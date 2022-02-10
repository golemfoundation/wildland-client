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
Manage users
"""
from copy import deepcopy
from typing import Dict, Iterable, List, Optional, Tuple, Union
from pathlib import PurePosixPath, Path
import click

from wildland.wildland_object.wildland_object import WildlandObject
from wildland.bridge import Bridge
from wildland.cleaner import get_cli_cleaner
from ..user import User

from .cli_base import aliased_group, ContextObj
from .cli_exc import CliError
from ..wlpath import WILDLAND_URL_PREFIX, WildlandPath
from .cli_common import sign, verify, edit, modify_manifest, add_fields, del_fields, dump, \
    check_if_any_options, check_options_conflict, publish, unpublish
from ..exc import WildlandError
from ..manifest.manifest import Manifest
from ..storage_driver import StorageDriver
from ..storage import Storage
from ..log import get_logger
from ..core.wildland_objects_api import WLObjectType, WLUser, WLBridge
from ..core.wildland_result import WLErrorType


logger = get_logger('cli-user')
cleaner = get_cli_cleaner()

@aliased_group('user', short_help='user management')
def user_():
    """
    Manage users
    """


@user_.command(short_help='create user')
@click.option('--key', metavar='KEY',
              help='use existing key pair (provide a filename (without extension); it must be in '
                   '~/.config/wildland/keys/')
@click.option('--path', 'paths', multiple=True,
              help='path (can be repeated)')
@click.option('--add-pubkey', 'additional_pubkeys', multiple=True,
              help='an additional public key that this user owns (can be repeated)')
@click.argument('name', metavar='NAME', required=False)
@click.pass_obj
def create(obj: ContextObj, key, paths, additional_pubkeys, name):
    """
    Create a new user manifest and save it. Clean up created files if fails.
    """
    try:
        _user_create(obj, key, paths, additional_pubkeys, name)
    except Exception as ex:
        click.secho('Creation failed.', fg='red')
        cleaner.clean_up()
        raise ex


def _user_create(obj: ContextObj, key, paths, additional_pubkeys, name):
    """
    Create a new user manifest and save it.
    """
    if key:
        result, pubkey = obj.wlcore.user_get_public_key(key)
        if not result.success:
            raise CliError(f'Failed to use provided key:\n  {result}')
        click.echo(f'Using key: {key}')
        owner = key
    else:
        result, owner, pubkey = obj.wlcore.user_generate_key()
        if not result.success:
            raise CliError(f'Failed to use provided key:\n  {result}')
        click.echo(f'Generated key: {owner}')
    assert pubkey

    keys = [pubkey]
    if additional_pubkeys:
        keys.extend(additional_pubkeys)

    # do paths
    if paths:
        paths = list(paths)
    else:
        if name:
            paths = [f'/users/{name}']
        else:
            paths = [f'/users/{owner}']
        click.echo(f'No path specified, using: {paths[0]}')

    result, user = obj.wlcore.user_create(name, keys, paths)

    if not result.success or not user:
        raise CliError(f'Failed to create user: {result}')

    _, current_default = obj.wlcore.env.get_default_user()
    if not current_default:
        click.echo(f'Using {owner} as @default')
        obj.wlcore.env.set_default_user(owner)
    _, current_default_owner = obj.wlcore.env.get_default_owner()
    if not current_default_owner:
        click.echo(f'Using {owner} as @default-owner')
        obj.wlcore.env.set_default_owner(owner)

    click.echo(f'Adding {owner} to local owners')
    obj.wlcore.env.add_local_owners(owner)


@user_.command('list', short_help='list users', alias=['ls'])
@click.option('--verbose', '-v', is_flag=True,
              help='Show extended output')
@click.option('--list-secret-keys', '-K', is_flag=True,
              help='Show users with private key available only')
@click.pass_obj
def list_(obj: ContextObj, verbose, list_secret_keys):
    """
    Display known users.
    """

    default_user = obj.wlcore.env.get_default_user()[1]
    default_owner = obj.wlcore.env.get_default_owner()[1]
    default_override = (default_user != obj.wlcore.env.get_default_user(use_override=False)[1])

    result_users, users = obj.wlcore.user_list()
    result_bridges, bridges = obj.wlcore.bridge_list()

    if not result_bridges.success or not result_users.success:
        click.echo('Failed to list users:')
        for e in result_users.errors + result_bridges.errors:
            click.echo(f'Error {e.error_code}: {e.error_description}')

    # TODO: this used to use a client method called load_users_with_bridge_paths; perhaps this
    # will be obsolete soon?

    bridges_from_default_user: Dict[str, List[str]] = dict()
    for bridge in bridges:
        if bridge.owner != default_user:
            continue
        if bridge.user_id not in bridges_from_default_user:
            bridges_from_default_user[bridge.user_id] = []
        bridges_from_default_user[bridge.user_id].extend(bridge.paths)

    for user in users:
        _, path = obj.wlcore.object_get_local_path(WLObjectType.USER, user.id)
        path_string = str(path)
        if list_secret_keys and not user.private_key_available:
            continue
        if user.owner == default_user:
            path_string += ' (@default)'
            if default_override:
                path_string += ' (@default overriden by wl start parameters)'
        if user.owner == default_owner:
            path_string += ' (@default-owner)'
        click.echo(path_string)
        click.echo(f'  owner: {user.owner}')
        if user.private_key_available:
            click.echo('  private and public keys available')
        else:
            click.echo('  only public key available')
        if user.owner not in bridges_from_default_user:
            click.echo('   no bridges to user available')
        else:
            for bridge_path in bridges_from_default_user[user.owner]:
                click.echo(f'   bridge path: {bridge_path}')
        for user_path in user.paths:
            click.echo(f'   user path: {user_path}')

        if verbose:
            for user_container in user.manifest_catalog_description:
                click.echo(f'   container: {user_container}')
        click.echo()


@user_.command('delete', short_help='delete a user', alias=['rm', 'remove'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if still has containers/storage')
@click.option('--cascade', is_flag=True,
              help='remove all containers and storage as well')
@click.option('--delete-keys', is_flag=True,
              help='also remove user keys')
@click.argument('names', metavar='NAME', nargs=-1)
def delete(obj: ContextObj, names, force, cascade, delete_keys):
    """
    Delete a user.
    """

    error_messages = ''
    for name in names:
        try:
            _delete(obj, name, force, cascade, delete_keys)
        except Exception as e:
            error_messages += f'{e}\n'

    if error_messages:
        raise CliError(f'Some users could not be deleted:\n{error_messages.strip()}')


def _delete(obj: ContextObj, name: str, force: bool, cascade: bool, delete_keys: bool):
    _, user = obj.wlcore.object_get(WLObjectType.USER, name)
    if not user:
        p = Path(name)
        if not p.exists():
            raise CliError(f'User {name} not found.')
        yaml_data = p.read_text()
        result, user = obj.wlcore.object_info(yaml_data)
        if not user:
            raise CliError(f'User {name} cannot be parsed: {str(result)}')

    result, usages = obj.wlcore.user_get_usages(user.id)
    if not result.success and not force:
        raise CliError(f'Fatal error while looking for user\'s containers: {str(result)}')

    used = False
    for usage in usages:
        if cascade:
            click.echo('Deleting container: {}'.format(usage.id))
            result = obj.wlcore.container_delete(usage.id)
            if not result.success:
                raise CliError(f'Cannot delete user\'s container: {result}')
        else:
            _, cont_path = obj.wlcore.object_get_local_path(WLObjectType.CONTAINER, usage.id)
            click.echo('Found container: {}'.format(cont_path))
            used = True

    if used and not force:
        raise CliError('User still has manifests, not deleting '
                       '(use --force or --cascade)')

    if delete_keys:
        result = obj.wlcore.user_remove_key(user.owner, force=force)
        if not result.success:
            raise CliError(str(result))

    _, default_user = obj.wlcore.env.get_default_user(use_override=False)
    if default_user == user.owner:
        click.echo('Removing @default from configuration file')
        obj.wlcore.env.reset_default_user()
    _, default_owner = obj.wlcore.env.get_default_owner()
    if default_owner == user.owner:
        click.echo('Removing @default-owner from configuration file')
        obj.wlcore.env.reset_default_owner()

    if obj.wlcore.env.is_local_owner(user.owner):
        obj.wlcore.env.remove_local_owners(user.owner)
        click.echo(f'Removing {user.owner} from local_owners')

    click.echo(f'Deleting: {user.owner}')
    result = obj.wlcore.user_delete(user.owner)
    if not result.success:
        raise CliError(f'Failed to delete user: {result}')


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
    cleaner.add_path(destination)
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
        manifest_path, manifest_url = _do_import_manifest(obj, path_or_url)
        if not manifest_path or not manifest_url:
            return
        _do_process_imported_manifest(obj, manifest_path, manifest_url, posix_paths, default_user)
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


@user_.command('import', short_help='import bridge or user manifest', alias=['im'])
@click.pass_obj
@click.option('--path', 'paths', multiple=True,
              help='path for resulting bridge manifest (can be repeated); if omitted, will'
                   ' use user\'s paths')
@click.option('--bridge-owner', help="specify a different (then default) user to be used as the "
                                     "owner of created bridge manifests")
@click.argument('path-or-url')
def user_import(obj: ContextObj, path_or_url: str, paths: List[str], bridge_owner: Optional[str]):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --path.
    Created bridge manifests will use system @default-owner, or --bridge-owner is specified.
    """
    try:
        _user_import(obj, path_or_url, paths, bridge_owner)
    except Exception as ex:
        click.secho('Import failed.', fg='red')
        cleaner.clean_up()
        raise CliError(f'Failed to import: {str(ex)}') from ex


