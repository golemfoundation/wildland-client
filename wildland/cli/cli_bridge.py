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
Manage bridges
"""

from typing import List, Optional
from pathlib import Path

import click

from wildland.cleaner import get_cli_cleaner
from .cli_base import aliased_group, ContextObj
from .cli_common import sign, verify, edit, dump, publish, unpublish
from .cli_exc import CliError
from ..log import get_logger
from ..core.wildland_objects_api import WLObjectType


logger = get_logger('cli-bridge')
cleaner = get_cli_cleaner()


@aliased_group('bridge', short_help='bridge management')
def bridge_():
    """
    Manage bridges
    """


@bridge_.command(short_help='create bridge')
@click.option('--owner', 'owner', help='User used to sign the bridge')
@click.option('--target-user', 'target_user_name', metavar='USER',
              help='User to whom the bridge will point. If provided, will be used to verify the '
                   'integrity of the --target-user-location. If omitted, --target-user-location'
                   'will be used to locate user manifest.')
@click.option('--target-user-location', metavar='URL',
              help='Path to the user manifest (use file:// for local file). If --target-user is '
                   'skipped, the user manifest from this path is considered trusted. If omitted, '
                   'the user manifest will be located in their manifests catalog.')
@click.option('--path', 'user_paths', multiple=True,
              help='path(s) for user in owner namespace (omit to take from user manifest)')
@click.argument('name', metavar='BRIDGE_NAME', required=False)
@click.pass_obj
def create(obj: ContextObj,
           owner: str,
           target_user_name: str,
           target_user_location: str,
           user_paths: List[str],
           name: Optional[str]):
    """
    Create a new bridge manifest. Clean up created files if fails.
    """
    try:
        _bridge_create(obj, owner, target_user_name, target_user_location,
                       user_paths, name)
    except Exception as ex:
        click.secho('Creation failed.', fg='red')
        cleaner.clean_up()
        raise ex


def _bridge_create(obj: ContextObj,
                  owner: str,
                  target_user_name: str,
                  target_user_location: str,
                  user_paths: List[str],
                  name: Optional[str]):
    """
    Create a new bridge manifest.
    """

    owner_id = None

    if owner:
        result, owner_obj = obj.wlcore.object_get(WLObjectType.USER, owner)
        if owner_obj:
            owner_id = owner_obj.owner
        else:
            raise CliError(f'User {owner} not found: {result}')

    target_user_id = None
    if target_user_name:
        result, target_user_obj = obj.wlcore.object_get(WLObjectType.USER, target_user_name)
        if target_user_obj:
            target_user_id = target_user_obj.owner
        else:
            raise CliError(f'Target user {target_user_name} not found')

    result, _ = obj.wlcore.bridge_create(paths=user_paths, owner=owner_id,
                                              target_user=target_user_id,
                                              user_url=target_user_location,
                                              name=name)

    if not result.success:
        raise CliError(f'Failed to create bridge: {result}')


@bridge_.command('list', short_help='list bridges', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known bridges.
    """

    result_bridges, bridges = obj.wlcore.bridge_list()
    if result_bridges.failure:
        click.echo('Failed to list bridges:')
        for e in result_bridges.errors:
            click.echo(f'Error {e.error_code}: {e.error_description}')

    for bridge in bridges:
        _, path = obj.wlcore.object_get_local_path(WLObjectType.BRIDGE, bridge.id)
        click.echo(path)
        result, user = obj.wlcore.object_get(WLObjectType.USER, bridge.owner)
        if result.failure or not user:
            raise CliError(f'User {bridge.owner} cannot be loaded: {result}')

        user_paths = user.paths  # type: ignore[attr-defined]
        if user_paths:
            user_desc = ' (' + ', '.join([str(p) for p in user_paths]) + ')'
        else:
            user_desc = ''

        click.echo(f'  owner: {bridge.owner}' + user_desc)
        click.echo('  paths: ' + ', '.join([str(p) for p in bridge.paths]))
        click.echo()


@bridge_.command('import', short_help='import bridge or user manifest', alias=['im'])
@click.pass_obj
@click.option('--path', 'paths', multiple=True,
              help='path for resulting bridge manifest (can be repeated); if omitted, will'
                   ' use user\'s paths')
@click.option('--bridge-owner', help="specify a different (then default) user to be used as the "
                                     "owner of created bridge manifests")
@click.option('--only-first', is_flag=True, default=False,
              help="import only first encountered bridge "
                   "(ignored in all cases except WL container paths)")
@click.argument('path-or-url')
def bridge_import(obj: ContextObj, path_or_url, paths, bridge_owner, only_first):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --path.
    Created bridge manifests will use system @default-owner, or --bridge-owner is specified.
    """
    try:
        do_bridge_import(obj.wlcore, path_or_url, paths, bridge_owner, only_first)
    except Exception as ex:
        click.secho('Creation failed.', fg='red')
        cleaner.clean_up()
        raise ex


def do_bridge_import(wlcore, path_or_url, paths, bridge_owner, only_first):
    """
    Perform bridge import. Separated into a function to avoid Click weirdness on import to cli_user.
    """
    p = Path(path_or_url)
    name = path_or_url
    name = name.split('/')[-1]

    if not bridge_owner:
        _, default_owner = wlcore.env.get_default_owner()
        if default_owner:
            bridge_owner = default_owner
        else:
            raise CliError('Cannot import a bridge without @default-owner or --bridge-owner.')

    if p.exists():
        yaml_data = p.read_bytes()
        name = p.name
        result, imported_bridge = wlcore.bridge_import_from_yaml(yaml_data, paths, bridge_owner,
                                                                 name)
        if not imported_bridge:
            raise CliError(f'Failed to import bridges: {result}')

        users = [f'{imported_bridge.user_id}:']
    else:
        result, imported_bridges = wlcore.bridge_import_from_url(path_or_url, paths,
                                                                 bridge_owner, only_first, name)
        users = [f'{bridge.user_id}:' for bridge in imported_bridges]
        if not result.success:
            raise CliError(f'Failed to import bridges: {result}')

    result = wlcore.user_refresh(users)
    if not result.success:
        raise CliError(f'Failed to import bridges: {result}')


bridge_.add_command(sign)
bridge_.add_command(verify)
bridge_.add_command(edit)
bridge_.add_command(dump)
bridge_.add_command(publish)
bridge_.add_command(unpublish)
