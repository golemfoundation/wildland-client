# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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
# pylint: disable=too-many-lines
'''
Manage containers
'''

from pathlib import PurePosixPath, Path
from typing import List, Tuple, Dict, Optional, Iterable
import os
import uuid
import sys
import logging
import threading
import signal
import click
import daemon
import yaml

from click import ClickException
from daemon import pidfile
from xdg import BaseDirectory

from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit, modify_manifest, add_field, del_field, \
    set_field, del_nested_field, find_manifest_file, dump
from .cli_storage import do_create_storage_from_set
from ..container import Container
from ..exc import WildlandError
from ..storage import Storage, StorageBackend
from ..client import Client
from ..fs_client import WildlandFSClient, WatchEvent
from ..manifest.manifest import ManifestError
from ..manifest.template import TemplateManager
from ..sync import Syncer, list_storage_conflicts
from ..hashdb import HashDb
from ..log import init_logging
from ..wlpath import WildlandPath

MW_PIDFILE = Path(BaseDirectory.get_runtime_dir()) / 'wildland-mount-watch.pid'
MW_DATA_FILE = Path(BaseDirectory.get_runtime_dir()) / 'wildland-mount-watch.data'

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

    def handle_parse_result(self, ctx, opts, args):
        if self.name in opts and self.required_opt not in opts:
            raise click.UsageError("option --{} requires --{}".format(
                self.name, self.required_opt))
        # noinspection Mypy
        self.prompt = None
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
@click.option('--update-user/--no-update-user', '-u/-n', default=False,
              help='Attach the container to the user')
@click.option('--storage-set', '--set', multiple=False, required=False,
              help='Use a storage template set to generate storages (see wl storage-set)')
@click.option('--local-dir', multiple=False, required=False,
              help='local directory to be passed to storage templates (requires --storage-set)')
@click.option('--default-storage-set/--no-default-storage-set', default=True,
              help="use user's default storage template set (ignored if --storage-set is used)")
@click.option('--access', multiple=True, required=False,
              help="allow additional users access to this container manifest")
@click.option('--encrypt-manifest/--no-encrypt-manifest', default=True, required=False,
              help="default: encrypt. if --no-encrypt, this manifest will not be encrypted "
                   "and --access cannot be used." )
@click.argument('name', metavar='CONTAINER', required=False)
@click.pass_obj
def create(obj: ContextObj, owner, path, name, update_user, default_storage_set, access,
           title=None, category=None, storage_set=None, local_dir=None, encrypt_manifest=True):
    '''
    Create a new container manifest.
    '''

    obj.client.recognize_users()
    owner = obj.client.load_user_by_name(owner or '@default-owner')

    if default_storage_set and not storage_set:
        set_name = obj.client.config.get('default-storage-set-for-user')\
            .get(owner.owner, None)
    else:
        set_name = storage_set

    if local_dir and not set_name:
        raise CliError('--local-dir requires --storage-set or default storage set.')

    if category and not title:
        if not name:
            raise CliError('--category option requires --title or container name')
        title = name

    if not category and not title and not path:
        raise CliError('--path is required if --category and --title are not set')

    if set_name:
        try:
            storage_set = TemplateManager(obj.client.template_dir).get_storage_set(set_name)
        except FileNotFoundError as fnf:
            raise CliError(f'Storage set {set_name} not found.') from fnf

    if access and not encrypt_manifest:
        raise CliError('--no-encrypt and --access are mutually exclusive.')

    if access:
        try:
            access = [{'user': obj.client.load_user_by_name(user).owner} for user in access]
        except WildlandError as ex:
            raise CliError(f'Cannot create container: {ex}') from ex
    elif not encrypt_manifest:
        access = [{'user': '*'}]

    container = Container(
        owner=owner.owner,
        paths=[PurePosixPath(p) for p in path],
        backends=[],
        title=title,
        categories=category,
        access=access
    )

    path = obj.client.save_new_container(container, name)
    click.echo(f'Created: {path}')

    if storage_set:
        try:
            do_create_storage_from_set(obj.client, container, storage_set, local_dir)
        except FileNotFoundError as fnf:
            click.echo(f'Removing container: {path}')
            path.unlink()
            raise CliError('Failed to create storage from set: storage set not found') from fnf
        except ValueError as e:
            click.echo(f'Removing container: {path}')
            path.unlink()
            raise CliError(f'Failed to create storage from set: {e}') from e

    if update_user:
        if not owner.local_path:
            raise CliError('Cannot update user because the manifest path is unknown')
        click.echo('Attaching container to user')

        owner.containers.append(str(obj.client.local_url(path)))
        obj.client.save_user(owner)


