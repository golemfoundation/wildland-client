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
Transfer commands (get, put)
"""

import click

from .cli_base import ContextObj
from ..wlpath import WildlandPath, PathError
from ..search import Search


@click.command(short_help='send a file')
@click.argument('local_file', type=click.File('rb'), default='-')
@click.argument('wlpath')
@click.pass_obj
def put(obj: ContextObj, local_file, wlpath):
    """
    Put a file under Wildland path. Reads from stdout or from a file.
    """

    try:
        wlpath = WildlandPath.from_str(wlpath)
    except PathError as ex:
        click.echo(f"Path error: {ex}")
        return
    data = local_file.read()
    search = Search(obj.client, wlpath, obj.client.config.aliases)
    try:
        search.write_file(data)
    except PathError as ex:
        click.echo(f'Error: {ex}')


@click.command(short_help='download a file')
@click.argument('wlpath')
@click.argument('local_file', type=click.File('wb'), default='-')
@click.pass_obj
def get(obj: ContextObj, wlpath, local_file):
    """
    Get a file, given its Wildland path. Saves to stdout or to a file.
    """

    try:
        wlpath = WildlandPath.from_str(wlpath)
    except PathError as ex:
        click.echo(f"Path error: {ex}")
        return
    search = Search(obj.client, wlpath, obj.client.config.aliases)
    data = search.read_file()
    try:
        local_file.write(data)
    except PathError as ex:
        click.echo(f'Error: {ex}')
