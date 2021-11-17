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
from itertools import combinations
from pathlib import PurePosixPath, Path
from typing import Iterable, List, Optional, Sequence, Tuple
import os
import sys
import re
import signal
import click
import daemon
import progressbar

from progressbar.widgets import FormatWidgetMixin, TimeSensitiveWidgetBase
from click import ClickException
from daemon import pidfile
from xdg import BaseDirectory

import wildland.cli.cli_common as cli_common

from wildland.client import Client
from wildland.control_client import ControlClientUnableToConnectError
from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import aliased_group, ContextObj
from .cli_exc import CliError
from .cli_storage import do_create_storage_from_templates
from ..container import Container
from ..exc import WildlandError
from ..manifest.manifest import ManifestError
from ..manifest.template import TemplateManager
from ..publish import Publisher
from ..utils import yaml_parser
from ..remounter import Remounter
from ..storage import Storage, StorageBackend
from ..log import init_logging, get_logger
from ..storage_sync.base import BaseSyncer, SyncConflict
from ..tests.profiling.profilers import profile

try:
    RUNTIME_DIR = Path(BaseDirectory.get_runtime_dir())
except KeyError:
    RUNTIME_DIR = Path.home() / 'run'
    RUNTIME_DIR.mkdir(exist_ok=True)

MW_PIDFILE = RUNTIME_DIR / 'wildland-mount-watch.pid'
MW_DATA_FILE = RUNTIME_DIR / 'wildland-mount-watch.data'

logger = get_logger('cli-container')


# We define our own Counter widget to solve refresh count on generator
class Counter(FormatWidgetMixin, TimeSensitiveWidgetBase):
    """Displays the current count"""

    # pylint: disable=redefined-builtin
    def __init__(self, format='%(value)d', **kwargs):
        FormatWidgetMixin.__init__(self, format=format, **kwargs)
        TimeSensitiveWidgetBase.__init__(self, format=format, **kwargs)

    # pylint: disable=redefined-builtin
    def __call__(self, progress, data, format=None):
        return FormatWidgetMixin.__call__(self, progress, data, format)


def get_counter(msg):
    """Create standardized counter for Wildland"""
    widgets = [
        msg, ": ",
        Counter()
    ]
    counter = progressbar.ProgressBar(widgets=widgets)
    return counter


