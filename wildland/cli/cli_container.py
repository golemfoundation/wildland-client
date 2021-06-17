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

# pylint: disable=too-many-lines,redefined-outer-name
"""
Manage containers
"""

from pathlib import PurePosixPath, Path
from typing import Iterable, List, Optional, Sequence, Tuple
from itertools import combinations
import os
import sys
import logging
import threading
import re
import signal
import tempfile
import click
import daemon
import yaml

from click import ClickException
from daemon import pidfile
from xdg import BaseDirectory

from wildland.wildland_object.wildland_object import WildlandObject
from wildland.storage_sync.base import SyncConflict, BaseSyncer
from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit as base_edit, modify_manifest, add_field, del_field, \
    set_field, del_nested_field, find_manifest_file, dump as base_dump
from .cli_storage import do_create_storage_from_templates
from ..container import Container
from ..exc import WildlandError
from ..manifest.manifest import ManifestError
from ..manifest.template import TemplateManager
from ..publish import Publisher
from ..remounter import Remounter
from ..storage import Storage, StorageBackend
from ..hashdb import HashDb
from ..log import init_logging

try:
    RUNTIME_DIR = Path(BaseDirectory.get_runtime_dir())
except KeyError:
    RUNTIME_DIR = Path.home() / 'run'
    RUNTIME_DIR.mkdir(exist_ok=True)

MW_PIDFILE = RUNTIME_DIR / 'wildland-mount-watch.pid'
MW_DATA_FILE = RUNTIME_DIR / 'wildland-mount-watch.data'

logger = logging.getLogger('cli_container')


@aliased_group('container', short_help='container management')
def container_():
    """
    Manage containers
    """


class OptionRequires(click.Option):
    """
    Helper class to provide conditional required for click.Option
    """
    def __init__(self, *args, **kwargs):
        try:
            self.required_opt = kwargs.pop('requires')
        except KeyError as ke:
            raise click.UsageError("'requires' parameter must be present") from ke
        kwargs['help'] = kwargs.get('help', '') + \
            ' NOTE: this argument requires {}'.format(self.required_opt)
        super().__init__(*args, **kwargs)

    def handle_parse_result(self, ctx: click.Context, opts, args):
        if self.name in opts and self.required_opt not in opts:
            raise click.UsageError("option --{} requires --{}".format(
                self.name, self.required_opt))
        self.prompt = None # type: ignore
        return super().handle_parse_result(ctx, opts, args)


@container_.command(short_help='create container')
@click.option('--owner', '--user',
              help='user for signing')
@click.option('--path', multiple=True, required=False,
              help='mount path (can be repeated)')
@click.option('--category', multiple=True, required=False,
              help='category, will be used to generate mount paths')
@click.option('--title', multiple=False, required=False,
              help='container title')
@click.option('--update-user/--no-update-user', '-u/-n', default=False, show_default=True,
              help='attach the container to the user')
@click.option('--storage-template', '--template', multiple=False, required=False,
              help='use a storage template to generate storages (see wl storage-template)')
@click.option('--local-dir', multiple=False, required=False,
              help='local directory to be passed to storage template (requires --storage-template)')
@click.option('--access', multiple=True, required=False,
              help='allow additional users access to this container manifest')
@click.option('--no-publish', is_flag=True,
              help='do not publish the container after creation')
@click.option('--encrypt-manifest/--no-encrypt-manifest', default=True, required=False,
              show_default=True, help='if --no-encrypt, this manifest will not be encrypted and '
              '--access cannot be used.')