def _user_import(obj: ContextObj, path_or_url: str, paths: List[str], bridge_owner: Optional[str]):
    """
    Import a provided user or bridge manifest.
    """
    p = Path(path_or_url)
    name = path_or_url
    name = name.split('/')[-1]

    if p.exists():
        yaml_data = p.read_bytes()
        name = p.name
        result, imported_object = obj.wlcore.object_import_from_yaml(yaml_data, name)
    else:
        result, imported_object = obj.wlcore.object_import_from_url(path_or_url, name)

    if not result.success:
        if len(result.errors) == 1 and result.errors[0].error_code == WLErrorType.FILE_EXISTS_ERROR:
            result, imported_object = obj.wlcore.user_get_by_id(result.errors[0].error_description)
            if not imported_object:
                raise CliError(f'Failed to import manifest: {str(result)}')
            click.echo('User already exists, skipping.')
        else:
            raise CliError(f'Failed to import manifest: {str(result)}')

    if isinstance(imported_object, WLUser):
        result, bridges = obj.wlcore.bridge_list()
        for bridge in bridges:
            if bridge.user_id == imported_object.owner:
                click.echo('Bridge already exists, skipping.')
                return
        result, _ = obj.wlcore.bridge_create(paths, bridge_owner, imported_object.owner,
                                             user_url=path_or_url, name=name)
    elif isinstance(imported_object, WLBridge):
        # TODO: this requires better handling through wlcore's bridge function, which are
        # TODO: not yet implemented. See #698
        obj.wlcore.bridge_delete(imported_object.id)
        import_manifest(obj, path_or_url, paths, WildlandObject.Type.USER, bridge_owner, False)
    else:
        raise CliError(f'Cannot import {path_or_url}: only user or bridge '
                       f'manifests can be imported')

    if not result.success:
        raise CliError(f'Failed to import {path_or_url}: {result}')

