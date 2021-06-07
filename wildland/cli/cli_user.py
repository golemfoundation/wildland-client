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
from typing import Tuple, Optional, Union, List, Dict
from pathlib import PurePosixPath, Path
import logging
import binascii
import click

from wildland.wildland_object.wildland_object import WildlandObject
from wildland.bridge import Bridge
from ..user import User

from .cli_base import aliased_group, ContextObj, CliError
from ..wlpath import WILDLAND_URL_PREFIX
from .cli_common import sign, verify, edit, modify_manifest, add_field, del_field, dump
from ..exc import WildlandError
from ..manifest.schema import SchemaError
from ..manifest.sig import SigError
from ..manifest.manifest import Manifest
from ..storage_driver import StorageDriver
from ..storage import Storage

logger = logging.getLogger('cli-user')


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
    Create a new user manifest and save it.
    """

    if key:
        try:
            owner, pubkey = obj.session.sig.load_key(key)
        except SigError as ex:
            click.echo(f'Failed to use provided key: {ex}')
            return
        click.echo(f'Using key: {owner}')
    else:
        owner, pubkey = obj.session.sig.generate()
        click.echo(f'Generated key: {owner}')

    if paths:
        paths = list(paths)
    else:
        if name:
            paths = [f'/users/{name}']
        else:
            paths = [f'/users/{owner}']
        click.echo(f'No path specified, using: {paths[0]}')

    if additional_pubkeys:
        additional_pubkeys = list(additional_pubkeys)
    else:
        additional_pubkeys = []

    user = User(
        owner=owner,
        pubkeys=[pubkey] + additional_pubkeys,
        paths=[PurePosixPath(p) for p in paths],
        manifests_catalog=[],
        client=obj.client
    )
    try:
        error_on_save = False
        path = obj.client.save_new_object(WildlandObject.Type.USER, user, name)
    except binascii.Error as ex:
        # Separate error to provide some sort of readable feedback
        # raised by SigContext.fingerprint through base64.b64decode
        click.echo(f'Failed to create user due to incorrect key provided (provide public '
                   f'key, not path to key file): {ex}')
        error_on_save = True
    except SchemaError as ex:
        click.echo(f'Failed to create user: {ex}')
        error_on_save = True

    if error_on_save:
        if not key:
            # remove generated keys that will not be used due to failure at creating user
            obj.session.sig.remove_key(owner)
        return

    user.add_user_keys(obj.session.sig)

    click.echo(f'Created: {path}')

    for alias in ['@default', '@default-owner']:
        if obj.client.config.get(alias) is None:
            click.echo(f'Using {owner} as {alias}')
            obj.client.config.update_and_save({alias: owner})

    click.echo(f'Adding {owner} to local owners')
    local_owners = obj.client.config.get('local-owners')
    obj.client.config.update_and_save({'local-owners': [*local_owners, owner]})


@user_.command('list', short_help='list users', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known users.
    """

    default_user = obj.client.config.get('@default')
    default_owner = obj.client.config.get('@default-owner')
    default_override = (default_user != obj.client.config.get('@default', use_override=False))

    for user in obj.client.load_all(WildlandObject.Type.USER):
        path_string = str(user.local_path)
        if user.owner == default_user:
            path_string += ' (@default)'
            if default_override:
                path_string += ' (@default overriden by wl start parameters)'
        if user.owner == default_owner:
            path_string += ' (@default-owner)'
        click.echo(path_string)
        click.echo(f'  owner: {user.owner}')
        if obj.client.session.sig.is_private_key_available(user.owner):
            click.echo('  private and public keys available')
        else:
            click.echo('  only public key available')

        for user_path in user.paths:
            click.echo(f'   path: {user_path}')
        for user_container in user.get_catalog_descriptions():
            click.echo(f'   container: {user_container}')
        click.echo()