@aliased_group('container', short_help='container management')
def container_():
    """
    Manage containers.
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
        self.prompt = None  # type: ignore
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
              help='if --no-encrypt, this manifest will not be encrypted and '
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
        click.echo(f'Attaching container to user [{owner_user.owner}]')

        owner_user.add_catalog_entry(str(obj.client.local_url(container_path)))
        obj.client.save_object(WildlandObject.Type.USER, owner_user)

    if not no_publish:
        try:
            owner_user = obj.client.load_object_from_name(WildlandObject.Type.USER, container.owner)
            if owner_user.has_catalog:
                click.echo(f'Publishing container: [{container.get_primary_publish_path()}]')
                publisher = Publisher(obj.client, owner_user)
                publisher.publish(container)
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


def _container_info(client, container, users_and_bridge_paths):
    container_fields = container.to_repr_fields(include_sensitive=False)
    bridge_paths = []
    try:
        if container_fields['owner'] in users_and_bridge_paths:
            bridge_paths = [str(p) for p in users_and_bridge_paths[container_fields['owner']]]
    except ManifestError:
        pass
    if bridge_paths:
        container_fields['bridge-paths-to-owner'] = bridge_paths

    cache = client.cache_storage(container)
    if cache:
        storage_type = cache.params['type']
        result = {
            "type": storage_type,
            "backend_id": cache.params["backend-id"],
        }
        storage_cls = StorageBackend.types()[storage_type]
        if storage_cls.LOCATION_PARAM and storage_cls.LOCATION_PARAM in cache.params and \
                cache.params[storage_cls.LOCATION_PARAM]:
            result.update({"location": cache.params[storage_cls.LOCATION_PARAM]})
        container_fields["cache"] = result

    click.secho("Sensitive fields are hidden.", fg="yellow")
    click.echo(container.local_path)
    data = yaml_parser.dump(container_fields, encoding='utf-8', sort_keys=False)
    click.echo(data.decode())


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
        _container_info(obj.client, container, users_and_bridge_paths)


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

    _container_info(obj.client, container, users_and_bridge_paths)


@container_.command('delete', short_help='delete a container', alias=['rm', 'remove'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even when using local storage manifests; ignore errors on parse')
@click.option('--cascade', is_flag=True,
              help='also delete local storage manifests')
@click.option('--no-unpublish', '-n', is_flag=True,
              help='do not attempt to unpublish the container before deleting it')
@click.argument('names', metavar='NAME', nargs=-1)
def delete(obj: ContextObj, names, force: bool, cascade: bool, no_unpublish: bool):
    """
    Delete a container.
    """

    error_messages = ''
    for name in names:
        try:
            _delete(obj, name, force, cascade, no_unpublish)
        except Exception as e:
            error_messages += f'{e}\n'

    if error_messages:
        raise CliError(f'Some containers could not be deleted:\n{error_messages.strip()}')


def _delete(obj: ContextObj, name: str, force: bool, cascade: bool, no_unpublish: bool):
    # TODO: also consider detecting user-container link (i.e. user's main container).

    try:
        container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, name)
    except ManifestError as ex:
        if force:
            logger.warning('Failed to load manifest: %s', ex)
            try:
                path = obj.client.find_local_manifest(WildlandObject.Type.CONTAINER, name)
                if path:
                    click.echo(f'Deleting file {path}')
                    path.unlink()
            except ManifestError:
                # already removed
                pass
            if cascade:
                logger.warning('Unable to cascade remove: manifest failed to load.')
            return
        logger.warning('Failed to load manifest, cannot delete: %s', ex)
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
    except ControlClientUnableToConnectError:
        pass

    _delete_cache(obj.client, container)

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
            click.echo(f'Unpublishing container: [{container.get_primary_publish_path()}]')
            user = obj.client.load_object_from_name(WildlandObject.Type.USER, container.owner)
            Publisher(obj.client, user).unpublish(container)
        except WildlandError:
            # not published
            pass

    click.echo(f'Deleting: {container.local_path}')
    container.local_path.unlink()


container_.add_command(cli_common.sign)
container_.add_command(cli_common.verify)
container_.add_command(cli_common.publish)
container_.add_command(cli_common.unpublish)

@container_.command(short_help='modify container manifest')
@click.option('--add-path', metavar='PATH', multiple=True, help='path to add')
@click.option('--del-path', metavar='PATH', multiple=True, help='path to remove')
@click.option('--add-category', metavar='PATH', multiple=True, help='category to add')
@click.option('--del-category', metavar='PATH', multiple=True, help='category to remove')
@click.option('--title', metavar='TEXT', help='title to set')
@click.option('--add-access', metavar='PATH', multiple=True, help='users to add access for')
@click.option('--del-access', metavar='PATH', multiple=True, help='users to remove access for')
@click.option('--encrypt-manifest', is_flag=True,
              help='encrypt this manifest so that it is accessible only to its owner')
@click.option('--no-encrypt-manifest', is_flag=True, help='or do not encrypt this manifest at all')
@click.option('--del-storage', metavar='TEXT', multiple=True,
              help='Storage to remove. Can be either the backend_id of a storage or position in '
                   'storage list (starting from 0)')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish modified container')
@click.option('--remount/--no-remount', '-r/-n', default=True, help='remount mounted container')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def modify(ctx: click.Context,
           add_path, del_path, add_category, del_category, title, add_access, del_access,
           encrypt_manifest, no_encrypt_manifest, del_storage,
           publish, remount, input_file
           ):
    """
    Command for modifying container manifests.

    If container is already published, any modification should be republish
    unless publish is False.
    """
    _option_check(ctx, add_path, del_path, add_category, del_category, title, add_access,
                  del_access, encrypt_manifest, no_encrypt_manifest, del_storage)

    add_access_owners = [
        {'user': ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
        for user in add_access]
    to_add = {'paths': add_path, 'categories': add_category, 'access': add_access_owners}

    del_access_owners = [
        {'user': ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
        for user in del_access]
    to_del = {'paths': del_path, 'categories': del_category, 'access': del_access_owners}

    to_del_nested = _get_storages_idx_to_del(ctx, del_storage, input_file)

    to_set = {}
    if title:
        to_set['title'] = title
    if encrypt_manifest:
        to_set['access'] = []
    if no_encrypt_manifest:
        to_set['access'] = [{'user': '*'}]

    container, modified = cli_common.resolve_object(
        ctx, input_file, WildlandObject.Type.CONTAINER, cli_common.modify_manifest,
        remount=remount,
        edit_funcs=[
            cli_common.add_fields,
            cli_common.del_fields,
            cli_common.set_fields,
            cli_common.del_nested_fields
        ],
        to_add=to_add,
        to_del=to_del,
        to_set=to_set,
        to_del_nested=to_del_nested,
        logger=logger
    )

    if publish and modified:
        cli_common.republish_object(ctx.obj.client, container)


def _option_check(ctx, add_path, del_path, add_category, del_category, title, add_access,
                  del_access, encrypt_manifest, no_encrypt_manifest, del_storage):
    cli_common.check_if_any_options(ctx, add_path, del_path, add_category, del_category, title,
                                    add_access, del_access, encrypt_manifest, no_encrypt_manifest,
                                    del_storage)
    cli_common.check_options_conflict("path", add_path, del_path)
    cli_common.check_options_conflict("category", add_category, del_category)
    cli_common.check_options_conflict("access", add_access, del_access)

    if (encrypt_manifest or no_encrypt_manifest) and (add_access or del_access):
        raise CliError(
            'using --encrypt-manifest or --no-encrypt-manifest'
            'AND --add-access or --del-access is ambiguous.')
    if encrypt_manifest and no_encrypt_manifest:
        raise CliError('options conflict:'
                       '\n  --encrypt-manifest and --no-encrypt-manifest')


def _get_storages_idx_to_del(ctx, del_storage, input_file):
    to_del_nested = {}
    if del_storage:
        idxs_to_delete = []
        container_manifest = cli_common.find_manifest_file(
            ctx.obj.client, input_file, 'container').read_bytes()
        container_yaml = list(yaml_parser.safe_load_all(container_manifest))[1]
        storages_obj = container_yaml.get('backends', {}).get('storage', {})
        for s in del_storage:
            if s.isnumeric():
                idxs_to_delete.append(int(s))
            else:
                for idx, obj_storage in enumerate(storages_obj):
                    if obj_storage['backend-id'] == s:
                        idxs_to_delete.append(idx)
        click.echo('Storage indexes to remove: ' + str(idxs_to_delete))
        to_del_nested[('backends', 'storage')] = idxs_to_delete

    return to_del_nested


def wl_path_for_container(client: Client, container: Container,
                          user_paths: Optional[Iterable[Iterable[PurePosixPath]]] = None) -> str:
    """
    Return user-friendly WL path for the container.
    """
    ret = client.bridge_separator

    if user_paths:
        # take some set of bridges to the user
        for path in list(user_paths)[0]:
            ret += str(path) + client.bridge_separator

    # add non-default owner if needed
    if ret == client.bridge_separator and container.owner != client.config.get('@default-owner'):
        ret = container.owner + client.bridge_separator

    # UUID path is always first, we want a more friendly one if possible
    # reverse sort puts paths like '/.uuid/' or '/.backends/' last
    paths = container.paths
    paths.sort(reverse=True)
    ret += str(paths[0]) + client.bridge_separator

    return ret


def _cache_sync(client: Client, container: Container, storages: List[Storage], verbose: bool,
                user_paths: Iterable[Iterable[PurePosixPath]]):
    """
    Start sync between cache storage and old primary storage.
    """
    primary: Storage = storages[0]  # get_storages_to_mount() ensures this
    if 'cache' in primary.params:
        if verbose:
            click.echo(f'Using cache at: {primary.params["location"]}')
        src = storages[1]  # [1] is the non-cache (old primary)
        cname = wl_path_for_container(client, container, user_paths)
        state = client.get_sync_job_state(container.sync_id)
        if not state:  # sync not running for this container
            # start bidirectional sync (this also performs an initial one-shot sync)
            # this happens in the background, user can see sync status/progress using `wl sync`
            client.do_sync(cname, container.sync_id, src.params, primary.params,
                           one_shot=False, unidir=False)


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
            _cache_sync(obj.client, container, storages, verbose, user_paths)
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

            _cache_sync(obj.client, container, storages, verbose, user_paths)
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


def _create_cache(client: Client, container: Container, template_name: str,
                  verbose: bool = False) -> Storage:
    """
    Create cache storage for a container from template.
    """
    template_manager = TemplateManager(client.dirs[WildlandObject.Type.TEMPLATE])
    try:
        template = template_manager.get_storage_template(template_name)
    except FileNotFoundError as fnf:
        raise WildlandError(f'Storage template {template_name} not found') from fnf

    storage_fields = template.get_storage_fields(container)
    storage_fields = container.fill_storage_fields(storage_fields)
    storage_fields['owner'] = client.config.get('@default-owner')
    cache = WildlandObject.from_fields(storage_fields, client, WildlandObject.Type.STORAGE,
                                       local_owners=client.config.get('local-owners'))

    # these params are not in the Storage schema because they're cache-specific
    cache.params['cache'] = True
    cache.params['original-owner'] = container.owner

    backend = StorageBackend.from_params(cache.params)
    location = backend.location
    with backend:
        backend.mkdir(PurePosixPath(''))
    base_name = container.owner + '.' + container.uuid
    cache_path = client.new_path(WildlandObject.Type.STORAGE, base_name,
                                 skip_numeric_suffix=True, base_dir=client.cache_dir)
    client.save_new_object(WildlandObject.Type.STORAGE, cache, template_name, cache_path)
    if verbose:
        click.echo(f'Created cache: {cache_path} with location: {location}')
    return cache


def _delete_cache(client: Client, container: Container) -> bool:
    """
    Delete cache associated with the container. Returns True if cache was present.
    """
    cache = client.cache_storage(container)
    if cache:
        click.echo(f'Deleting cache: {cache.local_path}')
        cache.local_path.unlink()
        return True

    return False


@container_.command(short_help='create cache storage for container(s)')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.option('--template', '-t', metavar='TEMPLATE', required=True,
              help='Use the specified storage template to create a new cache storage '
                   '(becomes primary storage for the container while mounted)')
@click.pass_obj
def create_cache(obj: ContextObj, container_names, template):
    """
    Create cache storage for container(s).
    """
    for name in container_names:
        containers = obj.client.load_containers_from(name)
        for container in containers:
            _create_cache(obj.client, container, template, verbose=True)


@container_.command(short_help='delete cache storage for container(s)')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def delete_cache(obj: ContextObj, container_names):
    """
    Delete cache storage for container(s).
    """
    for name in container_names:
        containers = obj.client.load_containers_from(name)
        for container in containers:
            if not _delete_cache(obj.client, container):
                click.echo('Cache not set for the container')


@container_.command(short_help='mount container')
@click.option('--remount/--no-remount', '-r/-n', default=True,
              help='Remount existing container, if found')
@click.option('--save', '-s', is_flag=True,
              help='Save the container to be mounted at startup')
@click.option('--import-users/--no-import-users', is_flag=True, default=True,
              help='Import encountered users on the WildLand path to the container(s)')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=True,
              help='Mount subcontainers of this container.')
@click.option('--only-subcontainers', '-b', is_flag=True, default=False,
              help='If a container has subcontainers, mount only the subcontainers')
@click.option('--with-cache', '-c', is_flag=True, default=False,
              help='Use the default cache storage template to create and use a new cache storage '
                   '(becomes primary storage for the container while mounted, synced with '
                   'the old primary). '
                   'Cache template to use can be overriden using the --cache-template option.')
@click.option('--cache-template', metavar='TEMPLATE',
              help='Use specified storage template to create and use a new cache storage')
@click.option('--list-all', '-l', is_flag=True,
              help='During mount, list all containers, including those who '
                   'did not need to be changed')
@click.option('--manifests-catalog', '-m', is_flag=True, default=False,
              help='Allow mounting containers from manifest catalogs')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=True)
@click.pass_obj
def mount(obj: ContextObj, container_names: Tuple[str], remount: bool, save: bool,
          import_users: bool, with_subcontainers: bool, only_subcontainers: bool, list_all: bool,
          manifests_catalog: bool, with_cache: bool, cache_template: str) -> None:
    """
    Mount a container given by name or path to its manifest. Repeat the argument to mount
    multiple containers.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    if with_cache and not cache_template:
        cache_template = obj.client.config.get('default-cache-template')
        if not cache_template:
            raise WildlandError('Default cache template not set, set one with '
                                '`wl set-default-cache` or use --cache-template option')

    _mount(obj, container_names, remount, save, import_users, with_subcontainers,
           only_subcontainers, list_all, manifests_catalog, cache_template)


