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
import click

from ..user import User

from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit

@aliased_group('user', short_help='user management')
def user_():
    '''
    Manage users
    '''


@user_.command(short_help='create user')
@click.option('--key', metavar='KEY',
    help='use existing key pair (must be in ~/.config/wildland/keys/')
@click.option('--path', 'paths', multiple=True,
    help='path (can be repeated)')
@click.argument('name', metavar='NAME', required=False)
@click.pass_obj
def create(obj: ContextObj, key, paths, name):
    '''
    Create a new user manifest and save it.
    '''

    if key:
        signer, pubkey = obj.session.sig.find(key)
        print(f'Using key: {signer}')
    else:
        signer, pubkey = obj.session.sig.generate()
        print(f'Generated key: {signer}')

    if paths:
        paths = list(paths)
    else:
        if name:
            paths = [f'/users/{name}']
        else:
            paths = [f'/users/{signer}']
        click.echo(f'No path specified, using: {paths[0]}')

    user = User(
        signer=signer,
        pubkey=pubkey,
        paths=[PurePosixPath(p) for p in paths],
        containers=[],
    )
    path = obj.client.save_new_user(user, name)
    click.echo(f'Created: {path}')

    for alias in ['@default', '@default-signer']:
        if obj.client.config.get(alias) is None:
            print(f'Using {signer} as {alias}')
            obj.client.config.update_and_save({alias: signer})

    print(f'Adding {signer} to local signers')
    local_signers = obj.client.config.get('local-signers')
    obj.client.config.update_and_save({'local-signers': [*local_signers, signer]})


@user_.command('list', short_help='list users', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known users.
    '''

    for user in obj.client.load_users():
        click.echo(user.local_path)
        click.echo(f'  signer: {user.signer}')
        for user_path in user.paths:
            click.echo(f'  path: {user_path}')
        for user_container in user.containers:
            click.echo(f'  container: {user_container}')
        click.echo()


@user_.command('delete', short_help='delete a user', alias=['rm'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if still has containers/storage')
@click.option('--cascade', is_flag=True,
              help='remove all containers and storage as well')
@click.argument('name', metavar='NAME')
def delete(obj: ContextObj, name, force, cascade):
    '''
    Delete a user.
    '''
    # TODO consider also deleting keys (~/.config/wildland/keys)
    # TODO check config file (aliases, etc.)

    obj.client.recognize_users()

    user = obj.client.load_user_from(name)
    if not user.local_path:
        raise CliError('Can only delete a local manifest')

    # Check if this is the only manifest with such signer
    other_count = 0
    for other_user in obj.client.load_users():
        if (other_user.local_path != user.local_path and
            other_user.signer == user.signer):
            other_count += 1

    used = False

    for container in obj.client.load_containers():
        assert container.local_path is not None
        if container.signer == user.signer:
            if cascade:
                click.echo('Deleting container: {}'.format(container.local_path))
                container.local_path.unlink()
            else:
                click.echo('Found container: {}'.format(container.local_path))
                used = True

    for storage in obj.client.load_storages():
        assert storage.local_path is not None
        if storage.signer == user.signer:
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

    click.echo(f'Deleting: {user.local_path}')
    user.local_path.unlink()


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
