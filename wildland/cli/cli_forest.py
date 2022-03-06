# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
Manage bridges
"""

from pathlib import Path, PurePosixPath
from typing import List, Dict, Any, Optional, Tuple, Union, Iterable
from copy import deepcopy

import logging
import os
import click

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_storage import do_create_storage_from_templates
from ..container import Container
from ..storage import StorageBackend, Storage
from ..storage_backends.file_children import FileChildrenMixin
from ..user import User
from ..utils import YAMLParserError
from ..publish import Publisher
from ..manifest.template import TemplateManager, StorageTemplate
from ..manifest.manifest import Manifest
from .cli_base import aliased_group, ContextObj
from .cli_exc import CliError
from ..wlpath import WildlandPath, WILDLAND_URL_PREFIX
from .cli_common import modify_manifest, add_fields
from .cli_container import _mount as mount_container
from .cli_container import _unmount as unmount_container
from ..exc import WildlandError
from ..storage_driver import StorageDriver
from ..bridge import Bridge

logger = logging.getLogger('cli-forest')


@aliased_group('forest', short_help='Wildland Forest management')
def forest_():
    """
    Manage Wildland Forests
    """


def _remove_suffix(s: str, suffix: str) -> str:
    if suffix and s.endswith(suffix):
        return s[:-len(suffix)]
    return s


def _do_import_manifest(obj, path_or_dict, manifest_owner: Optional[str] = None,
                        force: bool = False) -> Tuple[Optional[Path], Optional[str]]:
    """
    Takes a user or bridge manifest as pointed towards by path (can be local file path, url,
    wildland url), imports its public keys, copies the manifest itself.
    :param obj: ContextObj
    :param path_or_dict: (potentially ambiguous) path to manifest to be imported
    or dictionary with manifest fields of link object (see `Link.to_manifest_fields`)
    :return: tuple of local path to copied manifest , url to manifest (local or remote, depending on
        input)
    """

    local_url = False

    # TODO: Accepting paths (string) should be deprecated and force using link objects
    if isinstance(path_or_dict, dict):
        if path_or_dict.get('object') != WildlandObject.Type.LINK.value:
            raise CliError(f'Dictionary object must be of type {WildlandObject.Type.LINK.value}')

        if not manifest_owner:
            raise CliError('Unable to import a link object without specifying expected owner')

        link = obj.client.load_link_object(path_or_dict, manifest_owner)
        file_path = link.file_path
        file_data = link.get_target_file()
        file_name = file_path.stem
        file_url = None
    else:
        path = str(path_or_dict)

        if Path(path).exists():
            file_data = Path(path).read_bytes()
            file_name = Path(path).stem
            file_url = None
            local_url = True
        elif obj.client.is_url(path):
            try:
                file_data = obj.client.read_from_url(path, use_aliases=True)
            except FileNotFoundError as fnf:
                raise CliError(f'File {path} not found') from fnf

            file_name = _remove_suffix(Path(path).name, '.yaml')
            file_url = path
        else:
            raise CliError(f'File {path} not found')

    # load user pubkeys
    Manifest.verify_and_load_pubkeys(file_data, obj.session.sig)

    # determine type
    manifest = Manifest.from_bytes(file_data, obj.session.sig)
    import_type = WildlandObject.Type(manifest.fields['object'])

    if import_type not in [WildlandObject.Type.USER, WildlandObject.Type.BRIDGE]:
        raise CliError('Can import only user or bridge manifests')

    file_name = _remove_suffix(file_name, '.' + import_type.value)

    # do not import existing users, unless forced
    user_exists = False
    if import_type == WildlandObject.Type.USER:
        imported_user = WildlandObject.from_manifest(manifest, obj.client, WildlandObject.Type.USER,
                                                     pubkey=manifest.fields['pubkeys'][0])
        for user in obj.client.get_local_users():
            if user.owner == imported_user.owner:
                if not force:
                    if any(user.owner == b.user_id for b in obj.client.get_local_bridges()):
                        click.echo(f"User {user.owner} and their bridge already exist. "
                                   f"Skipping import.")
                        return None, None

                    click.echo(f"User {user.owner} already exists. Creating their bridge.")
                    file_path = obj.client.local_url(Path(user.manifest.local_path).absolute())
                    return user.manifest.local_path, file_path

                click.echo(f'User {user.owner} already exists. Forcing user import.')
                user_exists = True
                file_name = Path(user.local_path).name.rsplit('.', 2)[0]
                break

    # copying the user manifest
    destination = obj.client.new_path(import_type, file_name, skip_numeric_suffix=force)
    destination.write_bytes(file_data)
    if user_exists:
        msg = f'Updated: {str(destination)}'
    else:
        msg = f'Created: {str(destination)}'
    click.echo(msg)

    if local_url:
        file_url = obj.client.local_url(Path(destination).absolute())

    return destination, file_url


def find_user_manifest_within_catalog(obj, user: User) -> \
        Optional[Tuple[Storage, PurePosixPath]]:
    """
    Mounts containers of the given user's manifests-catalog and attempts to find that user's
    manifest file within that catalog.
    The user manifest file is expected to be named 'forest-owner.user.yaml' and be placed in the
    root directory of a storage.

    :param obj: ContextObj
    :param user: User
    :return: tuple of Storage where the user manifest was found and PurePosixPath path pointing
    at that manifest in the storage
    """
    for container in user.load_catalog(warn_about_encrypted_manifests=False):
        all_storages = obj.client.all_storages(container=container)

        for storage_candidate in all_storages:
            with StorageDriver.from_storage(storage_candidate) as driver:
                try:
                    file_candidate = PurePosixPath('forest-owner.user.yaml')
                    file_content = driver.read_file(file_candidate)

                    # Ensure you're able to load this object
                    obj.client.load_object_from_bytes(
                        WildlandObject.Type.USER, file_content, expected_owner=user.owner)

                    return storage_candidate, file_candidate

                except (FileNotFoundError, WildlandError) as ex:
                    logger.debug('Could not read user manifest. Exception: %s', ex)

    return None


def _do_process_imported_manifest(
        obj: ContextObj, copied_manifest_path: Path, user_manifest_location: str,
        paths: List[PurePosixPath], default_user: str):
    """
    Perform followup actions after importing a manifest: create a Bridge manifest for a user,
    import a Bridge manifest's target user
    :param obj: ContextObj
    :param copied_manifest_path: Path to where the manifest was copied
    :param user_manifest_location: url to manifest (local or remote, depending on input)
    :param paths: list of paths to use in created Bridge manifest
    :param default_user: owner of the manifests to be created
    """
    manifest = Manifest.from_file(copied_manifest_path, obj.session.sig)

    if manifest.fields['object'] == 'user':
        user = WildlandObject.from_manifest(manifest, obj.client, WildlandObject.Type.USER,
                                            pubkey=manifest.fields['pubkeys'][0])
        result = find_user_manifest_within_catalog(obj, user)

        user_location: Union[str, dict] = user_manifest_location

        if result:
            storage, file_path = result

            storage.owner = default_user
            user_location = {
                'object': WildlandObject.Type.LINK.value,
                'file': str(('/' / file_path)),
                'storage': storage.to_manifest_fields(inline=True)
            }

        fingerprint = obj.client.session.sig.fingerprint(user.primary_pubkey)

        bridge = Bridge(
            owner=default_user,
            user_location=user_location,
            user_pubkey=user.primary_pubkey,
            user_id=fingerprint,
            paths=(paths or Bridge.create_safe_bridge_paths(fingerprint, user.paths)),
            client=obj.client
        )

        name = _remove_suffix(copied_manifest_path.stem, ".user")
        bridge_path = obj.client.save_new_object(WildlandObject.Type.BRIDGE, bridge, name)
        click.echo(f'Created: {bridge_path}')
    else:
        bridge = WildlandObject.from_manifest(
            manifest, obj.client, WildlandObject.Type.BRIDGE)

        # adjust imported bridge
        if default_user:
            bridge.owner = default_user

        bridge.paths = list(paths) or Bridge.create_safe_bridge_paths(bridge.user_id, bridge.paths)

        copied_manifest_path.write_bytes(obj.session.dump_object(bridge))
        _do_import_manifest(obj, bridge.user_location, bridge.owner)


def import_manifest(obj: ContextObj, path_or_url: str, paths: Iterable[str],
                    wl_obj_type: WildlandObject.Type, bridge_owner: Optional[str],
                    only_first: bool):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --path.
    Separate function so that it can be used by both wl bridge and wl user
    """
    if bridge_owner:
        default_user = obj.client.load_object_from_name(
            WildlandObject.Type.USER, bridge_owner).owner
    else:
        default_user = obj.client.config.get('@default-owner')

    if not default_user:
        raise CliError('Cannot import user or bridge without a --bridge-owner or a default user.')

    posix_paths = [PurePosixPath(p) for p in paths]

    if wl_obj_type == WildlandObject.Type.USER:
        copied_manifest_path, manifest_url = _do_import_manifest(obj, path_or_url)
        if not copied_manifest_path or not manifest_url:
            return
        try:
            _do_process_imported_manifest(
                obj, copied_manifest_path, manifest_url, posix_paths, default_user)
        except Exception as ex:
            click.echo(
                f'Import error occurred. Removing created files: {str(copied_manifest_path)}')
            copied_manifest_path.unlink()
            raise CliError(f'Failed to import: {str(ex)}') from ex
    elif wl_obj_type == WildlandObject.Type.BRIDGE:
        if Path(path_or_url).exists():
            path = Path(path_or_url)
            bridges = [
                obj.client.load_object_from_bytes(
                    WildlandObject.Type.BRIDGE, path.read_bytes(), file_path=path)
            ]
            name = path.stem
        else:
            bridges = list(obj.client.read_bridge_from_url(path_or_url, use_aliases=True))
            name = path_or_url.replace(WILDLAND_URL_PREFIX, '')

        if not bridges:
            raise CliError('No bridges found.')
        if only_first:
            bridges = [bridges[0]]
        if len(bridges) > 1 and paths:
            raise CliError('Cannot import multiple bridges with --path override.')

        copied_files = []
        try:
            for bridge in bridges:
                fingerprint = obj.client.session.sig.fingerprint(bridge.user_pubkey)

                new_bridge = Bridge(
                    owner=default_user,
                    user_location=deepcopy(bridge.user_location),
                    user_pubkey=bridge.user_pubkey,
                    user_id=fingerprint,
                    paths=(posix_paths or
                           Bridge.create_safe_bridge_paths(fingerprint, bridge.paths)),
                    client=obj.client
                )
                bridge_name = name.replace(':', '_').replace('/', '_')
                bridge_path = obj.client.save_new_object(
                    WildlandObject.Type.BRIDGE, new_bridge, bridge_name, None)
                click.echo(f'Created: {bridge_path}')
                copied_files.append(bridge_path)
                _do_import_manifest(obj, bridge.user_location, bridge.owner)
        except Exception as ex:
            for file in copied_files:
                click.echo(
                    f'Import error occurred. Removing created files: {str(file)}')
                file.unlink(missing_ok=True)
            raise CliError(f'Failed to import: {str(ex)}') from ex
    else:
        raise CliError(f"[{wl_obj_type}] object type is not supported")