@user_.command('refresh', short_help='Iterate over bridges and pull latest user manifests',
               alias=['r'])
@click.pass_obj
@click.argument('name', metavar='USER', required=False)
def user_refresh(obj: ContextObj, name):
    """
    Iterates over bridges and fetches each user's file from the URL specified in the bridge
    """
    user_list: Optional[List[str]]

    if name:
        result, user = obj.wlcore.object_get(WLObjectType.USER, name)
        if not result.success or not user:
            raise CliError(f'User {name} cannot be loaded: {result}')
        user_list = [user.id]
    else:
        user_list = None

    result = obj.wlcore.user_refresh(user_list)
    if not result.success:
        raise CliError(f'Failed to refresh users: {result}')


# TODO: this is currently used by cli_forest, see #702
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


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
user_.add_command(dump)
user_.add_command(publish)
user_.add_command(unpublish)


@user_.command(short_help='modify user manifest')
@click.option('--add-path', metavar='PATH', multiple=True, help='path to add')
@click.option('--del-path', metavar='PATH', multiple=True, help='path to remove')
@click.option('--add-catalog-entry', metavar='PATH', multiple=True, help='container path to add')
@click.option('--del-catalog-entry', metavar='PATH', multiple=True, help='container path to remove')
@click.option('--add-pubkey', metavar='PUBKEY', multiple=True, help='raw public key to append')
@click.option('--add-pubkey-user', metavar='USER', multiple=True,
              help='user whose public keys should be appended to FILE')
