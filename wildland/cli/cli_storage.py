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

import types
from typing import Iterable, List, Optional, Sequence, Tuple, Type, Union
from pathlib import Path, PurePosixPath
import functools
import uuid
import click

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import aliased_group, ContextObj, CliError
from ..client import Client
from .cli_common import sign, verify, edit, modify_manifest, set_fields, add_fields, del_fields, \
    dump, check_if_any_options, check_options_conflict, publish, unpublish
from ..container import Container
from ..storage import Storage, _get_storage_by_id_or_type
from ..manifest.template import TemplateManager, StorageTemplate
from ..publish import Publisher
from ..log import get_logger
from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..storage_sync.base import SyncState
from ..manifest.manifest import ManifestError
from ..exc import WildlandError
from ..utils import format_command_options

logger = get_logger('cli-storage')


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
                     help='Make the storage trusted.'),
        click.Option(['--inline/--no-inline'], default=True,
                     help='Add the storage directly to container '
                     'manifest, instead of saving it to a file.'),
        click.Option(['--watcher-interval'], metavar='SECONDS', required=False, type=int,
                     help='Set the storage watcher-interval in seconds.'),
        click.Option(['--access'], multiple=True, required=False, metavar='USER',
                     help='limit access to this storage to the provided users. '
                          'Default: same as the container.'),
        click.Option(['--encrypt-manifest/--no-encrypt-manifest'], default=True,
                     required=False,
                     help='If --no-encrypt-manifest, this manifest will not be encrypted and '
                          '--access cannot be used. For inline storage, container manifest might '
                          'still be encrypted.'),
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
        callback=callback,
        context_settings={'show_default': True})
    setattr(command, "format_options", types.MethodType(format_command_options, command))
    return command


def _add_create_commands(group: click.core.Group):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        name: Optional[str],
        container: str,
        trusted: bool,
        inline: bool,
        watcher_interval: Optional[int],
        access: Sequence[str],
        encrypt_manifest: bool,
        no_publish: bool,
        **data):

    obj: ContextObj = click.get_current_context().obj

    container_obj = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, container)
    if not container_obj.local_path:
        raise WildlandError('Need a local container')

    container_mount_path = container_obj.paths[0]
    click.echo(f'Using container: {container_obj.local_path} ({container_mount_path})')

    params = backend.cli_create(data)

    # remove default, non-required values
    for param, value in list(params.items()):
        if value is None or value == []:
            del params[param]

    if watcher_interval:
        params['watcher-interval'] = watcher_interval

    params['backend-id'] = str(uuid.uuid4())

    access_users = None

    if not encrypt_manifest:
        access_users = [{'user': '*'}]
    elif access:
        access_users = [{'user': obj.client.load_object_from_name(
            WildlandObject.Type.USER, user).owner} for user in access]
    elif container_obj.access:
        access_users = container_obj.access

    storage = Storage(
        storage_type=backend.TYPE,
        owner=container_obj.owner,
        container=container_obj,
        params=params,
        client=obj.client,
        trusted=params.get('trusted', trusted),
        access=access_users
    )
    storage.validate()
    # try to load storage from params to check if everything is ok,
    # e.g., reference container is available
    obj.client.load_object_from_url_or_dict(WildlandObject.Type.STORAGE,
                                            storage.to_manifest_fields(inline=False),
                                            storage.owner, container=container_obj)
    click.echo(f'Adding storage {storage.backend_id} to container.')
    obj.client.add_storage_to_container(container_obj, storage, inline, name)
    click.echo(f'Saved container {container_obj.local_path}')

    if no_publish:
        return

    try:
        user = obj.client.load_object_from_name(WildlandObject.Type.USER, container_obj.owner)
        Publisher(obj.client, user).republish(container_obj)
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


