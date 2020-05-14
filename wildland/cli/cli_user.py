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

import click

from ..manifest.user import User

from .cli_base import ContextObj
from .cli_common import sign, verify, edit

@click.group('user', short_help='user management')
def user_():
    '''
    Manage users
    '''


@user_.command(short_help='create user')
@click.option('--key', required=True,
    help='GPG key identifier')
@click.option('--path', 'paths', multiple=True,
    help='path (can be repeated)')
@click.argument('name', metavar='NAME', required=False)
@click.pass_obj
def create(obj: ContextObj, key, paths, name):
    '''
    Create a new user manifest and save it. You need to have a GPG private key
    in your keyring.
    '''

    signer, pubkey = obj.loader.sig.find(key)
    print(f'Using key: {signer}')

    if paths:
        paths = list(paths)
    else:
        if name:
            paths = [f'/users/{name}']
        else:
            paths = [f'/users/{signer}']
        click.echo(f'No path specified, using: {paths[0]}')

    path = obj.loader.create_user(signer, pubkey, paths, name)
    click.echo(f'Created: {path}')

    if obj.loader.config.get('default_user') is None:
        print(f'Using {signer} as default user')
        obj.loader.config.update_and_save(default_user=signer)


@user_.command('list', short_help='list users')
@click.pass_obj
def list_(obj: ContextObj):
    '''
    Display known users.
    '''

    obj.loader.load_users()
    for path, manifest in obj.loader.load_manifests('user'):
        user = User(manifest)
        click.echo(path)
        click.echo(f'  signer: {user.signer}')
        for user_path in user.paths:
            click.echo(f'  path: {user_path}')
        for user_container in user.containers:
            click.echo(f'  container: {user_container}')
        click.echo()


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
