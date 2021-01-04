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

from pathlib import PurePosixPath
import binascii
import click

from ..user import User

from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit
from ..manifest.schema import SchemaError
from ..manifest.sig import SigError
from ..manifest.manifest import ManifestError


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
        # raised by SignifySigContext._fingerprint
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

    for user in users:
        path_string = str(user.local_path)
        for alias in ['@default', '@default-owner']:
            if user.owner == obj.client.config.get(alias):
                path_string += f' ({alias})'
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
    # TODO check config file (aliases, etc.)

    obj.client.recognize_users()

    try:
        user = obj.client.load_user_from(name)
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

    click.echo(f'Deleting: {user.local_path}')
    user.local_path.unlink()


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