@profile()
@cli_common.wrap_output
def _mount(obj: ContextObj, container_names: Sequence[str],
           remount: bool = True, save: bool = True, import_users: bool = True,
           with_subcontainers: bool = True, only_subcontainers: bool = False,
           list_all: bool = True, manifests_catalog: bool = False,
           cache_template: str = None) -> None:

    obj.fs_client.ensure_mounted()
    client = obj.client

    if import_users:
        client.auto_import_users = True

    params: List[Tuple[Container, List[Storage], List[Iterable[PurePosixPath]], Container]] = []
    successfully_loaded_container_names: List[str] = []
    fails: List[str] = []

    for container_name in container_names:
        current_params: List[Tuple[Container, List[Storage],
                                   List[Iterable[PurePosixPath]], Container]] = []

        counter = get_counter(f"Loading containers (from '{container_name}')")
        containers = counter(client.load_containers_from(
            container_name, include_manifests_catalog=manifests_catalog))
        counter.start()
        counter = get_counter(f"Checking container references (from '{container_name}')")
        reordered, exc_msg = client.ensure_mount_reference_container(
            containers, callback_iter_func=counter)

        if exc_msg:
            fails.append(exc_msg)

        if not reordered:
            continue  # container_name doesn't exist

        for container in reordered:
            if cache_template:
                _create_cache(client, container, cache_template, list_all)
        client.load_local_storage_cache()

        counter = get_counter(f"Preparing mount of container references (from '{container_name}')")
        for container in counter(reordered):
            try:
                user_paths = client.get_bridge_paths_for_user(container.owner)
                mount_params = prepare_mount(
                    obj, container, str(container), user_paths,
                    remount, with_subcontainers, None, list_all, only_subcontainers)
                current_params.extend(mount_params)
            except WildlandError as ex:
                fails.append(f'Cannot mount container {container}: {str(ex)}')

        successfully_loaded_container_names.append(container_name)
        params.extend(current_params)

    if len(params) > 1:
        click.echo(f'Mounting storages for containers: {len(params)}')
        obj.fs_client.mount_multiple_containers(params, remount=remount)
    elif len(params) > 0:
        click.echo('Mounting one storage')
        obj.fs_client.mount_multiple_containers(params, remount=remount)
    else:
        click.echo('No containers need (re)mounting')

    if save:
        default_containers = client.config.get('default-containers')
        default_containers_set = set(default_containers)
        new_default_containers = default_containers.copy()
        failed_containers = set(container_names) - set(successfully_loaded_container_names)

        if failed_containers and successfully_loaded_container_names:
            click.echo(f'Saving {len(successfully_loaded_container_names)} out of '
                       f'{len(container_names)} listed containers. The following containers will '
                       f'not be saved: {str(failed_containers)}.')

        for container_name in successfully_loaded_container_names:
            if container_name in default_containers_set:
                click.echo(f'Already in default-containers: {container_name}')
                continue
            click.echo(f'Adding to default-containers: {container_name}')
            default_containers_set.add(container_name)
            new_default_containers.append(container_name)

        if len(new_default_containers) > len(default_containers):
            client.config.update_and_save({'default-containers': new_default_containers})

        if len(new_default_containers) > len(default_containers_set):
            click.echo(f'default-containers in your config file {client.config.path} has '
                       'duplicates. Consider removing them.')

    if fails:
        raise WildlandError('\n'.join(fails))