@click.argument('name', metavar='CONTAINER', required=False)
@click.pass_obj
def create(obj: ContextObj, owner: Optional[str], path: Sequence[str], name: Optional[str],
        update_user: bool, access: Sequence[str], no_publish: bool, title: Optional[str],
        category: Sequence[str], storage_template: Optional[str], local_dir: Optional[str],
        encrypt_manifest: bool):
    """
    Create a new container manifest.
    """

    if local_dir and not storage_template:
        raise CliError('--local-dir requires --storage-template')

    if access and not encrypt_manifest:
        raise CliError('--no-encrypt and --access are mutually exclusive')

    if category and not title:
        if not name:
            raise CliError('--category option requires --title or container name')
        title = name

    storage_templates = []

    if storage_template:
        try:
            template_dir_path = obj.client.dirs[WildlandObject.Type.TEMPLATE]
            tpl_manager = TemplateManager(template_dir_path)
            storage_templates = tpl_manager.get_template_file_by_name(storage_template).templates
        except WildlandError as we:
            raise CliError(f'Could not load [{storage_template}] storage template. {we}') from we

    if access:
        access_list = [{'user': obj.client.load_object_from_name(
            WildlandObject.Type.USER, user).owner} for user in access]
    elif not encrypt_manifest:
        access_list = [{'user': '*'}]
    else:
        access_list = []

    owner_user = obj.client.load_object_from_name(WildlandObject.Type.USER,
        owner or '@default-owner')

    container = Container(
        owner=owner_user.owner,
        paths=[PurePosixPath(p) for p in path],
        backends=[],
        client=obj.client,
        title=title,
        categories=[PurePosixPath(c) for c in category],
        access=access_list
    )

    container_path = obj.client.save_new_object(WildlandObject.Type.CONTAINER, container, name)
    click.echo(f'Created: {container_path}')

    if storage_templates:
        try:
            do_create_storage_from_templates(obj.client, container, storage_templates, local_dir,
                                             no_publish=no_publish)
        except (WildlandError, ValueError) as ex:
            click.echo(f'Removing container: {container_path}')
            container_path.unlink()
            raise WildlandError(f'Failed to create storage from template. {ex}') from ex

    if update_user:
        if not owner_user.local_path:
            raise WildlandError('Cannot update user because the manifest path is unknown')
        click.echo('Attaching container to user')

        owner_user.add_catalog_entry(str(obj.client.local_url(container_path)))
        obj.client.save_object(WildlandObject.Type.USER, owner_user)

    if not no_publish:
        try:
            owner_user = obj.client.load_object_from_name(WildlandObject.Type.USER, container.owner)
            if owner_user.has_catalog:
                click.echo(f'publishing container {container.uuid_path}...')
                publisher = Publisher(obj.client, container)
                publisher.publish_container()
        except WildlandError as ex:
            raise WildlandError(f"Failed to publish container: {ex}") from ex


@container_.command(short_help='update container')
@click.option('--storage', multiple=True,
              help='storage to use (can be repeated)')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def update(obj: ContextObj, storage, cont):
    """
    Update a container manifest.
    """

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)
    if container.local_path is None:
        raise WildlandError('Can only update a local manifest')

    if not storage:
        click.echo('No change')
        return

    for storage_name in storage:
        storage = obj.client.load_object_from_name(WildlandObject.Type.STORAGE, storage_name)
        assert storage.local_path
        click.echo(f'Adding storage: {storage.local_path}')
        container.add_storage_from_obj(storage, inline=False, storage_name=storage_name)

    obj.client.save_object(WildlandObject.Type.CONTAINER, container)


@container_.command(short_help='publish container manifest')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def publish(obj: ContextObj, cont):
    """
    Publish a container manifest to a container from manifests catalog.
    """

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)
    click.echo(f'publishing container {container.uuid_path}...')
    Publisher(obj.client, container).publish_container()


@container_.command(short_help='unpublish container manifest')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def unpublish(obj: ContextObj, cont):
    """
    Attempt to unpublish a container manifest under a given wildland path
    from all containers in manifests catalogs.
    """

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)
    click.echo(f'unpublishing container {container.uuid_path}...')
    Publisher(obj.client, container).unpublish_container()


def _container_info(container, users_and_bridge_paths):
    click.echo(container.local_path)
    try:
        if container.owner in users_and_bridge_paths:
            user_desc = ' (' + ', '.join(
                [str(p) for p in users_and_bridge_paths[container.owner]]) + ')'
        else:
            user_desc = ''
    except ManifestError:
        user_desc = ''
    click.echo(f'  owner: {container.owner}' + user_desc)
    for container_path in container.expanded_paths:
        click.echo(f'  path: {container_path}')
    for storage_path in container.get_backends_description():
        click.echo(f'  storage: {storage_path}')
    click.echo()