def refresh_users(obj: ContextObj, user_list: Optional[List[User]] = None):
    """
    Refresh user manifests. Users can come from user_list parameter, or, if empty, all users
    referred to by local bridges will be refreshed.
    """
    user_fingerprints = [user.owner for user in user_list] if user_list is not None else None

    users_to_refresh: Dict[str, Union[dict, str]] = dict()
    for bridge in obj.client.get_local_bridges():
        if user_fingerprints is not None and \
                obj.client.session.sig.fingerprint(bridge.user_pubkey) not in user_fingerprints:
            continue
        if bridge.owner in users_to_refresh:
            # this is a heuristic to avoid downloading the same user multiple times, but
            # preferring link object to bare URL
            if isinstance(users_to_refresh[bridge.owner], str) and \
                    isinstance(bridge.user_location, dict):
                users_to_refresh[bridge.owner] = bridge.user_location
        else:
            users_to_refresh[bridge.owner] = bridge.user_location

    for owner, location in users_to_refresh.items():
        try:
            _do_import_manifest(obj, location, owner, force=True)
        except WildlandError as ex:
            click.secho(f"Error while refreshing bridge: {ex}", fg="red")


@forest_.command(short_help='Mount Wildland Forest')
@click.argument('forest_names', nargs=-1, required=True)
@click.option('--lazy/--no-lazy', default=True,
              help='Allow lazy mount of storages')
