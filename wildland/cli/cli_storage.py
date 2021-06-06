# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Storage object
"""

from typing import Dict, Iterable, List, Optional, Tuple, Type, Union
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse, urlunparse
import functools
import logging
import uuid

import click

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import aliased_group, ContextObj, CliError
from ..client import Client
from .cli_common import sign, verify, edit, modify_manifest, set_field, add_field, del_field, dump
from ..container import Container
from ..storage import Storage
from ..manifest.template import TemplateManager, StorageTemplate
from ..publish import Publisher

from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..manifest.manifest import ManifestError
from ..exc import WildlandError

logger = logging.getLogger('cli-storage')


@aliased_group('storage', short_help='storage management')
def storage_():
    """Manage storages for container"""


@storage_.group(short_help='create storage')
def create():
    """
    Create a new storage manifest.

    The storage has to be associated with a specific container.
    """


def _make_create_command(backend: Type[StorageBackend]):
    params = [
        click.Option(['--container'], metavar='CONTAINER',
                     required=True,
                     help='Container this storage is for'),
        click.Option(['--trusted'], is_flag=True,
                     help='Make the storage trusted. Default: false'),
        click.Option(['--inline/--no-inline'], default=True,
                     help='Add the storage directly to container '
                     'manifest, instead of saving it to a file. Default: inline.'),
        click.Option(['--watcher-interval'], metavar='SECONDS', required=False,
                     help='Set the storage watcher-interval in seconds.'),
        click.Option(['--public-url'], metavar='PUBLICURL',
                     help='Set public base URL'),
        click.Option(['--access'], multiple=True, required=False, metavar='USER',
                     help='limit access to this storage to the provided users. '
                          'Default: same as the container.'),
        click.Option(['--encrypt-manifest/--no-encrypt-manifest'], default=True,
                     required=False,
                     help='default: encrypt. if --no-encrypt, this manifest will not be encrypted '
                          'and --access cannot be used. For inline storage, '
                          'container manifest might still be encrypted.'),
        click.Option(['--no-publish'], is_flag=True,
                            help='do not publish the container after creation'),
        click.Argument(['name'], metavar='NAME', required=False),
    ]

    params.extend(backend.cli_options())

    callback = functools.partial(_do_create, backend=backend)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage',
        params=params,
        callback=callback)
    return command


def _add_create_commands(group):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        name,
        container,
        trusted,
        inline,
        watcher_interval,
        public_url,
        access,
        encrypt_manifest,
        no_publish,
        **data):

    obj: ContextObj = click.get_current_context().obj

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, container)
    if not container.local_path:
        raise WildlandError('Need a local container')

    container_mount_path = container.paths[0]
    click.echo(f'Using container: {container.local_path} ({container_mount_path})')

    params = backend.cli_create(data)

    # remove default, non-required values
    for param, value in list(params.items()):
        if value is None or value == []:
            del params[param]

    if watcher_interval:
        params['watcher-interval'] = int(watcher_interval)

    params['backend-id'] = str(uuid.uuid4())
    if public_url is not None:
        params['public-url'] = public_url

    if not encrypt_manifest:
        access = [{'user': '*'}]
    elif access:
        access = [{'user': obj.client.load_object_from_name(
            WildlandObject.Type.USER, user).owner} for user in access]
    else:
        if container.access:
            access = container.access
        else:
            access = None

    storage = Storage(
        storage_type=backend.TYPE,
        owner=container.owner,
        container_path=container_mount_path,
        params=params,
        client=obj.client,
        trusted=params.get('trusted', trusted),
        access=access
    )
    storage.validate()
    click.echo(f'Adding storage {storage.backend_id} to container.')
    obj.client.add_storage_to_container(container, storage, inline, name)
    click.echo(f'Saved container {container.local_path}')

    if no_publish:
        return

    try:
        Publisher(obj.client, container).republish_container()
    except WildlandError as ex:
        raise WildlandError(f"Failed to republish container: {ex}") from ex


@storage_.command('list', short_help='list storages', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known storages.
    """
    for storage in obj.client.load_all(WildlandObject.Type.STORAGE):
        click.echo(storage.local_path)
        click.echo(f'  type: {storage.storage_type}')
        click.echo(f'  backend_id: {storage.backend_id}')
        if storage.storage_type in ['local', 'local-cached', 'local-dir-cached']:
            click.echo(f'  location: {storage.params["location"]}')

    for container in obj.client.load_all(WildlandObject.Type.CONTAINER):
        backends = list(container.get_backends_description(only_inline=True))
        if not backends:
            continue

        click.echo(f'{container.local_path} (inline)')
        for backend in backends:
            click.echo(backend)


