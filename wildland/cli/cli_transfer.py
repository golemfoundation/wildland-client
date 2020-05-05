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
Transfer commands (get, put)
'''

import sys

import click

from .. import resolve

@click.command(short_help='send a file')
@click.argument('local_path', required=False)
@click.argument('wlpath')
@click.pass_context
def put(ctx, local_path, wlpath):
    '''
    Put a file under Wildland path. Reads from stdout or from a file.
    '''

    wlpath = resolve.WildlandPath.from_str(wlpath)
    ctx.obj.loader.load_users()
    default_user = ctx.obj.loader.find_default_user()

    if local_path:
        with open(local_path, 'rb') as f:
            data = f.read()
    else:
        data = sys.stdin.buffer.read()

    resolve.write_file(
        data, ctx.obj.loader, wlpath,
        default_user.signer if default_user else None)


@click.command(short_help='download a file')
@click.argument('wlpath')
@click.argument('local_path', required=False)
@click.pass_context
def get(ctx, wlpath, local_path):
    '''
    Get a file, given its Wildland path. Saves to stdout or to a file.
    '''

    wlpath = resolve.WildlandPath.from_str(wlpath)
    ctx.obj.loader.load_users()
    default_user = ctx.obj.loader.find_default_user()

    data = resolve.read_file(
        ctx.obj.loader, wlpath,
        default_user.signer if default_user else None)
    if local_path:
        with open(local_path, 'wb') as f:
            f.write(data)
    else:
        sys.stdout.buffer.write(data)