@click.option('--save', '-s', is_flag=True,
              help='Save the forest containers to be mounted at startup')
@click.option('--with-cache', '-c', is_flag=True, default=False,
              help='Use the default cache storage template to create and use a new cache storage '
                   '(becomes primary storage for the container while mounted, synced with '
                   'the old primary). '
                   'Cache template to use can be overriden using the --cache-template option.')
@click.option('--cache-template', metavar='TEMPLATE',
              help='Use specified storage template to create and use a new cache storage')
@click.option('--list-all', '-l', is_flag=True,
              help='During mount, list all forest containers, including those '
                   'who did not need to be changed')
@click.option('--no-refresh-users', '-n', is_flag=True, default=False,
              help="Do not refresh remote users when mounting")
@click.pass_context
def mount(ctx: click.Context, forest_names, lazy: bool, save: bool,
          with_cache: bool, cache_template: str,
          list_all: bool, no_refresh_users: bool):
    """
    Mount a forest given by name or path to manifest. Repeat the argument to
    mount multiple forests.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    obj: ContextObj = ctx.obj

    forests = []
    for forest_name in forest_names:
        if forest_name.endswith('*:') or not forest_name.endswith(':'):
            raise WildlandError(
                f'Failed to parse forest name: {forest_name}. '
                f'For example, ":/forests/User:" is a valid forest name')

        if WildlandPath.FOREST_VIA_USER_RE.match(forest_name):
            bridge_paths = list(obj.client.get_bridge_paths_for_user(
                f'{forest_name.split(":")[0]}'))
        else:
            bridge_paths = list(obj.client.read_bridge_from_url(forest_name, use_aliases=True))

        if bridge_paths:
            forests.append(f'{forest_name}*:')
        else:
            click.secho(f'Warning: Did not find bridge for: {forest_name}', fg="yellow")

    if len(forests) <= 0:
        raise WildlandError('No valid forest to be mount found')

    if with_cache and not cache_template:
        cache_template = obj.client.config.get('default-cache-template')
        if not cache_template:
            raise WildlandError('Default cache template not set, set one with '
                                '`wl set-default-cache` or use --cache-template option')

    # TODO: in versions v.0.0.2 or up
    # Refresh all local users; this could be optimized by refactoring search.py itself
    # to only use remote users, not local
    if not no_refresh_users:
        refresh_users(obj)

    mount_container(
        obj, forests, lazy=lazy, save=save, cache_template=cache_template, list_all=list_all)


@forest_.command(short_help='Unmount Wildland Forest', alias=['umount'])
@click.option('--path', metavar='PATH', help='mount path to search for')
@click.argument('forest_names', nargs=-1, required=True)
@click.pass_context
def unmount(ctx: click.Context, path: str, forest_names):
    """
    Unmount a forest given by name or path to manifest. Repeat the argument to
    unmount multiple forests.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    obj: ContextObj = ctx.obj

    forests = []
    for forest_name in forest_names:
        if forest_name.endswith('*:') or not forest_name.endswith(':'):
            raise WildlandError(
                f'Failed to parse forest name: {forest_name}. '
                f'For example, ":/forests/User:" is a valid forest name')
        forests.append(f'{forest_name}*:')
    unmount_container(obj, path=path, container_names=forests)