@container_.command(short_help='update container')
@click.option('--storage', multiple=True,
    help='storage to use (can be repeated)')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def update(obj: ContextObj, storage, cont):
    '''
    Update a container manifest.
    '''

    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)
    if container.local_path is None:
        raise ClickException('Can only update a local manifest')

    if not storage:
        print('No change')
        return

    for storage_name in storage:
        storage = obj.client.load_storage_from(storage_name)
        assert storage.local_path
        print(f'Adding storage: {storage.local_path}')
        if str(storage.local_path) in container.backends:
            raise click.ClickException('Storage already attached to container')
        container.backends.append(obj.client.local_url(storage.local_path))

    obj.client.save_container(container)


@container_.command(short_help='publish container manifest')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def publish(obj: ContextObj, cont):
    '''
    Publish a container manifest under a given wildland path
    (or to an infrastructure container, if wlpath not given).
    '''

    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)
    try:
        obj.client.publish_container(container)
    except WildlandError as exc:
        print(str(exc))
        sys.exit(1)


def _container_info(client, container):
    click.echo(container.local_path)
    try:
        user = client.load_user_by_name(container.owner)
        if user.paths:
            user_desc = ' (' + ', '.join([str(p) for p in user.paths]) + ')'
        else:
            user_desc = ''
    except ManifestError:
        user_desc = ''
    click.echo(f'  owner: {container.owner}' + user_desc)
    for container_path in container.expanded_paths:
        click.echo(f'  path: {container_path}')
    for storage_path in container.backends:
        click.echo(f'  storage: {storage_path}')
    click.echo()


