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

'''
Manage users
'''

from typing import Tuple, Iterable, Optional
from pathlib import PurePosixPath, Path
import binascii
import click

from ..user import User

from .cli_base import aliased_group, ContextObj, CliError
from ..client import WILDLAND_URL_PREFIX
from ..bridge import Bridge
from .cli_common import sign, verify, edit, modify_manifest, add_field, del_field, dump
from ..exc import WildlandError
from ..manifest.schema import SchemaError
from ..manifest.sig import SigError
from ..manifest.manifest import ManifestError, Manifest


@aliased_group('user', short_help='user management')
def user_():
    '''
    Manage users
    '''


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
    '''
    Create a new user manifest and save it.
    '''

    if key:
        try:
            owner, pubkey = obj.session.sig.load_key(key)
        except SigError as ex:
            click.echo(f'Failed to use provided key: {ex}')
            return
        print(f'Using key: {owner}')
    else:
        owner, pubkey = obj.session.sig.generate()
        print(f'Generated key: {owner}')

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
        containers=[],
    )
    try:
        error_on_save = False
        path = obj.client.save_new_user(user, name)
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
            print(f'Using {owner} as {alias}')
            obj.client.config.update_and_save({alias: owner})

    print(f'Adding {owner} to local owners')
    local_owners = obj.client.config.get('local-owners')
    obj.client.config.update_and_save({'local-owners': [*local_owners, owner]})