@user_.command('delete', short_help='delete a user', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if still has containers/storage')
@click.option('--cascade', is_flag=True,
              help='remove all containers and storage as well')
@click.option('--delete-keys', is_flag=True,
              help='also remove user keys')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade, delete_keys):
    """
    Delete a user.
    """

    user = obj.client.load_object_from_name(WildlandObject.Type.USER, name)

    if not user.local_path:
        raise WildlandError('Can only delete a local manifest')

    # Check if this is the only manifest with such owner
    other_count = 0
    for other_user in obj.client.load_all(WildlandObject.Type.USER):
        if other_user.local_path != user.local_path and other_user.owner == user.owner:
            other_count += 1

    used = False

    for container in obj.client.load_all(WildlandObject.Type.CONTAINER):
        assert container.local_path is not None
        if container.owner == user.owner:
            if cascade:
                click.echo('Deleting container: {}'.format(container.local_path))
                container.local_path.unlink()
            else:
                click.echo('Found container: {}'.format(container.local_path))
                used = True

    for storage in obj.client.load_all(WildlandObject.Type.STORAGE):
        assert storage.local_path is not None
        if storage.owner == user.owner:
            if cascade:
                click.echo('Deleting storage: {}'.format(storage.local_path))
                storage.local_path.unlink()
            else:
                click.echo('Found storage: {}'.format(storage.local_path))
                used = True

    if used and other_count > 0:
        click.echo('Found manifests for user, but this is not the only user '
                   'manifest. Proceeding.')
    elif used and other_count == 0 and not force:
        raise CliError('User still has manifests, not deleting '
                       '(use --force or --cascade)')

    if delete_keys:
        possible_owners = obj.session.sig.get_possible_owners(user.owner)

        if possible_owners != [user.owner] and not force:
            click.echo('Key used by other users as secondary key and will not be deleted. '
                       'Key should be removed manually. In the future you can use --force to force '
                       'key deletion.')
        else:
            click.echo(f'Removing key {user.owner}')
            obj.session.sig.remove_key(user.owner)

    for alias in ['@default', '@default-owner']:
        fingerprint = obj.client.config.get(alias)
        if fingerprint is not None:
            if fingerprint == user.owner:
                click.echo(f'Removing {alias} from configuration file')
                obj.client.config.remove_key_and_save(alias)

    local_owners = obj.client.config.get('local-owners')

    if local_owners is not None and user.owner in local_owners:
        local_owners.remove(user.owner)
        click.echo(f'Removing {user.owner} from local_owners')
        obj.client.config.update_and_save({'local-owners': local_owners})

    click.echo(f'Deleting: {user.local_path}')
    user.local_path.unlink()


def _remove_suffix(s: str, suffix: str) -> str:
    if suffix and s.endswith(suffix):
        return s[:-len(suffix)]
    return s


def _do_import_manifest(obj, path_or_dict, manifest_owner: Optional[str] = None,
                        force: bool = False) -> Tuple[Optional[Path], Optional[str]]:
    """
    Takes a manifest as pointed towards by path (can be local file path, url, wildland url),
    imports its public keys, copies the manifest itself.
    :param obj: ContextObj
    :param path: (potentially ambiguous) path to manifest to be imported
    :return: tuple of local path to copied manifest , url to manifest (local or remote, depending on
        input)
    """

    # TODO: Accepting paths (string) should be deprecated and force using link objects
    if isinstance(path_or_dict, dict):
        if path_or_dict.get('object', None) != WildlandObject.Type.LINK.value:
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
            file_url = obj.client.local_url(Path(path).absolute())
        else:
            try:
                file_data = obj.client.read_from_url(path, use_aliases=True)
            except FileNotFoundError as fnf:
                raise CliError('File was not found') from fnf

            file_name = _remove_suffix(path.split('/')[-1], '.yaml')
            file_url = path

    # load user pubkeys
    Manifest.verify_and_load_pubkeys(file_data, obj.session.sig)

    # determine type
    manifest = Manifest.from_bytes(file_data, obj.session.sig)
    import_type = WildlandObject.Type(manifest.fields['object'])

    if import_type not in [WildlandObject.Type.USER, WildlandObject.Type.BRIDGE]:
        raise CliError('Can import only user or bridge manifests')

    file_name = _remove_suffix(file_name, '.' + import_type.value)

    # do not import existing users, unless forced
    if import_type == WildlandObject.Type.USER:
        imported_user = WildlandObject.from_manifest(manifest, obj.client, WildlandObject.Type.USER,
                                                     pubkey=manifest.fields['pubkeys'][0])
        for user in obj.client.load_all(WildlandObject.Type.USER):
            if user.owner == imported_user.owner:
                if not force:
                    click.echo(f'User {user.owner} already exists. Skipping import.')
                    return None, None

                click.echo(f'User {user.owner} already exists. Forcing user import.')
                file_name = Path(user.local_path).name.rsplit('.', 2)[0]

    # copying the user manifest
    destination = obj.client.new_path(import_type, file_name, skip_numeric_suffix=force)
    destination.write_bytes(file_data)
    click.echo(f'Created: {str(destination)}')

    return destination, file_url