@container_.command('list', short_help='list containers', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known containers.
    '''

    obj.client.recognize_users()
    for container in obj.client.load_containers():
        _container_info(obj.client, container)


@container_.command(short_help='show container summary')
@click.argument('name', metavar='CONTAINER')
@click.pass_obj
def info(obj: ContextObj, name):
    '''
    Show information about single container.
    '''

    obj.client.recognize_users()
    try:
        container = obj.client.load_container_from(name)
    except ManifestError as ex:
        raise CliError(f'Failed to load manifest: {ex}') from ex

    _container_info(obj.client, container)


@container_.command('delete', short_help='delete a container', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even when using local storage manifests; ignore errors on parse')
@click.option('--cascade', is_flag=True,
              help='also delete local storage manifests')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade):
    '''
    Delete a container.
    '''
    # TODO: also consider detecting user-container link (i.e. user's main
    # container).
    obj.client.recognize_users()

    try:
        container = obj.client.load_container_from(name)
    except ManifestError as ex:
        if force:
            click.echo(f'Failed to load manifest: {ex}')
            try:
                path = obj.client.find_local_manifest(obj.client.container_dir, 'container', name)
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
        raise CliError('Can only delete a local manifest')

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
    for url_or_dict in list(container.backends):
        if isinstance(url_or_dict, str):
            path = obj.client.parse_file_url(url_or_dict, container.owner)
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

    click.echo(f'Deleting: {container.local_path}')
    container.local_path.unlink()


container_.add_command(sign)
container_.add_command(verify)
container_.add_command(edit)
container_.add_command(dump)


@container_.group(short_help='modify container manifest')
def modify():
    '''
    Commands for modifying container manifests.
    '''


@modify.command(short_help='add path to the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to add')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_path(ctx, input_file, path):
    '''
    Add path to the manifest.
    '''
    modify_manifest(ctx, input_file, add_field, 'paths', path)


@modify.command(short_help='remove path from the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_path(ctx, input_file, path):
    '''
    Remove path from the manifest.
    '''
    modify_manifest(ctx, input_file, del_field, 'paths', path)


@modify.command(short_help='set title in the manifest')
@click.argument('input_file', metavar='FILE')
@click.option('--title', metavar='TEXT', required=True, help='Title to set')
@click.pass_context
def set_title(ctx, input_file, title):
    '''
    Set title in the manifest.
    '''
    modify_manifest(ctx, input_file, set_field, 'title', title)


@modify.command(short_help='add category to the manifest')
@click.option('--category', metavar='PATH', required=True, multiple=True,
              help='Category to add')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_category(ctx, input_file, category):
    '''
    Add category to the manifest.
    '''
    modify_manifest(ctx, input_file, add_field, 'categories', category)


@modify.command(short_help='remove category from the manifest')
@click.option('--category', metavar='PATH', required=True, multiple=True,
              help='Category to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_category(ctx, input_file, category):
    '''
    Remove category from the manifest.
    '''
    modify_manifest(ctx, input_file, del_field, 'categories', category)


@modify.command(short_help='allow additional user(s) access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users to add access for')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_access(ctx, input_file, access):
    """
    Allow an additional user access to this manifest.
    """
    ctx.obj.client.recognize_users()

    processed_access = []

    try:
        for user in access:
            user = ctx.obj.client.load_user_by_name(user)
            processed_access.append({'user': user.owner})
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    modify_manifest(ctx, input_file, add_field, 'access', processed_access)


@modify.command(short_help='stop additional user(s) from having access to this encrypted manifest')
@click.option('--access', metavar='PATH', required=True, multiple=True,
              help='Users whose access should be revoked')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_access(ctx, input_file, access):
    '''
    Remove category from the manifest.
    '''
    ctx.obj.client.recognize_users()

    processed_access = []

    try:
        for user in access:
            user = ctx.obj.client.load_user_by_name(user)
            processed_access.append({'user': user.owner})
    except WildlandError as ex:
        raise CliError(f'Cannot modify access: {ex}') from ex

    modify_manifest(ctx, input_file, del_field, 'access', processed_access)


@modify.command(short_help='do not encrypt this manifest at all')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def set_no_encrypt_manifest(ctx, input_file):
    '''
    Set title in the manifest.
    '''
    modify_manifest(ctx, input_file, set_field, 'access', [{'user': '*'}])


@modify.command(short_help='encrypt this manifest so that it is accessible only to its owner')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def set_encrypt_manifest(ctx, input_file):
    '''
    Set title in the manifest.
    '''
    modify_manifest(ctx, input_file, set_field, 'access', [])


@modify.command(short_help='remove storage backend from the manifest')
@click.option('--storage', metavar='TEXT', required=True, multiple=True,
              help='Storage to remove. Can be either the backend_id of a storage or position in '
                   'storage list (starting from 0)')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_storage(ctx, input_file, storage):
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

    modify_manifest(ctx, input_file, del_nested_field, ['backends', 'storage'], keys=idxs_to_delete)


def prepare_mount(obj: ContextObj,
                  container: Container,
                  container_name: str,
                  user_paths: Iterable[PurePosixPath],
                  remount: bool,
                  with_subcontainers: bool,
                  subcontainer_of: Optional[Container],
                  quiet: bool,
                  only_subcontainers: bool):
    """
    Prepare 'params' argument for WildlandFSClient.mount_multiple_containers() to mount selected
        container and its subcontainers (depending on options).

    :param obj: command context from click
    :param container: container object to mount
    :param container_name: container name - used for diagnostic messages (unless quiet=True)
    :param user_paths: paths of the container owner - ['/'] for default user
    :param remount: should remount?
    :param with_subcontainers: should include subcontainers?
    :param subcontainer_of: it is a subcontainer
    :param quiet: don't print messages
    :param only_subcontainers: only mount subcontainers
    :return: combined 'params' argument
    """
    if with_subcontainers:
        subcontainers = list(obj.client.all_subcontainers(container))
    else:
        subcontainers = []

    storages = obj.client.get_storages_to_mount(container)

    if not subcontainers or not only_subcontainers:
        if obj.fs_client.find_primary_storage_id(container) is None:
            if not quiet:
                print(f'new: {container_name}')
            yield (container, storages, user_paths, subcontainer_of)
        elif remount:
            storages_to_remount = []

            for path in obj.fs_client.get_orphaned_container_storage_paths(container, storages):
                storage_id = obj.fs_client.find_storage_id_by_path(path)
                print(f'Removing orphaned storage {path} (id: {storage_id} )')
                obj.fs_client.unmount_storage(storage_id)

            for storage in storages:
                if obj.fs_client.should_remount(container, storage, user_paths):
                    storages_to_remount.append(storage)

                    if not quiet:
                        print(f'changed: {storage.backend_id}')
                else:
                    if not quiet:
                        print(f'not changed: {storage.backend_id})')

            yield (container, storages_to_remount, user_paths, subcontainer_of)
        else:
            raise CliError(f'Already mounted: {container.local_path}')

    if with_subcontainers:
        for subcontainer in subcontainers:
            yield from prepare_mount(obj, subcontainer, f'{container_name}:{subcontainer.paths[0]}',
                                     user_paths, remount, with_subcontainers, container, quiet,
                                     only_subcontainers)


@container_.command(short_help='mount container')
@click.option('--remount/--no-remount', '-r/-n', default=True,
              help='Remount existing container, if found')
@click.option('--save', '-s', is_flag=True,
              help='Save the container to be mounted at startup')
@click.option('--import-users/--no-import-users', is_flag=True, default=True,
              help='Import encountered users on the WildLand path to the container(s)')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=True,
              help='Do not mount subcontainers of this container.')
@click.option('--only-subcontainers', '-b', is_flag=True, default=False,
              help='If a container has subcontainers, mount only the subcontainers')
@click.option('--quiet', '-q', is_flag=True,
              help='Do not list what is mounted')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount(obj: ContextObj, container_names, remount, save, import_users: bool,
          with_subcontainers: bool, only_subcontainers: bool, quiet):
    '''
    Mount a container given by name or path to manifest. Repeat the argument to
    mount multiple containers.

    The Wildland system has to be mounted first, see ``wl start``.
    '''
    try:
        obj.fs_client.ensure_mounted()
        obj.client.recognize_users()
    except WildlandError as ex:
        raise ClickException(ex) from ex

    if import_users:
        obj.client.auto_import_users = True

    params: List[Tuple[Container, List[Storage], List[PurePosixPath], Container]] = []

    failed = False
    exc_msg = 'Failed to load some container manifests:\n'

    for container_name in container_names:
        found = False
        try:
            # wildland paths are special, because may require importing intermediate users
            if WildlandPath.match(container_name):
                containers = obj.client.load_container_from_wlpath(
                    WildlandPath.from_str(container_name),
                )
            else:
                containers = obj.client.load_containers_from(container_name)
        except WildlandError as ex:
            failed = True
            exc_msg += str(ex) + '\n'
            continue

        try:
            for container in containers:
                try:
                    user_paths = obj.client.get_bridge_paths_for_user(container.owner)
                    params.extend(prepare_mount(
                        obj, container, str(container), user_paths,
                        remount, with_subcontainers, None, quiet, only_subcontainers))
                    found = True
                except WildlandError as ex:
                    failed = True
                    exc_msg += str(ex) + '\n'
        except WildlandError as ex:
            failed = True
            exc_msg += str(ex) + '\n'
        if not found:
            failed = True
            exc_msg += 'No container found for \'{}\'\n'.format(container_name)

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

    if failed:
        raise ClickException(exc_msg)


@container_.command(short_help='unmount container', alias=['umount'])
@click.option('--path', metavar='PATH',
              help='mount path to search for')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=True,
              help='Do not umount subcontainers.')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=False)
@click.pass_obj
def unmount(obj: ContextObj, path: str, with_subcontainers: bool, container_names):
    '''
    Unmount a container_ You can either specify the container manifest, or
    identify the container by one of its path (using ``--path``).
    '''

    try:
        obj.fs_client.ensure_mounted()
        obj.client.recognize_users()
    except WildlandError as ex:
        raise ClickException(ex) from ex

    if bool(container_names) + bool(path) != 1:
        raise click.UsageError('Specify either container or --path')

    failed = False
    exc_msg = 'Failed to load some container manifests:\n'

    # pylint: disable=too-many-nested-blocks
    if container_names:
        storage_ids = []
        for container_name in container_names:
            try:
                for container in obj.client.load_containers_from(container_name):
                    for mount_path in obj.fs_client.get_unique_storage_paths(container):
                        storage_id = obj.fs_client.find_storage_id_by_path(mount_path)

                        if storage_id is None:
                            click.echo(f'Not mounted: {mount_path}')
                        else:
                            click.echo(f'Will unmount: {mount_path}')
                            storage_ids.append(storage_id)

                    if with_subcontainers:
                        storage_ids.extend(
                            obj.fs_client.find_all_subcontainers_storage_ids(container))
            except WildlandError as ex:
                failed = True
                exc_msg += str(ex) + '\n'
    else:
        storage_id = obj.fs_client.find_storage_id_by_path(PurePosixPath(path))
        if storage_id is None:
            raise ClickException('Container not mounted')
        storage_ids = [storage_id]
        if with_subcontainers:
            storage_ids.extend(
                obj.fs_client.find_all_subcontainers_storage_ids(
                    obj.fs_client.get_container_from_storage_id(storage_id)))

    if not storage_ids:
        raise ClickException('No containers mounted')

    click.echo(f'Unmounting {len(storage_ids)} containers')
    for storage_id in storage_ids:
        obj.fs_client.unmount_storage(storage_id)

    if failed:
        raise ClickException(exc_msg)


class Remounter:
    '''
    A class for watching files and remounting if necessary.
    '''

    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 container_names: List[str], additional_patterns: Optional[List[str]] = None):
        self.client = client
        self.fs_client = fs_client

        self.patterns: List[str] = []
        if additional_patterns:
            self.patterns.extend(additional_patterns)
        for name in container_names:
            path = Path(os.path.expanduser(name)).resolve()
            relpath = path.relative_to(self.fs_client.mount_dir)
            self.patterns.append(str(PurePosixPath('/') / relpath))

        # Queued operations
        self.to_mount: List[Tuple[Container,
                                  Storage,
                                  Iterable[PurePosixPath],
                                  Optional[Container]]] = []
        self.to_unmount: List[int] = []

        # manifest path -> main container path
        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

    def run(self):
        '''
        Run the main loop.
        '''

        logger.info('Using patterns: %r', self.patterns)
        for events in self.fs_client.watch(self.patterns, with_initial=True):
            for event in events:
                try:
                    self.handle_event(event)
                except Exception:
                    logger.exception('error in handle_event')

            self.unmount_pending()
            self.mount_pending()

    def handle_event(self, event: WatchEvent):
        '''
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        '''

        logger.info('Event %s: %s', event.event_type, event.path)

        # Find out if we've already seen the file, and can match it to a
        # mounted storage.
        storage_id: Optional[int] = None
        if event.path in self.main_paths:
            storage_id = self.fs_client.find_storage_id_by_path(
                self.main_paths[event.path])

        # Handle delete: unmount if the file was mounted.
        if event.event_type == 'delete':
            # Stop tracking the file
            if event.path in self.main_paths:
                del self.main_paths[event.path]

            if storage_id is not None:
                logger.info('  (unmount %d)', storage_id)
                self.to_unmount.append(storage_id)
            else:
                logger.info('  (not mounted)')

        # Handle create/modify:
        if event.event_type in ['create', 'modify']:
            local_path = self.fs_client.mount_dir / event.path.relative_to('/')
            container = self.client.load_container_from_path(local_path)

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_path(
                container.owner, container.paths[0])


            user_paths = self.client.get_bridge_paths_for_user(container.owner)
            storages = self.client.get_storages_to_mount(container)

            if self.fs_client.find_primary_storage_id(container) is None:
                logger.info('  new: %s', str(container))
                self.to_mount.append((container, storages, user_paths, None))
            else:
                storages_to_remount = []

                for path in self.fs_client.get_orphaned_container_storage_paths(
                        container, storages):
                    storage_id = self.fs_client.find_storage_id_by_path(path)
                    logger.info('  (removing orphan %s @ id: %d)', path, storage_id)
                    self.fs_client.unmount_storage(storage_id)

                for storage in storages:
                    if self.fs_client.should_remount(container, storage, user_paths):
                        logger.info('  (remounting: %s)', storage.backend_id)
                        storages_to_remount.append(storage)
                    else:
                        logger.info('  (not changed: %s)', storage.backend_id)

                self.to_mount.append((container, storages_to_remount, user_paths, None))

    def unmount_pending(self):
        '''
        Unmount queued containers.
        '''

        for storage_id in self.to_unmount:
            self.fs_client.unmount_storage(storage_id)
        self.to_unmount.clear()

    def mount_pending(self):
        '''
        Mount queued containers.
        '''

        self.fs_client.mount_multiple_containers(self.to_mount, remount=True)
        self.to_mount.clear()


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
        raise ClickException(error_message)


@container_.command('mount-watch', short_help='mount container')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount_watch(obj: ContextObj, container_names):
    '''
    Watch for manifest files inside Wildland, and keep the filesystem mount
    state in sync.
    '''

    obj.fs_client.ensure_mounted()
    obj.client.recognize_users()
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
    container_id = container.ensure_uuid()
    return Path(BaseDirectory.get_runtime_dir()) / f'wildland-sync-{container_id}.pid'


@container_.command('sync', short_help='start syncing a container')
@click.argument('cont', metavar='CONTAINER')
@click.option('--target-remote', help='specify which remote storage should be kept in sync'
                                      'with the local storage. Default: first listed in manifest. '
                                      'Can be specified as backend_id or as storage type (e.g. s3')
@click.pass_obj
def sync_container(obj: ContextObj, target_remote, cont):
    """
    Keep the given container in sync across the local storage and selected remote storage
    (by default the first listed in manifest).
    """

    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)

    sync_pidfile = syncer_pidfile_for_container(container)

    if os.path.exists(sync_pidfile):
        raise ClickException("Sync process for this container is already running; use "
                             "stop-sync to stop it.")

    storages = [StorageBackend.from_params(storage.params) for storage in
                obj.client.all_storages(container)]

    try:
        target_storages = [[storage for storage in storages
                            if obj.client.is_local_storage(storage)][0]]
    except IndexError:
        raise CliError('No local storage backend found')  # pylint: disable=raise-missing-from

    default_remotes = obj.client.config.get('default-remote-for-container')

    if target_remote:
        try:
            target_remote = [storage for storage in storages
                             if target_remote in (storage.backend_id, storage.TYPE)][0]
        except IndexError:
            # pylint: disable=raise-missing-from
            raise CliError('No remote storage backend found: check if specified'
                           ' --target-remote exists.')
        default_remotes[container.ensure_uuid()] = target_remote.backend_id
        obj.client.config.update_and_save({'default-remote-for-container': default_remotes})

    else:
        target_remote_id = default_remotes.get(container.ensure_uuid(), None)
        try:
            target_remote = [
                storage for storage in storages
                if target_remote_id == storage.backend_id
                   or (not target_remote_id and not obj.client.is_local_storage(storage))][0]
        except IndexError:
            # pylint: disable=raise-missing-from
            raise CliError('No remote storage backend found: specify --target-remote.')

    click.echo(f'Using remote backend {target_remote.backend_id} of type {target_remote.TYPE}')
    target_storages.append(target_remote)

    # Store information about container/backend mappings
    hash_db = HashDb(obj.client.config.base_dir)
    hash_db.update_storages_for_containers(container.ensure_uuid(), target_storages)

    with daemon.DaemonContext(pidfile=pidfile.TimeoutPIDLockFile(sync_pidfile),
                              stdout=sys.stdout, stderr=sys.stderr, detach_process=True):
        init_logging(False, f'/tmp/wl-sync-{container.ensure_uuid()}.log')

        container_path = PurePosixPath(container.local_path)
        container_name = container_path.name.replace(''.join(container_path.suffixes), '')

        syncer = Syncer(target_storages, container_name=container_name,
                        config_dir=obj.client.config.base_dir)
        try:
            syncer.start_syncing()
        except FileNotFoundError:
            print("Storage root not found!")
            return
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            syncer.stop_syncing()


@container_.command('stop-sync', short_help='stop syncing a container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def stop_syncing_container(obj: ContextObj, cont):
    '''
    Keep the given container in sync across storages.
    '''

    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)

    sync_pidfile = syncer_pidfile_for_container(container)

    terminate_daemon(sync_pidfile, "Sync container for this container is not running.")


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
    obj.client.recognize_users()
    container = obj.client.load_container_from(cont)

    if not force_scan:
        hash_db = HashDb(obj.client.config.base_dir)
        conflicts = hash_db.get_conflicts(container.ensure_uuid())
        if conflicts is None:
            print("No backends have been synced for this container; "
                  "list-conflicts will not work without a preceding container sync")
            return
    else:
        storages = [StorageBackend.from_params(storage.params) for storage in
                    obj.client.all_storages(container)]
        conflicts = list_storage_conflicts(storages)

    if conflicts:
        print("Conflicts detected on:")
        for (path, c1, c2) in conflicts:
            # TODO: check if file still exists?
            print(f"Conflict detected in file {path} in containers {c1} and {c2}")
    else:
        print("No conflicts were detected by container sync.")


@container_.command(short_help='duplicate a container')
@click.option('--new-name', help='name of the new container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def duplicate(obj: ContextObj, new_name, cont):
    '''
    Duplicate an existing container manifest.
    '''

    obj.client.recognize_users()

    container = obj.client.load_container_from(cont)
    old_uuid = container.ensure_uuid()

    new_container = Container(
        owner=container.owner,
        paths=container.paths[1:],
        backends=container.backends,
        title=container.title,
        categories=container.categories,
        access=container.access,
    )
    new_uuid = new_container.ensure_uuid()

    replace_backends = []
    for backend in new_container.backends:
        if isinstance(backend, dict):
            backend['backend-id'] = str(uuid.uuid4())
        else:
            storage = obj.client.load_storage_from_url(backend, container.owner)
            storage.params['backend-id'] = str(uuid.uuid4())
            new_storage = Storage(
                container_path=PurePosixPath(str(storage.container_path).replace(
                    old_uuid, new_uuid)),
                storage_type=storage.storage_type,
                owner=storage.owner,
                params=storage.params,
                trusted=storage.trusted)
            new_path = obj.client.save_new_storage(new_storage, new_name)
            click.echo(f'Created storage: {new_path}')
            replace_backends.append((backend, obj.client.local_url(new_path)))

    for old, new in replace_backends:
        new_container.backends.remove(old)
        new_container.backends.append(new)

    path = obj.client.save_new_container(new_container, new_name)
    click.echo(f'Created: {path}')