@container_.command('list', short_help='list containers', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known containers.
    """
    users_and_bridge_paths = {}
    for user, bridge_paths in obj.client.load_users_with_bridge_paths(only_default_user=True):
        if bridge_paths:
            users_and_bridge_paths[user.owner] = bridge_paths

    for container in obj.client.load_all(WildlandObject.Type.CONTAINER):
        _container_info(container, users_and_bridge_paths)


@container_.command(short_help='show container summary')
@click.argument('name', metavar='CONTAINER')
@click.pass_obj
def info(obj: ContextObj, name):
    """
    Show information about single container.
    """
    users_and_bridge_paths = {}
    for user, bridge_paths in obj.client.load_users_with_bridge_paths(only_default_user=True):
        if bridge_paths:
            users_and_bridge_paths[user.owner] = bridge_paths

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, name)

    _container_info(container, users_and_bridge_paths)


@container_.command('delete', short_help='delete a container', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even when using local storage manifests; ignore errors on parse')
@click.option('--cascade', is_flag=True,
              help='also delete local storage manifests')
@click.option('--no-unpublish', '-n', is_flag=True,
              help='do not attempt to unpublish the container before deleting it')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade, no_unpublish):
    """
    Delete a container.
    """
    # TODO: also consider detecting user-container link (i.e. user's main container).

    try:
        container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, name)
    except ManifestError as ex:
        if force:
            click.echo(f'Failed to load manifest: {ex}')
            try:
                path = obj.client.find_local_manifest(WildlandObject.Type.CONTAINER, name)
                if path:
                    click.echo(f'Deleting file {path}')
                    path.unlink()
            except ManifestError:
                # already removed
                pass
            if cascade:
                click.echo('Unable to cascade remove: manifest failed to load.')
            return
        click.echo(f'Failed to load manifest, cannot delete: {ex}')
        click.echo('Use --force to force deletion.')
        return

    if not container.local_path:
        raise WildlandError('Can only delete a local manifest')

    # unmount if mounted
    try:
        for mount_path in obj.fs_client.get_unique_storage_paths(container):
            storage_id = obj.fs_client.find_storage_id_by_path(mount_path)

            if storage_id:
                obj.fs_client.unmount_storage(storage_id)

            for storage_id in obj.fs_client.find_all_subcontainers_storage_ids(container):
                obj.fs_client.unmount_storage(storage_id)

    except FileNotFoundError:
        pass

    has_local = False

    for backend in container.load_raw_backends(include_inline=False):
        path = obj.client.parse_file_url(backend, container.owner)
        if path and path.exists():
            if cascade:
                click.echo('Deleting storage: {}'.format(path))
                path.unlink()
            else:
                click.echo('Container refers to a local manifest: {}'.format(path))
                has_local = True

    if has_local and not force:
        raise CliError('Container refers to local manifests, not deleting '
                       '(use --force or --cascade)')

    # unpublish
    if not no_unpublish:
        try:
            click.echo(f'unpublishing container {container.uuid_path}...')
            Publisher(obj.client, container).unpublish_container()
        except WildlandError:
            # not published
            pass

    click.echo(f'Deleting: {container.local_path}')
    container.local_path.unlink()


container_.add_command(sign)
container_.add_command(verify)


@container_.group(short_help='modify container manifest')
def modify():
    """
    Commands for modifying container manifests.
    """


@modify.resultcallback()
@click.pass_context
def _republish(ctx, params):
    """
    Republish modified container manifest.

    If container is already published, any modification should be republish
    unless publish is False.

    Using 'resultcallback' enforce that every 'modify' subcommand have to
    return (container, publish) to handle republishing.
    """
    container, publish = params

    if publish:
        try:
            click.echo(f're-publishing container {container.uuid_path}...')
            Publisher(ctx.obj.client, container).republish_container()
        except WildlandError as ex:
            raise WildlandError(f"Failed to republish container: {ex}") from ex

@modify.command(short_help='add path to the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to add')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_path(ctx: click.Context, input_file, path, publish):
    """
    Add path to the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=add_field, field='paths', values=path)

    return container, publish


@modify.command(short_help='remove path from the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to remove')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_path(ctx: click.Context, input_file, path, publish):
    """
    Remove path from the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=del_field, field='paths', values=path)

    return container, publish


@modify.command(short_help='set title in the manifest')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.option('--title', metavar='TEXT', required=True, help='Title to set')
@click.pass_context
def set_title(ctx: click.Context, input_file, title, publish):
    """
    Set title in the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=set_field, field='title', value=title)

    return container, publish

@modify.command(short_help='add category to the manifest')
@click.option('--category', metavar='PATH', required=True, multiple=True,
              help='Category to add')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_category(ctx: click.Context, input_file, category, publish):
    """
    Add category to the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=add_field, field='categories', values=category)

    return container, publish


@modify.command(short_help='remove category from the manifest')
@click.option('--category', metavar='PATH', required=True, multiple=True,
              help='Category to remove')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_category(ctx: click.Context, input_file, category, publish):
    """
    Remove category from the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=del_field, field='categories', values=category)

    return container, publish


@modify.command(short_help='allow additional user(s) access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users to add access for')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_access(ctx: click.Context, input_file, access, publish):
    """
    Allow an additional user access to this manifest.
    """
    processed_access = []

    for user in access:
        user = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user)
        processed_access.append({'user': user.owner})

    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=add_field, field='access', values=processed_access)

    return container, publish


@modify.command(short_help='stop additional user(s) from having access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users whose access should be revoked')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_access(ctx: click.Context, input_file, access, publish):
    """
    Remove category from the manifest.
    """
    processed_access = []

    for user in access:
        user = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user)
        processed_access.append({'user': user.owner})

    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=del_field, field='access', values=processed_access)

    return container, publish


