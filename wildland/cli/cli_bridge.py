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
from typing import List, Optional

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
@click.option('--owner', 'owner', help='User used to sign the bridge')
@click.option('--ref-user', 'ref_user_name', metavar='USER',
              help='Username to refer to. Use to verify the integrity of the --ref-user-location')
@click.option('--ref-user-location', metavar='URL',
              required=True,
              help='Path to the user manifest (use file:// for local file). If --ref-user is \
              skipped, the user from this path is considered trusted and imported into wildland \
              user store.')
@click.option('--ref-user-path', 'ref_user_paths', multiple=True,
              help='paths for user in Wildland namespace (omit to take from user manifest)')
@click.option('--file-path', help='file path to create under')
@click.argument('name', metavar='BRIDGE_NAME', required=False)
@click.pass_obj
def create(obj: ContextObj,
           owner: str,
           ref_user_name: str,
           ref_user_location: str,
           ref_user_paths: List[str],
           name: Optional[str],
           file_path: Optional[str]):
    '''
    Create a new bridge manifest.
    '''

    obj.client.recognize_users()

    owner_user = obj.client.load_user_by_name(owner or '@default-owner')

    if name is None and file_path is None:
        raise CliError('Either name or file path needs to be provided')

    if not obj.client.is_url(ref_user_location):
        raise CliError('Ref user location must be an URL')

    if ref_user_name:
        ref_user = obj.client.load_user_by_name(ref_user_name)
    else:
        ref_user = obj.client.load_user_from_url(ref_user_location, owner_user.owner,
                                                 allow_self_signed=True)

    if ref_user_paths:
        paths = [PurePosixPath(p) for p in ref_user_paths]
    else:
        click.echo(
            "Using user's default paths: {}".format([str(p) for p in ref_user.paths]))
        paths = list(ref_user.paths)

    bridge = Bridge(
        owner=owner_user.owner,
        user_location=ref_user_location,
        user_pubkey=ref_user.pubkeys[0],
        paths=paths,
    )
    path = obj.client.save_new_bridge(
        bridge, name, Path(file_path) if file_path else None)
    click.echo(f'Created: {path}')


bridge_.add_command(sign)
bridge_.add_command(verify)
bridge_.add_command(edit)