@container_.command(short_help='unmount container', alias=['umount'])
@click.option('--path', metavar='PATH',
              help='Mount path to search for.')
@click.option('--with-subcontainers/--without-subcontainers', '-w/-W', is_flag=True, default=True,
              help='Do not unmount subcontainers.')
@click.option('--undo-save', '-u', 'undo_save', is_flag=True, default=False,
              help='Undo mount --save option.')
@click.option('--all', 'unmount_all', is_flag=True, default=False,
              help='Unmount all mounted storages.')
@click.argument('container_names', metavar='CONTAINER', nargs=-1, required=False)
@click.pass_obj
def unmount(obj: ContextObj, path: str, with_subcontainers: bool, undo_save: bool,
            unmount_all: bool, container_names: Sequence[str]) -> None:
    """
    Unmount a container given by name, path to container's manifest or by one of its paths (using
    ``--path``). Repeat the argument to unmount multiple containers.
    """
    _unmount(obj, container_names=container_names, path=path, with_subcontainers=with_subcontainers,
             undo_save=undo_save, unmount_all=unmount_all)


@cli_common.wrap_output
def _unmount(obj: ContextObj, container_names: Sequence[str], path: str,
             with_subcontainers: bool = True, undo_save: bool = False,
             unmount_all: bool = False) -> None:

    obj.fs_client.ensure_mounted()

    if unmount_all and (undo_save or not with_subcontainers or len(container_names) > 0
                        or bool(path)):
        raise click.UsageError('--all cannot be used with other options')

    if bool(container_names) + bool(path) != 1 and not unmount_all:
        raise click.UsageError('Specify either container or --path')

    if undo_save and path:
        raise click.UsageError(
            'Specify either --undo-save or --path. Cannot unsave a container '
            'specified by --path. Only containers specified by name or path to manifest can be '
            'saved and unsaved')

    if unmount_all:
        ids = obj.fs_client.get_mounted_storage_ids()
        if len(ids) > 0:
            click.echo(f'Unmounting {len(ids)} storages')
            for ident in ids:
                obj.fs_client.unmount_storage(ident)
            click.echo('Stopping all sync jobs')
            obj.client.run_sync_command('stop-all')
        else:
            click.echo('No storages to unmount')
        return

    fails: List[str] = []
    all_storage_ids = []
    all_cache_ids = []
    storage_ids: List[int] = []
    if container_names:
        for container_name in container_names:
            counter = get_counter(f"Loading containers (from '{container_name}')")
            try:
                storage_ids, cache_ids = _collect_storage_ids_by_container_name(
                    obj, container_name, counter, with_subcontainers)
                all_storage_ids.extend(storage_ids)
                all_cache_ids.extend(cache_ids)
            except WildlandError as ex:
                fails.append(str(ex))

        if fails:
            fails = ['Failed to load some container manifests:'] + fails
    else:
        counter = get_counter(f"Loading containers (from '{path}')")
        storage_ids, cache_ids = _collect_storage_ids_by_container_path(
            obj, PurePosixPath(path), counter, with_subcontainers)
        all_storage_ids.extend(storage_ids)
        all_cache_ids.extend(cache_ids)

    if undo_save:
        default_containers = obj.client.config.get('default-containers')
        # Preserve containers order when removing some of them
        # https://stackoverflow.com/a/53657523/1321680
        default_containers_dict = dict.fromkeys(default_containers)

        if len(default_containers) > len(default_containers_dict):
            click.echo('Removing duplicates found in default-containers in your config file')

        for container_name in container_names:
            if container_name not in default_containers_dict:
                click.echo(f'Not removing {container_name}: not in default-containers')
            else:
                click.echo(f'Removing from default-containers: {container_name}')
                del default_containers_dict[container_name]

        new_default_containers = list(default_containers_dict)

        if len(new_default_containers) < len(default_containers):
            obj.client.config.update_and_save({'default-containers': new_default_containers})

    # remove duplicates while maintaining id order
    all_storage_ids = list(dict.fromkeys(all_storage_ids))
    all_cache_ids = list(dict.fromkeys(all_cache_ids))

    if all_storage_ids or all_cache_ids:
        click.echo(f'Unmounting {len(storage_ids)} containers')
        for storage_id in all_storage_ids:
            obj.fs_client.unmount_storage(storage_id)

        for storage_id in all_cache_ids:
            container = obj.fs_client.get_container_from_storage_id(storage_id)
            obj.client.stop_sync(container.sync_id)
            obj.fs_client.unmount_storage(storage_id)

    elif not undo_save:
        raise WildlandError('No containers mounted')

    if fails:
        raise WildlandError('\n'.join(fails))