@storage_.command('delete', short_help='delete a storage', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if used by containers or if manifest cannot be loaded')
@click.option('--no-cascade', is_flag=True,
              help='remove reference from containers')
@click.option('--container', metavar='CONTAINER',
              help='remove reference from specific containers')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, no_cascade, container):
    """
    Delete a storage.
    """

    try:
        local_path, used_by = _get_local_path_and_find_usage(obj.client, name)
    except ManifestError as ex:
        if force:
            click.echo(f'Failed to load manifest: {ex}')
            _delete_force(obj.client, name, no_cascade)
        else:
            click.echo(f'Failed to load manifest, cannot delete: {ex}')
            click.echo('Use --force to force deletion.')
            raise
        return

    if local_path:
        if no_cascade:
            for container_obj, _ in used_by:
                click.echo(f'Storage used in container: {container_obj.local_path}')
        else:
            _delete_cascade(obj.client, used_by)

        if used_by and not force and no_cascade:
            raise CliError('Storage is still used, not deleting '
                           '(use --force or remove --no-cascade)')

        click.echo(f'Deleting: {local_path}')
        local_path.unlink()
    else:
        if no_cascade:
            raise CliError('Inline storage cannot be deleted in --no-cascade mode')

        if len(used_by) > 1:
            if container is None:
                raise CliError(f'Storage {name} is used '
                               f'in multiple containers: {[str(cont) for cont, _ in used_by]} '
                               '(please specify container name with --container)')

            container_obj = obj.client.load_object_from_name(
                WildlandObject.Type.CONTAINER, container)
            used_by = [(cont, backend) for cont, backend in used_by
                       if cont.local_path == container_obj.local_path]

        if len(used_by) > 1:
            if not click.confirm('Several matching results have been found: \n'
                                 f'{used_by} \n'
                                 f'Do you want remove all listed storages?'):
                return

        _delete_cascade(obj.client, used_by)


def _get_local_path_and_find_usage(client: Client, name: str) \
        -> Tuple[Optional[Path],  List[Tuple[Container, Union[Path, str]]]]:
    try:
        storage = client.load_object_from_name(WildlandObject.Type.STORAGE, name)
    except ManifestError:
        raise
    except WildlandError:
        used_by = client.find_storage_usage(name)
        if not used_by:
            raise
        return None, used_by

    if not storage.local_path:
        raise WildlandError('Can only delete a local manifest')
    used_by = client.find_storage_usage(storage.backend_id)
    return storage.local_path, used_by


def _delete_force(client: Client, name: str, no_cascade: bool):
    try:
        path = client.find_local_manifest(WildlandObject.Type.STORAGE, name)
        if path:
            click.echo(f'Deleting file {path}')
            path.unlink()
    except ManifestError:
        # already removed
        pass
    if not no_cascade:
        click.echo('Unable to cascade remove: manifest failed to load.')


def _delete_cascade(client: Client, containers: List[Tuple[Container, Union[Path, str]]]):
    for container, backend in containers:
        click.echo(f'Removing {backend} from {container.local_path}')
        container.del_storage(backend)
        try:
            click.echo(f'Saving: {container.local_path}')
            client.save_object(WildlandObject.Type.CONTAINER, container)
        except ManifestError as ex:
            click.echo(f'Failed to modify container manifest, cannot delete: {ex}')


def do_create_storage_from_templates(client: Client, container: Container,
        storage_templates: Iterable[StorageTemplate], local_dir: Optional[str],
        no_publish: bool = False) -> None:
    """
    Create storages for a container from a given list of storage templates.
    :param client: Wildland client
    :param container: Wildland container
    :param storage_templates: list of storage templates
    :param local_dir: str to be passed to template renderer as a parameter, can be used by template
        creators
    :param no_publish: should the container not be published after creation
    """
    to_process: List[Tuple[Storage, Optional[StorageBackend], Path]] = []

    for template in storage_templates:
        storage = _create_storage_backend_from_template(client, container, template, local_dir)
        storage_cls = StorageBackend.types()[storage.storage_type]
        assert storage_cls.LOCATION_PARAM
        path = storage.params[storage_cls.LOCATION_PARAM]
        storage_backend = StorageBackend.from_params(storage.params)
        to_process.append((storage, storage_backend, path))

    for storage, backend, path in to_process:
        # Ensure that base path actually exists
        if storage.is_writeable and backend:
            try:
                with backend:
                    backend.mkdir(PurePosixPath(path))
                    click.echo(f'Created base path: {path}')
            except Exception as ex:
                click.echo(f'WARN: Could not create base path {path} in a writable '
                           f'storage [{backend.backend_id}]. {ex}')

        click.echo(f'Adding storage {storage.backend_id} to container.')
        client.add_storage_to_container(container=container, storage=storage, inline=True)
        click.echo(f'Saved container {container.local_path}')

        if no_publish:
            return

        try:
            Publisher(client, container).republish_container()
        except WildlandError as ex:
            raise WildlandError(f"Failed to republish container: {ex}") from ex