def find_user_manifest_within_catalog(obj, user: User) -> \
        Optional[Tuple[Storage, PurePosixPath]]:
    """
    Mounts containers of the given user's manifests-catalog and attempts to find that user's
    manifest file within that catalog.
    The user manifest file is expected to be named 'forest-owner.yaml' and be placed in the root
    directory of a storage.

    :param obj: ContextObj
    :param user: User
    :return tuple of Storage where the user manifest was found and PurePosixPath path pointing
    at that manifest in the storage

    """
    for container in user.load_catalog():
        all_storages = obj.client.all_storages(container=container)

        for storage_candidate in all_storages:
            with StorageDriver.from_storage(storage_candidate) as driver:
                try:
                    file_candidate = PurePosixPath('forest-owner.yaml')
                    file_content = driver.read_file(file_candidate)

                    # Ensure you're able to load this object
                    obj.client.load_object_from_bytes(
                        WildlandObject.Type.USER, file_content, expected_owner=user.owner)

                    return storage_candidate, file_candidate

                except WildlandError as ex:
                    logger.debug('Could not read user manifest. Exception: %s', ex)

    return None


def _sanitize_imported_paths(paths: List[PurePosixPath], owner: str) -> List[PurePosixPath]:
    """
    Accept a list of imported paths (either from a user or a bridge manifest) and return only
    the first one with sanitised (safe) path.
    """
    if not paths:
        raise CliError('No paths found to sanitize')

    path = paths[0]

    if path.is_relative_to('/'):
        path = path.relative_to('/')

    safe_path = f'/forests/{owner}-' + '_'.join(path.parts)

    return [PurePosixPath(safe_path)]


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

        bridge = Bridge(
            owner=default_user,
            user_location=user_location,
            user_pubkey=user.primary_pubkey,
            user_id=obj.client.session.sig.fingerprint(user.primary_pubkey),
            paths=(paths if paths else _sanitize_imported_paths(user.paths, user.owner)),
            client=obj.client
        )

        name = _remove_suffix(copied_manifest_path.stem, ".user")
        bridge_path = obj.client.save_new_object(WildlandObject.Type.BRIDGE, bridge, name, None)
        click.echo(f'Created: {bridge_path}')
    else:
        bridge = WildlandObject.from_manifest(manifest, obj.client, WildlandObject.Type.BRIDGE)

        original_bridge_owner = bridge.owner

        # adjust imported bridge
        if default_user:
            bridge.owner = default_user

        if paths:
            bridge.paths = list(paths)
        else:
            bridge.paths = _sanitize_imported_paths(bridge.paths, original_bridge_owner)

        copied_manifest_path.write_bytes(obj.session.dump_object(bridge))
        _do_import_manifest(obj, bridge.user_location, bridge.owner)


def import_manifest(obj: ContextObj, path_or_url, paths, wl_obj_type, bridge_owner, only_first):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --paths.
    Separate function so that it can be used by both wl bridge and wl user
    """
    if bridge_owner:
        default_user = obj.client.load_object_from_name(
            WildlandObject.Type.USER, bridge_owner).owner
    else:
        default_user = obj.client.config.get('@default-owner')

    if not default_user:
        raise CliError('Cannot import user or bridge without a --bridge-owner or a default user.')

    if wl_obj_type == WildlandObject.Type.USER:
        copied_manifest_path, manifest_url = _do_import_manifest(obj, path_or_url)
        if not copied_manifest_path or not manifest_url:
            return
        try:
            _do_process_imported_manifest(
                obj, copied_manifest_path, manifest_url,
                [PurePosixPath(p) for p in paths], default_user)
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
                new_bridge = Bridge(
                    owner=default_user,
                    user_location=deepcopy(bridge.user_location),
                    user_pubkey=bridge.user_pubkey,
                    user_id=obj.client.session.sig.fingerprint(bridge.user_pubkey),
                    paths=(paths or _sanitize_imported_paths(bridge.paths, bridge.owner)),
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
@click.option('--only-first', is_flag=True, default=False,
              help="import only first encountered bridge "
                   "(ignored in all cases except WL container paths)")
@click.argument('path-or-url')
def user_import(obj: ContextObj, path_or_url, paths, bridge_owner, only_first):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --paths.
    Created bridge manifests will use system @default-owner, or --bridge-owner is specified.
    """
    # TODO: remove imported keys and manifests on failure: requires some thought about how to
    # collect information on (potentially) multiple objects created

    import_manifest(obj, path_or_url, paths, WildlandObject.Type.USER, bridge_owner, only_first)