def _mount_path_to_backend_id(path: PurePosixPath) -> Optional[str]:
    pattern = r'^/.users/[0-9a-z-]+:/.backends/[0-9a-z-]+/([0-9a-z-]+)$'
    path_regex = re.compile(pattern)
    match = path_regex.match(str(path))
    if match and match.lastindex == 1:
        return match.group(1)
    return None


def _collect_storage_ids_by_container_name(
            obj: ContextObj, container_name: str,
            callback_iter_func=iter, with_subcontainers: bool = True,
        ) -> tuple[List[int], List[int]]:
    """
    Returns a tuple with a list of normal storages and a list of cache storages.
    """

    storage_ids: List[int] = []
    cache_ids = []
    containers = callback_iter_func(obj.client.load_containers_from(container_name))
    for container in containers:
        unique_storage_paths = obj.fs_client.get_unique_storage_paths(container, True)

        cache = obj.client.cache_storage(container)
        for mount_path in unique_storage_paths:
            storage_id = obj.fs_client.find_storage_id_by_path(mount_path)
            is_pseudomanifest = _is_pseudomanifest_primary_mount_path(mount_path)

            if storage_id is None:
                assert not is_pseudomanifest
            else:
                backend_id = _mount_path_to_backend_id(mount_path)
                if cache and cache.params['backend-id'] == backend_id:
                    cache_ids.append(storage_id)
                else:
                    storage_ids.append(storage_id)

        if with_subcontainers:
            sub_ids = obj.fs_client.find_all_subcontainers_storage_ids(container)
            cache = obj.client.cache_storage(container)
            for storage_id in sub_ids:
                if cache and cache.params['backend-id'] == storage_id:
                    cache_ids.append(storage_id)
                else:
                    storage_ids.append(storage_id)

    return storage_ids, cache_ids