@modify.command(short_help='do not encrypt this manifest at all')
@click.argument('input_file', metavar='FILE')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.pass_context
def set_no_encrypt_manifest(ctx: click.Context, input_file, publish):
    """
    Set title in the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=set_field, field='access', value=[{'user': '*'}])

    return container, publish


@modify.command(short_help='encrypt this manifest so that it is accessible only to its owner')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def set_encrypt_manifest(ctx: click.Context, input_file, publish):
    """
    Set title in the manifest.
    """
    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=set_field, field='access', value=[])

    return container, publish


@modify.command(short_help='remove storage backend from the manifest')
@click.option('--storage', metavar='TEXT', required=True, multiple=True,
              help='Storage to remove. Can be either the backend_id of a storage or position in '
                   'storage list (starting from 0)')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_storage(ctx: click.Context, input_file, storage, publish):
    """
    Remove category from the manifest.
    """
    container_manifest = find_manifest_file(ctx.obj.client, input_file, 'container').read_bytes()
    container_yaml = list(yaml.safe_load_all(container_manifest))[1]
    storages_obj = container_yaml.get('backends', {}).get('storage', {})

    idxs_to_delete = []

    for s in storage:
        if s.isnumeric():
            idxs_to_delete.append(int(s))
        else:
            for idx, obj_storage in enumerate(storages_obj):
                if obj_storage['backend-id'] == s:
                    idxs_to_delete.append(idx)

    click.echo('Storage indexes to remove: ' + str(idxs_to_delete))

    container = _resolve_container(ctx, input_file, modify_manifest,
                                   edit_func=del_nested_field, fields=['backends', 'storage'],
                                   keys=idxs_to_delete)

    return container, publish


def prepare_mount(obj: ContextObj,
                  container: Container,
                  container_name: str,
                  user_paths: Iterable[Iterable[PurePosixPath]],
                  remount: bool,
                  with_subcontainers: bool,
                  subcontainer_of: Optional[Container],
                  verbose: bool,
                  only_subcontainers: bool):
    """
    Prepare 'params' argument for WildlandFSClient.mount_multiple_containers() to mount selected
        container and its subcontainers (depending on options).

    :param obj: command context from click
    :param container: container object to mount
    :param container_name: container name - used for diagnostic messages (if verbose=True)
    :param user_paths: paths of the container owner - ['/'] for default user
    :param remount: should remount?
    :param with_subcontainers: should include subcontainers?
    :param subcontainer_of: it is a subcontainer
    :param verbose: print all messages
    :param only_subcontainers: only mount subcontainers
    :return: combined 'params' argument
    """
    # avoid iterating manifests catalog recursively, again
    if with_subcontainers and not container.is_manifests_catalog:
        subcontainers = list(obj.client.all_subcontainers(container))
    else:
        subcontainers = []

    if not subcontainers or not only_subcontainers:
        storages = obj.client.get_storages_to_mount(container)
        primary_storage_id = obj.fs_client.find_primary_storage_id(container)

        if primary_storage_id is None:
            if verbose:
                click.echo(f'new: {container_name}')
            yield (container, storages, user_paths, subcontainer_of)
        elif remount:
            storages_to_remount = []

            orphaned_storage_paths = obj.fs_client.get_orphaned_container_storage_paths(
                container, storages)

            for path in orphaned_storage_paths:
                storage_id = obj.fs_client.find_storage_id_by_path(path)
                assert storage_id is not None
                click.echo(f'Removing orphaned storage {path} (id: {storage_id})')
                obj.fs_client.unmount_storage(storage_id)

            for storage in storages:
                if obj.fs_client.should_remount(container, storage, user_paths):
                    storages_to_remount.append(storage)

                    if verbose:
                        click.echo(f'changed: {storage.backend_id}')
                else:
                    if verbose:
                        click.echo(f'not changed: {storage.backend_id}')

            yield (container, storages_to_remount, user_paths, subcontainer_of)
        else:
            raise WildlandError(f'Already mounted: {container.local_path}')

    if with_subcontainers and subcontainers:
        # keep the parent container mounted, when touching its subcontainers -
        # if they all point to the parent, this will avoid mounting and
        # unmounting it each time
        storage = obj.client.select_storage(container)
        with StorageBackend.from_params(storage.params, deduplicate=True):
            for subcontainer in subcontainers:
                # TODO: use MR !240 to pass a container set to prepare mount
                if isinstance(subcontainer, Container) and\
                        subcontainer.uuid == container.uuid:
                    continue
                if isinstance(subcontainer, Container):
                    yield from prepare_mount(obj, subcontainer,
                                             f'{container_name}:{subcontainer.paths[0]}',
                                             user_paths, remount, with_subcontainers, container,
                                             verbose, only_subcontainers)


@container_.command(short_help='mount container')
@click.option('--remount/--no-remount', '-r/-n', default=True, show_default=True,
              help='Remount existing container, if found')
@click.option('--save', '-s', is_flag=True,
              help='Save the container to be mounted at startup')
@click.option('--import-users/--no-import-users', is_flag=True, default=True, show_default=True,
              help='Import encountered users on the WildLand path to the container(s)')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=True,
              show_default=True, help='Do not mount subcontainers of this container.')
@click.option('--only-subcontainers', '-b', is_flag=True, default=False, show_default=True,
              help='If a container has subcontainers, mount only the subcontainers')
@click.option('--list-all', '-l', is_flag=True,
              help='During mount, list all containers, including those who '
                   'did not need to be changed')
@click.option('--manifests-catalog', '-m', is_flag=True, default=False, show_default=True,
              help='Allow mounting containers from manifest catalogs')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount(obj: ContextObj, container_names: Tuple[str], remount: bool, save: bool,
          import_users: bool, with_subcontainers: bool, only_subcontainers: bool, list_all: bool,
          manifests_catalog: bool) -> None:
    """
    Mount a container given by name or path to manifest. Repeat the argument to
    mount multiple containers.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    _mount(obj, container_names, remount, save, import_users,
           with_subcontainers, only_subcontainers, list_all, manifests_catalog)