@storage_.command('delete', short_help='delete a storage', alias=['rm', 'remove'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if used by containers or if manifest cannot be loaded;'
                   ' skip attempting to sync storage with remaining storage(s)')
@click.option('--no-cascade', is_flag=True,
              help='remove reference from containers')
@click.option('--container', metavar='CONTAINER',
              help='remove reference from specific containers')
@click.argument('names', metavar='NAME', nargs=-1)
def delete(obj: ContextObj, names, force: bool, no_cascade: bool, container: Optional[str]):
    """
    Delete a storage.
    """

    error_messages = ''
    for name in names:
        try:
            _delete(obj, name, force, no_cascade, container)
        except Exception as e:
            error_messages += f'{e}\n'

    if error_messages:
        raise CliError(f'Some storages could not be deleted:\n{error_messages.strip()}')


def _delete(obj: ContextObj, name: str, force: bool, no_cascade: bool, container: Optional[str]):
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

    container_to_sync = []
    container_failed_to_sync = []
    for container_obj, _ in used_by:
        if len(obj.client.get_all_storages(container_obj)) > 1 and not force:
            status = obj.client.get_sync_job_state(container_obj.sync_id)
            if status is None:
                container_to_sync.append(container_obj)
            elif status[0] != SyncState.SYNCED:
                click.echo(f"Syncing of {container_obj.uuid} is in progress.")
                return

    if container_to_sync:
        for c in container_to_sync:
            storage_to_delete = _get_storage_by_id_or_type(name, obj.client.all_storages(c))
            click.echo(f'Outdated storage for container {c.uuid}, attempting to sync storage.')
            target = None
            try:
                target = obj.client.get_remote_storage(c, excluded_storage=name)
            except WildlandError:
                pass
            if not target:
                try:
                    target = obj.client.get_local_storage(c, excluded_storage=name)
                except WildlandError:
                    # pylint: disable=raise-missing-from
                    raise WildlandError("Cannot find storage to sync data into.")
            logger.debug("sync: {%s} -> {%s}", storage_to_delete, target)
            response = obj.client.do_sync(c.uuid, c.sync_id, storage_to_delete.params,
                                          target.params, one_shot=True, unidir=True)
            logger.debug(response)
            msg, success = obj.client.wait_for_sync(c.sync_id)
            click.echo(msg)
            if not success:
                container_failed_to_sync.append(c.uuid)

    if container_failed_to_sync and not force:
        click.echo(f"Failed to sync storage for containers: {','.join(container_failed_to_sync)}")
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
        logger.warning('Unable to cascade remove: manifest failed to load.')


def _delete_cascade(client: Client, containers: List[Tuple[Container, Union[Path, str]]]):
    for container, backend in containers:
        click.echo(f'Removing {backend} from {container.local_path}')
        container.del_storage(backend)
        try:
            click.echo(f'Saving: {container.local_path}')
            client.save_object(WildlandObject.Type.CONTAINER, container)
        except ManifestError as ex:
            raise CliError(f'Failed to modify container manifest, cannot delete: {ex}') from ex


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
    to_process: List[Tuple[Storage, StorageBackend]] = []

    for template in storage_templates:
        try:
            storage = template.get_storage(client, container, local_dir)
        except ValueError as ex:
            raise CliError(f'Failed to create storage from storage template: {ex}') from ex

        storage_backend = StorageBackend.from_params(storage.params)
        to_process.append((storage, storage_backend))

    for storage, backend in to_process:
        if storage.is_writeable:
            _ensure_backend_location_exists(backend)

        click.echo(f'Adding storage {storage.backend_id} to container.')
        client.add_storage_to_container(container=container, storage=storage, inline=True)
        click.echo(f'Saved container {container.local_path}')

    if not no_publish:
        try:
            user = client.load_object_from_name(WildlandObject.Type.USER, container.owner)
            Publisher(client, user).republish(container)
        except WildlandError as ex:
            raise WildlandError(f"Failed to republish container: {ex}") from ex


def _ensure_backend_location_exists(backend: StorageBackend) -> None:
    path = backend.location

    if path is None:
        return
    try:
        with backend:
            if str(PurePosixPath(backend.location)) != backend.location:
                raise WildlandError('The `LOCATION_PARAM` of the backend is not a valid path.')
            backend.mkdir(PurePosixPath(path))
            click.echo(f'Created base path: {path}')
    except Exception as ex:
        logger.warning('Could not create base path %s in a writable storage [%s]. %s',
                       path, backend.backend_id, ex)


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
storage_.add_command(publish)
storage_.add_command(unpublish)

_add_create_commands(create)


@storage_.command(short_help='modify storage manifest')
@click.option('--location', metavar='PATH', help='location to set')
@click.option('--add-access', metavar='PATH', multiple=True, help='users to add access for')
@click.option('--del-access', metavar='PATH', multiple=True, help='users to remove access for')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def modify(ctx: click.Context,
           location, add_access, del_access, input_file
           ):
    """
    Command for modifying storage manifests.
    """
    check_if_any_options(ctx, location, add_access, del_access)
    check_options_conflict("access", add_access, del_access)

    try:
        add_access_owners = [
            {'user': ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
            for user in add_access]
        del_access_owners = [
            {'user': ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
            for user in del_access]
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    to_add = {'access': add_access_owners}
    to_del = {'access': del_access_owners}
    to_set = {}
    if location:
        to_set['location'] = location
    modify_manifest(ctx, input_file,
                    edit_funcs=[add_fields, del_fields, set_fields],
                    to_add=to_add,
                    to_del=to_del,
                    to_set=to_set,
                    logger=logger)