def _collect_storage_ids_by_container_path(
            obj: ContextObj, path: PurePosixPath,
            callback_iter_func=iter, with_subcontainers: bool = True
        ) -> tuple[List[int], List[int]]:
    """
    Return all storage IDs corresponding to a given mount path (tuple with normal storages and
    cache storages). Path can be either absolute or relative with respect to the mount directory.
    """

    all_storage_ids = callback_iter_func(obj.fs_client.find_all_storage_ids_by_path(path))
    storage_ids = []
    cache_ids = []

    for storage_id in all_storage_ids:
        container = obj.fs_client.get_container_from_storage_id(storage_id)
        cache = obj.client.cache_storage(container)
        mount_path = obj.fs_client.get_primary_unique_mount_path_from_storage_id(storage_id)
        backend_id = _mount_path_to_backend_id(mount_path)
        if cache and cache.params['backend-id'] == backend_id:
            cache_ids.append(storage_id)
        else:
            storage_ids.append(storage_id)

        if _is_pseudomanifest_storage_id(obj, storage_id):
            logger.debug('Ignoring unmounting solely pseudomanifest path (storage ID = %d)',
                         storage_id)
            continue

        if with_subcontainers:
            subcontainer_storage_ids = obj.fs_client.find_all_subcontainers_storage_ids(container)
            storage_ids.extend(subcontainer_storage_ids)

    return storage_ids, cache_ids


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
        init_logging(False, f"{os.path.expanduser('~')}/.local/share/wildland/wl-mount-watch.log")
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