def _mount(obj: ContextObj, container_names: Sequence[str],
           remount: bool = True, save: bool = True, import_users: bool = True,
           with_subcontainers: bool = True, only_subcontainers: bool = False,
           list_all: bool = True, manifests_catalog: bool = False) -> None:

    # if we want to mount all containers, check if all are published
    if any((str(c).endswith(':*:') for c in container_names)):
        not_published = Publisher.list_unpublished_containers(obj.client)
        n_container = len(list(obj.client.dirs[WildlandObject.Type.CONTAINER].glob('*.yaml')))

        # if all containers are unpublished DO NOT print warning
        if not_published and len(not_published) != n_container:
            click.echo("WARN: Some local containers (or container updates) are not published:\n" +
                       '\n'.join(not_published))

    obj.fs_client.ensure_mounted()

    if import_users:
        obj.client.auto_import_users = True

    params: List[Tuple[Container, List[Storage], List[Iterable[PurePosixPath]], Container]] = []

    fails: List[str] = []

    counter = 0

    for container_name in container_names:
        current_params: List[Tuple[Container, List[Storage],
                                   List[Iterable[PurePosixPath]], Container]] = []

        try:
            containers = obj.client.load_containers_from(
                container_name, include_manifests_catalog=manifests_catalog)

        except WildlandError as ex:
            fails.append(container_name + ':' + str(ex) + '\n')
            continue

        try:
            reordered, em_cont, failed = obj.client.ensure_mount_reference_container(containers)
            if failed:
                fails.append(em_cont)
            for container in reordered:
                counter += 1
                if not list_all:
                    print(f"Loading containers. Loaded {counter}...", end='\r')
                try:
                    user_paths = obj.client.get_bridge_paths_for_user(container.owner)
                    mount_params = prepare_mount(
                        obj, container, str(container), user_paths,
                        remount, with_subcontainers, None, list_all, only_subcontainers)
                    current_params.extend(mount_params)
                except WildlandError as ex:
                    fails.append(f'Cannot mount container {container.uuid}: {str(ex)}')
        except WildlandError as ex:
            fails.append(f'Failed to load all containers from {container_name}:{str(ex)}')

        params.extend(current_params)

    if not list_all and params:
        print('\n')
    if len(params) > 1:
        click.echo(f'Mounting {len(params)} containers')
        obj.fs_client.mount_multiple_containers(params, remount=remount)
    elif len(params) > 0:
        click.echo('Mounting 1 container')
        obj.fs_client.mount_multiple_containers(params, remount=remount)
    else:
        click.echo('No containers need (re)mounting')

    if save:
        default_containers = obj.client.config.get('default-containers')
        default_containers_set = set(default_containers)
        new_default_containers = default_containers.copy()
        for container_name in container_names:
            if container_name in default_containers_set:
                click.echo(f'Already in default-containers: {container_name}')
                continue
            click.echo(f'Adding to default-containers: {container_name}')
            default_containers_set.add(container_name)
            new_default_containers.append(container_name)
        if len(new_default_containers) > len(default_containers):
            obj.client.config.update_and_save(
                {'default-containers': new_default_containers})

    if fails:
        raise WildlandError('\n'.join(fails))


@container_.command(short_help='unmount container', alias=['umount'])
@click.option('--path', metavar='PATH',
              help='mount path to search for')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=True,
              show_default=True, help='Do not umount subcontainers.')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=False)
@click.pass_obj
def unmount(obj: ContextObj, path: str, with_subcontainers: bool, container_names: Sequence[str]):
    """
    Unmount a container. You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    """
    _unmount(obj, container_names=container_names, path=path, with_subcontainers=with_subcontainers)


