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

from .cli_base import AliasedGroup, ContextObj
from .cli_common import sign, verify, edit

@click.group('user', short_help='user management', cls=AliasedGroup)
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

    if obj.client.config.get('default_user') is None:
        print(f'Using {signer} as default user')
        obj.client.config.update_and_save(default_user=signer)

    print(f'Adding {signer} to local signers')
    local_signers = obj.client.config.get('local_signers')
    obj.client.config.update_and_save(local_signers=[*local_signers, signer])


@user_.command('list', short_help='list users')
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
user_.add_alias(ls='list')


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