def _create_storage_backend_from_template(client: Client, container: Container,
        template: StorageTemplate, local_dir: Optional[str]) -> Storage:

    storage_fields = _get_storage_fields_from_template(template, container, local_dir)
    storage_type = storage_fields['type']
    storage_cls = StorageBackend.types()[storage_type]

    if storage_cls.LOCATION_PARAM and storage_cls.LOCATION_PARAM in storage_fields and \
            storage_fields[storage_cls.LOCATION_PARAM]:
        orig_location = storage_fields[storage_cls.LOCATION_PARAM]

        if client.is_url(orig_location):
            uri = urlparse(orig_location)
            path = Path(uri.path).resolve()
            location = urlunparse(
                (uri.scheme, uri.netloc, str(path), uri.params, uri.query, uri.fragment))
        else:
            path = Path(orig_location)
            location = orig_location

        storage_fields[storage_cls.LOCATION_PARAM] = str(location)

    return WildlandObject.from_fields(storage_fields, client, WildlandObject.Type.STORAGE,
        local_owners=client.config.get('local-owners'))


def _get_storage_fields_from_template(template: StorageTemplate, container: Container,
        local_dir: Optional[str]) -> Dict:
    try:
        storage_fields = template.get_storage_fields(container, local_dir)
    except ValueError as ex:
        click.echo(f'Failed to create storage from storage template: {ex}')
        raise ex

    return container.fill_storage_fields(storage_fields)


@storage_.command('create-from-template', short_help='create a storage from a storage template',
                  alias=['cs'])
@click.option('--storage-template', '--template', '-t', multiple=False, required=True,
              help='name of storage template to use')
@click.option('--local-dir', multiple=False, required=False,
              help='local directory to be passed to storage templates')
@click.option('--no-publish', is_flag=True,
              help='do not publish the container after creation')
@click.argument('cont', metavar='CONTAINER', required=True)
@click.pass_obj
def create_from_template(obj: ContextObj, cont, storage_template: str, local_dir=None,
                         no_publish=False):
    """
    Setup storage for a container from a storage template.
    """
    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)
    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

    try:
        storage_templates = template_manager.get_template_file_by_name(storage_template).templates

        do_create_storage_from_templates(obj.client, container, storage_templates, local_dir,
                                         no_publish=no_publish)
    except WildlandError as we:
        raise CliError(f'Could not create storage from [{storage_template}] template. {we}') from we


storage_.add_command(sign)
storage_.add_command(verify)
storage_.add_command(edit)
storage_.add_command(dump)

_add_create_commands(create)


@storage_.group(short_help='modify storage manifest')
def modify():
    """
    Commands for modifying storage manifests.
    """


@modify.command(short_help='set location in the manifest')
@click.argument('input_file', metavar='FILE')
@click.option('--location', metavar='PATH', required=True, help='Location to set')
@click.pass_context
def set_location(ctx: click.Context, input_file, location):
    """
    Set location in the manifest.
    """
    modify_manifest(ctx, input_file, set_field, 'location', location)


@modify.command(short_help='allow additional user(s) access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users to add access for')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_access(ctx: click.Context, input_file, access):
    """
    Add category to the manifest.
    """
    processed_access = []

    try:
        for user in access:
            user = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user)
            processed_access.append({'user': user.owner})
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    modify_manifest(ctx, input_file, add_field, 'access', processed_access)


@modify.command(short_help='stop additional user(s) from having access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users whose access should be revoked')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_access(ctx: click.Context, input_file, access):
    """
    Remove category from the manifest.
    """
    processed_access = []

    try:
        for user in access:
            user = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user)
            processed_access.append({'user': user.owner})
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    modify_manifest(ctx, input_file, del_field, 'access', processed_access)
