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
Manage bridges
'''

from pathlib import PurePosixPath, Path
from typing import List

import click

from ..bridge import Bridge
from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import sign, verify, edit


@aliased_group('bridge', short_help='bridge management')
def bridge_():
    '''
    Manage bridges
    '''


@bridge_.command(short_help='create bridge')
@click.option('--user', 'user_name', help='user for signing')
@click.option('--ref-user', 'ref_user_name', metavar='USER',
              required=True,
              help='user to refer to')
@click.option('--ref-user-location', metavar='URL-OR-PATH',
              required=True,
              help='path to user manifest (URL or relative path)')
@click.option('--ref-user-path', 'ref_user_paths', multiple=True,
              help='paths for user in Wildland namespace (omit to take from user manifest)')
@click.argument('file_path', metavar='FILE', required=True)
@click.pass_obj
def create(obj: ContextObj,
           user_name: str,
           ref_user_name: str,
           ref_user_location: str,
           ref_user_paths: List[str],
           file_path: str):
    '''
    Create a new bridge manifest under a given path.
    '''

    obj.client.recognize_users()
    user = obj.client.load_user_from(user_name or '@default-signer')

    # Ensure the path is relative and starts with './' or '../'.
    if not obj.client.is_url(ref_user_location):
        if ref_user_location.startswith('/'):
            raise CliError('URL should be relative: {ref_user_location')
        if not (ref_user_location.startswith('./') or
                ref_user_location.startswith('../')):
            ref_user_location = './' + ref_user_location

    ref_user = obj.client.load_user_from(ref_user_name)
    if ref_user_paths:
        paths = [PurePosixPath(p) for p in ref_user_paths]
    else:
        click.echo(
            "Using user's default paths: {}".format([str(p) for p in ref_user.paths]))
        paths = list(ref_user.paths)

    bridge = Bridge(
        signer=user.signer,
        user_location=ref_user_location,
        user_pubkey=ref_user.pubkey,
        paths=paths,
    )
    path = obj.client.save_new_bridge(bridge, Path(file_path))
    click.echo(f'Created: {path}')


bridge_.add_command(sign)
bridge_.add_command(verify)
bridge_.add_command(edit)