def _unmount(obj: ContextObj, container_names: Sequence[str], path: str,
        with_subcontainers: bool = True):
    obj.fs_client.ensure_mounted()

    if bool(container_names) + bool(path) != 1:
        raise click.UsageError('Specify either container or --path')

    failed = False
    exc_msg = 'Failed to load some container manifests:\n'
    storage_ids = []

    if container_names:
        for container_name in container_names:
            try:
                container_storage_ids = _collect_storage_ids_by_container_name(
                    obj, container_name, with_subcontainers)
                storage_ids.extend(container_storage_ids)
            except WildlandError as ex:
                failed = True
                exc_msg += str(ex) + '\n'
    else:
        container_storage_ids = _collect_storage_ids_by_container_path(
            obj, path, with_subcontainers)
        storage_ids.extend(container_storage_ids)

    if not storage_ids:
        raise WildlandError('No containers mounted')

    # dividing by 2 as every container has respective hidden pseudo-manifest
    containers_count_without_submanifests = len(storage_ids) // 2
    click.echo(f'Unmounting {containers_count_without_submanifests} containers')

    for storage_id in storage_ids:
        obj.fs_client.unmount_storage(storage_id)

    if failed:
        raise WildlandError(exc_msg)


def _collect_storage_ids_by_container_name(obj: ContextObj, container_name: str,
        with_subcontainers: bool = True) -> List[int]:

    storage_ids = []

    for container in obj.client.load_containers_from(container_name):
        unique_storage_paths = obj.fs_client.get_unique_storage_paths(container)

        for mount_path in unique_storage_paths:
            storage_id = obj.fs_client.find_storage_id_by_path(mount_path)
            is_pseudomanifest = _is_pseudomanifest_primary_mount_path(mount_path)

            if storage_id is None:
                assert not is_pseudomanifest
                click.echo(f'Not mounted: {mount_path}')
            else:
                if not is_pseudomanifest:
                    click.echo(f'Will unmount: {mount_path}')
                storage_ids.append(storage_id)

        if with_subcontainers:
            storage_ids.extend(
                obj.fs_client.find_all_subcontainers_storage_ids(container))

    return storage_ids


def _collect_storage_ids_by_container_path(obj: ContextObj, path: str,
        with_subcontainers: bool = True) -> List[int]:
    """
    Return all storage IDs corresponding to a given mount path.
    """

    storage_ids = obj.fs_client.find_all_storage_ids_by_path(PurePosixPath(path))
    all_storage_ids = []

    for storage_id in storage_ids:
        all_storage_ids.append(storage_id)

        if _is_pseudomanifest_storage_id(obj, storage_id):
            logger.debug('Ignoring unmounting solely pseudomanifest path (storage ID = %d)',
                         storage_id)
            continue

        if with_subcontainers:
            container = obj.fs_client.get_container_from_storage_id(storage_id)
            subcontainer_storage_ids = obj.fs_client.find_all_subcontainers_storage_ids(container)
            all_storage_ids.extend(subcontainer_storage_ids)

    return all_storage_ids


def _is_pseudomanifest_storage_id(obj: ContextObj, storage_id: int) -> bool:
    """
    Check whether given storage ID corresponds to a pseudomanifest storage.
    """
    primary_path = obj.fs_client.get_primary_unique_mount_path_from_storage_id(storage_id)
    return _is_pseudomanifest_primary_mount_path(primary_path)


def _is_pseudomanifest_primary_mount_path(path: PurePosixPath) -> bool:
    """
    Check whether given path represents primary pseudomanifest mount path.
    """
    pattern = r'^/.users/[0-9a-z-]+:/.backends/[0-9a-z-]+/[0-9a-z-]+-pseudomanifest$'
    path_regex = re.compile(pattern)
    return bool(path_regex.match(str(path)))


def terminate_daemon(pfile, error_message):
    """
    Terminate a daemon running at specified pfile. If daemon not running, raise error message.
    """
    if os.path.exists(pfile):
        with open(pfile) as pid:
            try:
                os.kill(int(pid.readline()), signal.SIGINT)
            except ProcessLookupError:
                os.remove(pfile)
    else:
        raise WildlandError(error_message)


@container_.command('mount-watch', short_help='mount container')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount_watch(obj: ContextObj, container_names):
    """
    Watch for manifest files inside Wildland, and keep the filesystem mount
    state in sync.
    """

    obj.fs_client.ensure_mounted()
    if os.path.exists(MW_PIDFILE):
        raise ClickException("Mount-watch already running; use stop-mount-watch to stop it "
                             "or add-mount-watch to watch more containers.")
    if container_names:
        with open(MW_DATA_FILE, 'w') as file:
            file.truncate(0)
            file.write("\n".join(container_names))

    remounter = Remounter(obj.client, obj.fs_client, container_names)

    with daemon.DaemonContext(pidfile=pidfile.TimeoutPIDLockFile(MW_PIDFILE),
                              stdout=sys.stdout, stderr=sys.stderr, detach_process=True):
        init_logging(False, '/tmp/wl-mount-watch.log')
        remounter.run()


@container_.command('stop-mount-watch', short_help='stop mount container watch')
def stop_mount_watch():
    """
    Stop watching for manifest files inside Wildland.
    """
    terminate_daemon(MW_PIDFILE, "Mount-watch not running.")


