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

from .common import sign, verify, edit


@click.group(short_help='user management')
def user():
    '''
    Manage users
    '''


@user.command(short_help='create user')
@click.option('--key', required=True,
    help='GPG key identifier')
@click.argument('name', metavar='NAME', required=False)
@click.pass_context
def create(ctx, key, name):
    '''
    Create a new user manifest and save it. You need to have a GPG private key
    in your keyring.
    '''

    signer, pubkey = ctx.obj.loader.sig.find(key)
    print(f'Using key: {signer}')

    path = ctx.obj.loader.create_user(signer, pubkey, name)
    print(f'Created: {path}')

    if ctx.obj.loader.config.get('default_user') is None:
        print(f'Using {signer} as default user')
        ctx.obj.loader.config.update_and_save(default_user=signer)


@user.command('list', short_help='list users')
@click.pass_context
def list_(ctx):
    '''
    Display known users.
    '''

    ctx.obj.loader.load_users()
    for u in ctx.obj.loader.users:
        print(f'{u.signer} {u.manifest_path}')


user.add_command(sign)
user.add_command(verify)
user.add_command(edit)