@click.option('--del-pubkey', metavar='PUBKEY', multiple=True, help='public key to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def modify(ctx: click.Context,
           add_path, del_path, add_catalog_entry, del_catalog_entry,
           add_pubkey, add_pubkey_user, del_pubkey,
           input_file
           ):
    """
    Command for modifying user manifests.
    """
    _option_check(ctx, add_path, del_path, add_catalog_entry, del_catalog_entry,
                  add_pubkey, add_pubkey_user, del_pubkey)

    add_members = []
    add_pubkeys = []
    for p in add_pubkey:
        if WildlandPath.WLPATH_RE.match(p):
            add_members.append({"user-path": WildlandPath.get_canonical_form(p)})
        else:
            add_pubkeys.append(p)

    del_members = []
    del_pubkeys = []
    for p in del_pubkey:
        if WildlandPath.WLPATH_RE.match(p):
            del_members.append({"user-path": WildlandPath.get_canonical_form(p)})
        else:
            del_pubkeys.append(p)

    pubkeys = _get_all_pubkeys_and_check_conflicts(ctx, add_pubkeys, add_pubkey_user, del_pubkeys)

    to_add = {'paths': add_path, 'manifests-catalog': add_catalog_entry,
              'pubkeys': pubkeys, 'members': add_members}
    to_del = {'paths': del_path, 'manifests-catalog': del_catalog_entry,
              'pubkeys': del_pubkeys, 'members': del_members}

    modify_manifest(ctx, input_file,
                    edit_funcs=[add_fields, del_fields],
                    to_add=to_add,
                    to_del=to_del,
                    logger=logger)


def _option_check(ctx, add_path, del_path, add_catalog_entry, del_catalog_entry,
                  add_pubkey, add_pubkey_user, del_pubkey):
    check_if_any_options(ctx, add_path, del_path, add_catalog_entry, del_catalog_entry,
                         add_pubkey, add_pubkey_user, del_pubkey)
    check_options_conflict("path", add_path, del_path)
    check_options_conflict("catalog_entry", add_catalog_entry, del_catalog_entry)
    check_options_conflict("pubkey", add_pubkey, del_pubkey)


def _get_all_pubkeys_and_check_conflicts(ctx, add_pubkey, add_pubkey_user, del_pubkey):
    pubkeys = set(add_pubkey)

    conflicts = ""
    for name in add_pubkey_user:
        user_obj = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, name)

        click.echo(f'Pubkeys found in [{name}]:')

        for key in user_obj.pubkeys:
            click.echo(f'  {key}')

        pubkey_conflicts = set(del_pubkey).intersection(user_obj.pubkeys)
        if pubkey_conflicts:
            conflicts += 'Error: options conflict:'
            for c in pubkey_conflicts:
                conflicts += f'\n  --add-pubkey-user {name} and --del-pubkey {c}' \
                             f'\n    User {name} has a pubkey {c}'

        pubkeys.update(user_obj.pubkeys)
    if conflicts:
        raise CliError(conflicts)

    for key in pubkeys:
        if not ctx.obj.session.sig.is_valid_pubkey(key):
            raise CliError(f'Given pubkey [{key}] is not a valid pubkey')

    return pubkeys