@user_.command('refresh', short_help='Iterate over bridges and pull latest user manifests',
               alias=['r'])
@click.pass_obj
@click.argument('name', metavar='USER', required=False)
def user_refresh(obj: ContextObj, name):
    """
    Iterates over bridges and fetches each user's file from the URL specified in the bridge
    """
    if name:
        user_list = [obj.client.load_object_from_name(WildlandObject.Type.USER, name)]
    else:
        user_list = obj.client.load_all(WildlandObject.Type.USER)

    refresh_users(obj, user_list)


def refresh_users(obj: ContextObj, user_list: Optional[List[User]] = None):
    """
    Refresh user manifests. Users can come from user_list parameter, or, if empty, all users
    referred to by local bridges will be refreshed.
    """
    user_fingerprints = [user.owner for user in user_list] if user_list is not None else None

    users_to_refresh: Dict[str, Union[dict, str]] = dict()
    for bridge in obj.client.load_all(WildlandObject.Type.BRIDGE):
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
            click.echo(f"Error while refreshing bridge: {ex}")


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
user_.add_command(dump)


@user_.group(short_help='modify user manifest')
def modify():
    """
    Commands for modifying user manifests.
    """


@modify.command(short_help='add path to the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to add')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_path(ctx: click.Context, input_file, path):
    """
    Add path to the manifest.
    """
    modify_manifest(ctx, input_file, add_field, 'paths', path)


@modify.command(short_help='remove path from the manifest')
@click.option('--path', metavar='PATH', required=True, multiple=True, help='Path to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_path(ctx: click.Context, input_file, path):
    """
    Remove path from the manifest.
    """
    modify_manifest(ctx, input_file, del_field, 'paths', path)


@modify.command(short_help='add entry to manifests-catalog')
@click.option('--path', metavar='PATH', required=True, multiple=True,
              help='Container path to add')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_catalog_entry(ctx: click.Context, input_file, path):
    """
    Add path to the manifest.
    """
    modify_manifest(ctx, input_file, add_field, 'manifests-catalog', path)


@modify.command(short_help="remove an entry from manifest's manifest catalog")
@click.option('--path', metavar='PATH', required=True, multiple=True,
              help='Container path to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_catalog_entry(ctx: click.Context, input_file, path):
    """
    Add path to the manifest.
    """
    modify_manifest(ctx, input_file, del_field, 'manifests-catalog', path)


@modify.command(short_help='add public key(s) to the manifest')
@click.option('--pubkey', metavar='PUBKEY', required=False, multiple=True,
              help='Raw public keys to append')
@click.option('--user', metavar='USER', required=False, multiple=True,
              help='Users whose public keys should be appended to FILE')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_pubkey(ctx: click.Context, input_file, pubkey, user):
    """
    Add public key to the manifest.
    """
    if not pubkey and not user:
        raise CliError('You must provide at least one --user or --pubkey.')

    pubkeys = set(pubkey)

    for name in user:
        user_obj = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, name)

        click.echo(f'Pubkeys found in [{name}]:')

        for key in user_obj.pubkeys:
            click.echo(f'  {key}')

        pubkeys.update(user_obj.pubkeys)

    for key in pubkeys:
        if not ctx.obj.session.sig.is_valid_pubkey(key):
            raise CliError(f'Given pubkey [{key}] is not a valid pubkey')

    modify_manifest(ctx, input_file, add_field, 'pubkeys', pubkeys)


@modify.command(short_help='remove public key from the manifest')
@click.option('--pubkey', metavar='PUBKEY', required=True, multiple=True,
              help='Public key to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_pubkey(ctx: click.Context, input_file, pubkey):
    """
    Remove public key from the manifest.
    """
    modify_manifest(ctx, input_file, del_field, 'pubkeys', pubkey)