@container_.command('sync', short_help='start syncing a container')
@click.argument('cont', metavar='CONTAINER')
@click.option('--target-storage', help='specify target storage. Default: first non-local storage'
                                       ' listed in manifest. Can be specified as backend_id or as '
                                       'storage type (e.g. s3)')
@click.option('--source-storage', help='specify source storage. Default: first local storage '
                                       'listed in manifest. Can be specified as backend_id or as '
                                       'storage type (e.g. s3)')
@click.option('--one-shot', is_flag=True, default=False,
              help='perform only one-time sync, do not start syncing daemon')
@click.option('--no-wait', is_flag=True, default=False,
              help="don't wait for a one-shot sync to complete, run in the background")
@click.pass_obj
def sync_container(obj: ContextObj, target_storage, source_storage, one_shot, no_wait, cont):
    """
    Keep the given container in sync across the local storage and selected remote storage
    (by default the first listed in manifest).
    """
    if no_wait and not one_shot:
        raise CliError('--no-wait requires --one-shot')

    client = obj.client
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)

    source = client.get_local_storage(container, source_storage)
    target = client.get_remote_storage(container, target_storage)
    job_id = container.sync_id
    response = client.do_sync(cont, job_id, source.params, target.params, one_shot, unidir=False)

    click.echo(response)

    if one_shot:
        if no_wait:
            click.echo('One-shot sync started, run `wl status` for current status and '
                       '`wl container stop-sync` to stop/clear its status.')
        else:
            click.echo(client.wait_for_sync(job_id)[0])