@user_.command('list', short_help='list users', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known users.
    '''

    obj.client.recognize_users()
    users = obj.client.load_users()

    default_user = obj.client.config.get('@default')
    default_owner = obj.client.config.get('@default-owner')
    default_override = (default_user != obj.client.config.get('@default', use_override=False))

    for user in users:
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
        for user_container in user.containers:
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
    '''
    Delete a user.
    '''

    obj.client.recognize_users()

    try:
        user = obj.client.load_user_by_name(name)
    except ManifestError:
        click.echo(f'User not found: {name}')
        return

    if not user.local_path:
        raise CliError('Can only delete a local manifest')

    # Check if this is the only manifest with such owner
    other_count = 0
    for other_user in obj.client.load_users():
        if other_user.local_path != user.local_path and other_user.owner == user.owner:
            other_count += 1

    used = False

    for container in obj.client.load_containers():
        assert container.local_path is not None
        if container.owner == user.owner:
            if cascade:
                click.echo('Deleting container: {}'.format(container.local_path))
                container.local_path.unlink()
            else:
                click.echo('Found container: {}'.format(container.local_path))
                used = True

    for storage in obj.client.load_storages():
        assert storage.local_path is not None
        if storage.owner == user.owner:
            if cascade:
                click.echo('Deleting storage: {}'.format(storage.local_path))
                storage.local_path.unlink()
            else:
                click.echo('Found storage: {}'.format(storage.local_path))
                used = True

    if used and other_count > 0:
        click.echo(
            'Found manifests for user, but this is not the only user '
            'manifest. Proceeding.')
    elif used and other_count == 0 and not force:
        raise CliError('User still has manifests, not deleting '
                       '(use --force or --cascade)')

    if delete_keys:
        possible_owners = obj.session.sig.get_possible_owners(user.owner)

        if possible_owners != [user.owner] and not force:
            print('Key used by other users as secondary key and will not be deleted. '
                  'Key should be removed manually. In the future you can use --force to force '
                  'key deletion.')
        else:
            print("Removing key", user.owner)
            obj.session.sig.remove_key(user.owner)

    for alias in ['@default', '@default-owner']:
        fingerprint = obj.client.config.get(alias)
        if fingerprint is not None:
            if fingerprint == user.owner:
                print(f'Removing {alias} from configuration file')
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


def _do_import_manifest(obj, path, force: bool = False) -> Tuple[Optional[Path], Optional[str]]:
    """
    Takes a manifest as pointed towards by path (can be local file path, url, wildland url),
    imports its public keys, copies the manifest itself.
    :param obj: ContextObj
    :param path: (potentially ambiguous) path to manifest to be imported
    :return: tuple of local path to copied manifest , url to manifest (local or remote, depending on
        input)
    """
    if Path(path).exists():
        file_data = Path(path).read_bytes()
        file_name = Path(path).stem
        file_url = obj.client.local_url(Path(path).absolute())
    else:
        try:
            file_data = obj.client.read_from_url(path, obj.client.config.get('@default'),
                                                 use_aliases=True)
            file_name = _remove_suffix(path.split('/')[-1], '.yaml')
            file_url = path
        except WildlandError as ex:
            raise CliError(str(ex)) from ex

    # load user pubkeys
    Manifest.load_pubkeys(file_data, obj.session.sig)

    # determine type
    manifest = Manifest.from_bytes(file_data, obj.session.sig)
    import_type = manifest.fields['object']

    if import_type not in ['user', 'bridge']:
        raise CliError('Can import only user or bridge manifests')

    file_name = _remove_suffix(file_name, '.' + import_type)

    # do not import existing users, unless forced
    if import_type == 'user':
        imported_user = User.from_manifest(manifest, manifest.fields['pubkeys'][0])
        for user in obj.client.load_users():
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


def _do_process_imported_manifest(
        obj: ContextObj, copied_manifest_path: Path, manifest_url: str,
        paths: Iterable[str], default_user: str):
    """
    Perform followup actions after importing a manifest: create a Bridge manifest for a user,
    import a Bridge manifest's target user
    :param obj: ContextObj
    :param copied_manifest_path: Path to where the manifest was copied
    :param manifest_url: url to manifest (local or remote, depending on input)
    :param paths: list of paths to use in created Bridge manifest
    :param default_user: owner of the manifests to be created
    """
    manifest = Manifest.from_file(copied_manifest_path, obj.session.sig)

    if manifest.fields['object'] == 'user':
        user = User.from_manifest(manifest, manifest.fields['pubkeys'][0])

        if not paths:
            new_paths = user.paths
        else:
            new_paths = [PurePosixPath(p) for p in paths]

        bridge = Bridge(
            owner=default_user,
            user_location=manifest_url,
            user_pubkey=user.primary_pubkey,
            paths=new_paths,
        )

        name = _remove_suffix(copied_manifest_path.stem, ".user")
        bridge_path = obj.client.save_new_bridge(bridge, name, None)
        click.echo(f'Created: {bridge_path}')
    else:
        bridge = Bridge.from_manifest(manifest)
        # adjust imported bridge
        if paths:
            bridge.paths = paths
        if default_user:
            bridge.owner = default_user
        copied_manifest_path.write_bytes(obj.session.dump_object(bridge))
        _do_import_manifest(obj, bridge.user_location)


def import_manifest(obj: ContextObj, name, paths, bridge_owner, only_first):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --paths.
    Separate function so that it can be used by both wl bridge and wl user
    """
    if bridge_owner:
        try:
            default_user = obj.client.load_user_by_name(bridge_owner).owner
        except WildlandError as ex:
            raise CliError(f'Cannot load bridge-owner {bridge_owner}') from ex
    else:
        default_user = obj.client.config.get('@default-owner')

    if not default_user:
        raise CliError('Cannot import user or bridge without a --bridge-owner or a default user.')

    if Path(name).exists() or obj.client.is_url_file_path(name):
        # try to import manifest file
        copied_manifest_path, manifest_url = _do_import_manifest(obj, name)
        if not copied_manifest_path or not manifest_url:
            return
        try:
            _do_process_imported_manifest(obj, copied_manifest_path, manifest_url,
                                          paths, default_user)
        except Exception as ex:
            click.echo(
                f'Import error occurred. Removing created files: {str(copied_manifest_path)}')
            copied_manifest_path.unlink()
            raise CliError(f'Failed to import: {str(ex)}') from ex
    else:
        # this didn't work out, perhaps we have an url to a bunch of bridges?
        try:
            bridges = list(obj.client.read_bridge_from_url(name, use_aliases=True))
            if not bridges:
                raise CliError('No bridges found.')
            if only_first:
                bridges = [bridges[0]]
            if len(bridges) > 1 and paths:
                raise CliError('Cannot import multiple bridges with --path override.')
        except WildlandError as wl_ex:
            raise CliError(f'Failed to import manifest: {str(wl_ex)}') from wl_ex

        copied_files = []
        try:
            for bridge in bridges:
                new_bridge = Bridge(
                    owner=default_user,
                    user_location=bridge.user_location,
                    user_pubkey=bridge.user_pubkey,
                    paths=paths or bridge.paths,
                )
                bridge_name = name[len(WILDLAND_URL_PREFIX):]
                bridge_name = bridge_name.replace(':', '_').replace('/', '_')
                bridge_path = obj.client.save_new_bridge(new_bridge, bridge_name, None)
                click.echo(f'Created: {bridge_path}')
                copied_files.append(bridge_path)
                _do_import_manifest(obj, bridge.user_location)
        except Exception as ex:
            for file in copied_files:
                click.echo(
                    f'Import error occurred. Removing created files: {str(file)}')
                file.unlink(missing_ok=True)
            raise CliError(f'Failed to import: {str(ex)}') from ex


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

    obj.client.recognize_users()

    import_manifest(obj, path_or_url, paths, bridge_owner, only_first)


@user_.command('refresh', short_help='Iterate over bridges and pull latest user manifests',
               alias=['r'])
@click.pass_obj
@click.argument('name', metavar='USER', required=False)
def user_refresh(obj: ContextObj, name):
    '''
    Iterates over bridges and fetches each user's file from the URL specified in the bridge
    '''
    obj.client.recognize_users()
    user = obj.client.load_user_by_name(name) if name else None

    for bridge in obj.client.load_bridges():
        if user and user.owner != obj.client.session.sig._fingerprint(bridge.user_pubkey):
            continue

        try:
            _do_import_manifest(obj, bridge.user_location, force=True)
        except WildlandError as ex:
            click.echo(f"Error while refreshing bridge: {ex}")


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
user_.add_command(dump)


@user_.group(short_help='modify user manifest')
def modify():
    '''
    Commands for modifying user manifests.
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


@modify.command(short_help='add public key to the manifest')
@click.option('--pubkey', metavar='PUBKEY', required=True, multiple=True, help='Public key to add')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def add_pubkey(ctx, input_file, pubkey):
    '''
    Add public key to the manifest.
    '''
    # TODO: validate values, schema is not enough
    modify_manifest(ctx, input_file, add_field, 'pubkeys', pubkey)


@modify.command(short_help='remove public key from the manifest')
@click.option('--pubkey', metavar='PUBKEY', required=True, multiple=True,
              help='Public key to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def del_pubkey(ctx, input_file, pubkey):
    '''
    Remove public key from the manifest.
    '''
    modify_manifest(ctx, input_file, del_field, 'pubkeys', pubkey)