@container_.command('add-mount-watch', short_help='mount container')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def add_mount_watch(obj: ContextObj, container_names):
    """
    Add additional container manifest patterns to daemon that watches for manifest files inside
    Wildland.
    """

    if os.path.exists(MW_DATA_FILE):
        with open(MW_DATA_FILE, 'r') as file:
            old_container_names = file.read().split('\n')
        container_names.extend(old_container_names)

    stop_mount_watch()

    mount_watch(obj, container_names)


def syncer_pidfile_for_container(container: Container) -> Path:
    """
    Helper function that returns a pidfile for a given container's sync process.
    """
    container_id = container.uuid
    return Path(BaseDirectory.get_runtime_dir()) / f'wildland-sync-{container_id}.pid'


def _get_storage_by_id_or_type(id_or_type: str, storages: List[Storage]) -> Storage:
    """
    Helper function to find a storage by listed id or type.
    """
    try:
        return [storage for storage in storages
                if id_or_type in (storage.backend_id, storage.params['type'])][0]
    except IndexError:
        # pylint: disable=raise-missing-from
        raise WildlandError(f'Storage {id_or_type} not found.')


@container_.command('sync', short_help='start syncing a container')
@click.argument('cont', metavar='CONTAINER')
@click.option('--target-storage', help='specify target storage. Default: first non-local storage'
                                       ' listed in manifest. Can be specified as backend_id or as '
                                       'storage type (e.g. s3)')
@click.option('--source-storage', help='specify source storage. Default: first local storage '
                                       'listed in manifest. Can be specified as backend_id or as '
                                       'storage type (e.g. s3)')
@click.option('--one-shot', is_flag=True, default=False, show_default=True,
              help='perform only one-time sync, do not start syncing daemon')
@click.pass_obj
def sync_container(obj: ContextObj, target_storage, source_storage, one_shot, cont):
    """
    Keep the given container in sync across the local storage and selected remote storage
    (by default the first listed in manifest).
    """

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)

    sync_pidfile = syncer_pidfile_for_container(container)

    if os.path.exists(sync_pidfile):
        raise ClickException("Sync process for this container is already running; use "
                             "stop-sync to stop it.")

    all_storages = list(obj.client.all_storages(container))

    if source_storage:
        source_object = _get_storage_by_id_or_type(source_storage, all_storages)
    else:
        try:
            source_object = [storage for storage in all_storages
                                  if obj.client.is_local_storage(storage.params['type'])][0]
        except IndexError:
            # pylint: disable=raise-missing-from
            raise WildlandError('No local storage backend found')

    source_backend = StorageBackend.from_params(source_object.params)
    default_remotes = obj.client.config.get('default-remote-for-container')

    if target_storage:
        target_object = _get_storage_by_id_or_type(target_storage, all_storages)
        default_remotes[container.uuid] = target_object.backend_id
        obj.client.config.update_and_save({'default-remote-for-container': default_remotes})
    else:
        target_remote_id = default_remotes.get(container.uuid)
        try:
            target_object = [storage for storage in all_storages
                             if target_remote_id == storage.backend_id
                             or (not target_remote_id and
                                 not obj.client.is_local_storage(storage.params['type']))][0]
        except IndexError:
            # pylint: disable=raise-missing-from
            raise CliError('No remote storage backend found: specify --target-storage.')

    target_backend = StorageBackend.from_params(target_object.params)
    click.echo(f'Using remote backend {target_backend.backend_id} '
               f'of type {target_backend.TYPE}')

    # Store information about container/backend mappings
    hash_db = HashDb(obj.client.config.base_dir)
    hash_db.update_storages_for_containers(container.uuid,
                                           [source_backend, target_backend])

    if container.local_path:
        container_path = PurePosixPath(container.local_path)
        container_name = container_path.name.replace(''.join(container_path.suffixes), '')
    else:
        container_name = cont

    source_backend.set_config_dir(obj.client.config.base_dir)
    target_backend.set_config_dir(obj.client.config.base_dir)
    syncer = BaseSyncer.from_storages(source_storage=source_backend,
                                      target_storage=target_backend,
                                      log_prefix=f'Container: {container_name}',
                                      one_shot=one_shot, continuous=not one_shot,
                                      unidirectional=False, can_require_mount=False)

    if one_shot:
        syncer.one_shot_sync()
        return

    with daemon.DaemonContext(pidfile=pidfile.TimeoutPIDLockFile(sync_pidfile),
                              stdout=sys.stdout, stderr=sys.stderr, detach_process=True):
        init_logging(False, f'/tmp/wl-sync-{container.uuid}.log')
        try:
            syncer.start_sync()
        except FileNotFoundError as e:
            click.echo(f"Storage root not found! Details: {e}")
            return
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            syncer.stop_sync()


