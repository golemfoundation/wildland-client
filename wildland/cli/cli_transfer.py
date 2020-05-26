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

from .cli_base import ContextObj
from ..resolve import WildlandPath, Search


@click.command(short_help='send a file')
@click.argument('local_path', required=False)
@click.argument('wlpath')
@click.pass_obj
def put(obj: ContextObj, local_path, wlpath):
    '''
    Put a file under Wildland path. Reads from stdout or from a file.
    '''

    wlpath = WildlandPath.from_str(wlpath)
    obj.client.recognize_users()

    if local_path:
        with open(local_path, 'rb') as f:
            data = f.read()
    else:
        data = sys.stdin.buffer.read()

    search = Search(obj.client, wlpath)
    search.write_file(data)


@click.command(short_help='download a file')
@click.argument('wlpath')
@click.argument('local_path', required=False)
@click.pass_obj
def get(obj: ContextObj, wlpath, local_path):
    '''
    Get a file, given its Wildland path. Saves to stdout or to a file.
    '''

    wlpath = WildlandPath.from_str(wlpath)
    obj.client.recognize_users()

    search = Search(obj.client, wlpath)
    data = search.read_file()

    if local_path:
        with open(local_path, 'wb') as f:
            f.write(data)
    else:
        sys.stdout.buffer.write(data)