@forest_.command(short_help='Bootstrap Wildland Forest')
@click.argument('storage_template', required=True)
@click.option('--owner', '--user', metavar='USER', required=False,
              default='@default-owner',
              help='User for signing')
@click.option('--access', metavar='USER', required=False, multiple=True,
              help='Name of users to encrypt the container with. Can be used multiple times. '
                   'If not set, the container is unencrypted.')
@click.option('--manifest-local-dir', metavar='PATH', required=False, multiple=False,
              default='/.manifests',
              help='Set manifests local directory. Must be an absolute path.')
@click.pass_context
def create(ctx: click.Context,
           storage_template: str,
           owner: str = '@default-owner',
           manifest_local_dir: str = '/.manifests/',
           access: List[str] = None):
    """
    Bootstrap a new Forest. If owner is not specified, @default-owner is used.
    You must have a private key of the owner in order to use this command.

    \b
    Arguments:
      STORAGE_TEMPLATE      storage template used to create Forest containers

    Description

    This command creates a manifest catalog entry for the Forest.
    The storage template *must* contain at least one read-write storage.

    After the container is created, the following steps take place:

    \b
      1. A link object to the container is generated
         and appended to USER's manifests catalog.
      2. USER manifest and container manifest are copied to the
         storage from Forest manifests container

    """
    access_list = []
    if access:
        for user in access:
            if WildlandPath.WLPATH_RE.match(user):
                access_list.append({"user-path": user})
            else:
                access_list.append({"user": user})

    _bootstrap_forest(ctx, owner, storage_template, manifest_local_dir, access_list)