@container_.command('stop-sync', short_help='stop syncing a container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def stop_syncing_container(obj: ContextObj, cont):
    """
    Keep the given container in sync across storages.
    """

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)

    sync_pidfile = syncer_pidfile_for_container(container)

    terminate_daemon(sync_pidfile, "Sync for this container is not running.")


@container_.command('list-conflicts', short_help='list detected file conflicts across storages')
@click.argument('cont', metavar='CONTAINER')
@click.option('--force-scan', is_flag=True,
              help='force iterating over all storages and computing hash for all files; '
                   'can be very slow')
@click.pass_obj
def list_container_conflicts(obj: ContextObj, cont, force_scan):
    """
    List conflicts detected by the syncing tool.
    """
    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)

    storages = [StorageBackend.from_params(storage.params) for storage in
                obj.client.all_storages(container)]

    if not force_scan:
        for storage in storages:
            storage.set_config_dir(obj.client.config.base_dir)

    conflicts = []
    for storage1, storage2 in combinations(storages, 2):
        syncer = BaseSyncer.from_storages(source_storage=storage1,
                                          target_storage=storage2,
                                          log_prefix=f'Container: {cont}',
                                          one_shot=False, continuous=False, unidirectional=False,
                                          can_require_mount=False)

        conflicts.extend([error for error in syncer.iter_errors()
                          if isinstance(error, SyncConflict)])

    if conflicts:
        click.echo("Conflicts detected on:")
        for c in conflicts:
            click.echo(str(c))
    else:
        click.echo("No conflicts were detected by container sync.")


@container_.command(short_help='duplicate a container')
@click.option('--new-name', help='name of the new container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def duplicate(obj: ContextObj, new_name, cont):
    """
    Duplicate an existing container manifest.
    """

    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)
    new_container = container.copy(new_name)

    path = obj.client.save_new_object(WildlandObject.Type.CONTAINER, new_container, new_name)
    click.echo(f'Created: {path}')


@container_.command(short_help='find container by absolute file or directory path')
@click.argument('path', metavar='PATH')
@click.pass_obj
def find(obj: ContextObj, path: str):
    """
    Find container by absolute or relative file/directory path. If the path is relative, it needs to
    be relative with respect to the current working directory (not to the Wildland's mountpoint).
    """
    absolute_path = Path(path).resolve()
    results = set(sorted([
        (fileinfo.backend_id, f'wildland:{fileinfo.storage_owner}:{fileinfo.container_path}:')
        for fileinfo in obj.fs_client.pathinfo(absolute_path)
    ]))

    if not results:
        raise CliError('Given path was not found in any storage')

    for result in results:
        (backend_id, wlpath) = result

        click.echo(f'Container: {wlpath}\n'
                   f'  Backend id: {backend_id}')


@container_.command(short_help='verify and dump contents of a container')
@click.option('--decrypt/--no-decrypt', '-d/-n', default=True, help='decrypt manifest')
@click.argument('path', metavar='FILE or WLPATH')
@click.pass_context
def dump(ctx: click.Context, path, decrypt):
    """
    Verify and dump contents of a container.
    """
    _resolve_container(ctx, path, base_dump, decrypt=decrypt)


@container_.command(short_help='edit container manifest in external tool')
@click.option('--editor', metavar='EDITOR',
    help='custom editor')
@click.option('--remount/--no-remount', '-r/-n', default=True,
    help='remount mounted container')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish edited container')
@click.argument('path', metavar='FILE or WLPATH')
@click.pass_context
def edit(ctx: click.Context, path, publish, editor, remount):
    """
    Edit container manifest in external tool.
    """
    container = _resolve_container(ctx, path, base_edit, editor=editor, remount=remount)

    if publish:
        click.echo(f're-publishing container {container.uuid_path}...')
        Publisher(ctx.obj.client, container).republish_container()


def _resolve_container(ctx: click.Context, path, callback, **callback_kwargs):
    client = ctx.obj.client

    if client.is_url(path) and not path.startswith('file:'):
        container = client.load_object_from_url(
            WildlandObject.Type.CONTAINER, path, client.config.get('@default'))

        with tempfile.NamedTemporaryFile(suffix='.tmp.container.yaml') as f:
            f.write(container.manifest.to_bytes())
            f.flush()

            ctx.invoke(callback, pass_ctx=ctx, input_file=f.name, **callback_kwargs)

            with open(f.name, 'rb') as file:
                data = file.read()

            container = client.load_object_from_bytes(WildlandObject.Type.CONTAINER, data)
    else:
        local_path = client.find_local_manifest(WildlandObject.Type.CONTAINER, path)

        if local_path:
            path = str(local_path)

        ctx.invoke(callback, pass_ctx=ctx, input_file=path, **callback_kwargs)
        container = client.load_object_from_name(WildlandObject.Type.CONTAINER, path)

    return container