@container_.command('stop-sync', short_help='stop syncing a container')
@click.argument('cont', metavar='CONTAINER')
@click.pass_obj
def stop_syncing_container(obj: ContextObj, cont):
    """
    Stop sync process for the given container.
    """
    container = obj.client.load_object_from_name(WildlandObject.Type.CONTAINER, cont)
    response = obj.client.stop_sync(container.sync_id)
    click.echo(response)


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

    conflicts: List[SyncConflict] = []
    for storage1, storage2 in combinations(storages, 2):
        syncer = BaseSyncer.from_storages(source_storage=storage1,
                                          target_storage=storage2,
                                          log_prefix=f'Container: {cont}',
                                          one_shot=False, continuous=False, unidirectional=False,
                                          can_require_mount=False)

        conflicts.extend(syncer.iter_conflicts_force())

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
def dump(ctx: click.Context, path: str, decrypt: bool):
    """
    Verify and dump contents of a container.
    """
    cli_common.resolve_object(
        ctx, path, WildlandObject.Type.CONTAINER, cli_common.dump,
        decrypt=decrypt, save_manifest=False
    )


@container_.command(short_help='edit container manifest in external tool')
@click.option('--editor', metavar='EDITOR', help='custom editor')
@click.option('--remount/--no-remount', '-r/-n', default=True, help='remount mounted container')
@click.option('--publish/--no-publish', '-p/-P', default=True, help='publish edited container')
@click.argument('path', metavar='FILE or WLPATH')
@click.pass_context
def edit(ctx: click.Context, path: str, publish: bool, editor: Optional[str], remount: bool):
    """
    Edit container manifest in external tool.
    """
    container, manifest_modified = cli_common.resolve_object(
        ctx, path, WildlandObject.Type.CONTAINER, cli_common.edit, editor=editor, remount=remount)

    if publish and manifest_modified:
        cli_common.republish_object(ctx.obj.client, container)