def _bootstrap_forest(ctx: click.Context, user: str, manifest_storage_template_name: str,
                      manifest_local_dir: str = '/', access: List[Dict] = None):

    obj: ContextObj = ctx.obj

    # Load users manifests
    try:
        forest_owner = obj.client.load_object_from_name(WildlandObject.Type.USER, user)
        if user == '@default-owner':
            # retrieve owner's name from path
            user = forest_owner.paths[0].parts[-1]
    except WildlandError as we:
        raise CliError(f'User [{user}] could not be loaded. {we}') from we

    if not obj.client.session.sig.is_private_key_available(forest_owner.owner):
        raise CliError(f'Forest owner\'s [{user}] private key not found.')

    if access:
        if len(access) == 1 and access[0].get("user", None) == '*':
            access_list = [{'user': '*'}]
        else:
            access_list = []
            try:
                for a in access:
                    if a.get("user", None):
                        access_list.append({'user': obj.client.load_object_from_name(
                                WildlandObject.Type.USER, a["user"]).owner})
                    elif a.get("user-path", None):
                        access_list.append(
                            {'user-path': WildlandPath.get_canonical_form(a["user-path"])})
            except WildlandError as we:
                raise CliError(f'User could not be loaded. {we}') from we
    else:
        access_list = [{'user': forest_owner.owner}]

    storage_templates = _resolve_storage_templates(obj, manifest_storage_template_name)

    catalog_container = None

    try:
        catalog_container = _create_container(obj, forest_owner, [Path('/.manifests')],
                                              f'{user}-forest-catalog', access_list,
                                              storage_templates, manifest_local_dir)

        assert catalog_container.local_path is not None
        assert forest_owner.local_path is not None

        catalog_storage = obj.client.select_storage(container=catalog_container,
                                                    predicate=lambda x: x.is_writeable)

        # If a writeable catalog storage doesn't have manifest_pattern defined,
        # forcibly set manifest pattern for all storages in this container.
        # TODO: improve support for more complex forms of writeable storages and more complex
        # manifest-patterns

        catalog_backend = StorageBackend.from_params(catalog_storage.params)
        if isinstance(catalog_backend, FileChildrenMixin) and \
                not catalog_backend.params.get('manifest-pattern'):
            catalog_backend.params['manifest-pattern'] = catalog_backend.DEFAULT_MANIFEST_PATTERN

        # Additionally ensure that they are going to be stored inline and override old storages
        # completely

        old_storages = list(obj.client.all_storages(catalog_container))

        catalog_container.clear_storages()

        for storage in old_storages:
            storage.params['manifest-pattern'] = catalog_storage.params['manifest-pattern']

        obj.client.add_storage_to_container(catalog_container, old_storages, inline=True)

        obj.client.save_object(WildlandObject.Type.CONTAINER, catalog_container)

        manifests_storage = obj.client.select_storage(container=catalog_container,
                                                      predicate=lambda x: x.is_writeable)
        manifests_backend = StorageBackend.from_params(manifests_storage.params)

        for storage in obj.client.all_storages(container=catalog_container):
            storage_backend = StorageBackend.from_params(storage.params)
            assert isinstance(storage_backend, FileChildrenMixin), \
                'Unsupported catalog storage type.'
            rel_path = storage_backend.get_relpaths(
                catalog_container.get_primary_publish_path(),
                catalog_container.get_publish_paths())

            link_obj: Dict[str, Any] = {'object': 'link', 'file': f'/{list(rel_path)[0]}'}

            fields = storage.to_manifest_fields(inline=True)
            if not storage.access:
                fields['access'] = obj.client.load_pubkeys_from_field(
                    access_list, forest_owner.owner)

            link_obj['storage'] = fields
            if storage.owner != forest_owner.owner:
                link_obj['storage-owner'] = storage.owner

            modify_manifest(ctx, str(forest_owner.local_path), edit_funcs=[add_fields],
                            to_add={'manifests-catalog': [link_obj]})

        # Refresh user's manifests catalog
        obj.client.recognize_users_and_bridges()

        _bootstrap_manifest(manifests_backend, forest_owner.local_path,
                            Path('forest-owner.user.yaml'))

        # Reload forest_owner to load the manifests-catalog info
        forest_owner = obj.client.load_object_from_name(WildlandObject.Type.USER, user)
        Publisher(obj.client, forest_owner, catalog_container).publish(catalog_container)
    except Exception as ex:
        raise CliError(f'Could not create a Forest. {ex}') from ex
    finally:
        if catalog_container and catalog_container.local_path:
            catalog_container.local_path.unlink()


def _resolve_storage_templates(obj, template_name: str) -> List[StorageTemplate]:
    try:
        tpl_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

        return tpl_manager.get_template_file_by_name(template_name).templates
    except (WildlandError, YAMLParserError) as err:
        raise CliError(f'Could not load [{template_name}] storage template. {err}') from err


def _create_container(obj: ContextObj,
                      user: User,
                      container_paths: List[Path],
                      container_name: str,
                      access: List[dict],
                      storage_templates: List[StorageTemplate],
                      storage_local_dir: str = '') -> Container:

    container = Container(owner=user.owner, paths=[PurePosixPath(p) for p in container_paths],
                          backends=[], client=obj.client, access=access)

    obj.client.save_new_object(WildlandObject.Type.CONTAINER, container, container_name)
    do_create_storage_from_templates(obj.client, container, storage_templates, storage_local_dir)

    return container


def _bootstrap_manifest(backend: StorageBackend, manifest_path: Path, file_path: Path):
    with backend:
        with backend.create(PurePosixPath(file_path), os.O_CREAT | os.O_WRONLY) as manifest_obj:
            data = manifest_path.read_bytes()
            manifest_obj.write(data, 0)
