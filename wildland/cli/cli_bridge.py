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

from pathlib import PurePosixPath, Path
from typing import List, Optional

import click

from wildland.wildland_object.wildland_object import WildlandObject
from wildland.bridge import Bridge
from wildland.link import Link
from ..manifest.manifest import ManifestError
from .cli_base import aliased_group, ContextObj
from .cli_common import sign, verify, edit, dump, publish, unpublish
from .cli_exc import CliError
from .cli_user import import_manifest, find_user_manifest_within_catalog
from ..log import get_logger

logger = get_logger('cli-bridge')


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
@click.option('--file-path', help='file path to create under')
@click.argument('name', metavar='BRIDGE_NAME', required=False)
@click.pass_obj
def create(obj: ContextObj,
           owner: str,
           target_user_name: str,
           target_user_location: str,
           user_paths: List[str],
           name: Optional[str],
           file_path: Optional[str]):
    """
    Create a new bridge manifest.
    """

    owner_user = obj.client.load_object_from_name(WildlandObject.Type.USER,
                                                  owner or '@default-owner')

    if not target_user_name and not target_user_location:
        raise CliError('At least one of --target-user and --target-user-location must be provided.')

    if target_user_location and not obj.client.is_url(target_user_location):
        raise CliError('Target user location must be an URL')

    if target_user_name:
        target_user = obj.client.load_object_from_name(WildlandObject.Type.USER, target_user_name)
    else:
        target_user = obj.client.load_object_from_url(
            WildlandObject.Type.USER, target_user_location, owner=owner_user.owner)

    if target_user_location:
        location = target_user_location
    else:
        found_manifest = find_user_manifest_within_catalog(obj, target_user)
        if not found_manifest:
            if target_user.local_path:
                logger.warning('Cannot find user manifest in manifests catalog. '
                               'Using local file path.')
                location = obj.client.local_url(target_user.local_path)
            else:
                raise CliError('User manifest not found in manifests catalog. '
                               'Provide --target-user-location.')
        else:
            storage, file = found_manifest
            file = '/' / file
            location_link = Link(file, client=obj.client, storage=storage)
            location = location_link.to_manifest_fields(inline=True)

    fingerprint = obj.client.session.sig.fingerprint(target_user.primary_pubkey)

    if user_paths:
        paths = [PurePosixPath(p) for p in user_paths]
    else:
        paths = target_user.paths

        click.echo("Using user's default paths: {}".format([str(p) for p in target_user.paths]))

    bridge = Bridge(
        owner=owner_user.owner,
        user_location=location,
        user_pubkey=target_user.primary_pubkey,
        user_id=fingerprint,
        paths=paths,
        client=obj.client
    )

    if not name or file_path:
        # an heuristic for nicer paths
        for path in paths:
            if 'uuid' not in str(path):
                name = str(path).lstrip('/').replace('/', '_')
                break

    path = obj.client.save_new_object(WildlandObject.Type.BRIDGE,
                                      bridge, name, Path(file_path) if file_path else None)
    click.echo(f'Created: {path}')


@bridge_.command('list', short_help='list bridges', alias=['ls'])
@click.pass_obj
def list_(obj: ContextObj):
    """
    Display known bridges.
    """

    for bridge in obj.client.get_local_bridges():
        click.echo(bridge.local_path)

        try:
            user = obj.client.load_object_from_name(WildlandObject.Type.USER, bridge.owner)
            if user.paths:
                user_desc = ' (' + ', '.join([str(p) for p in user.paths]) + ')'
            else:
                user_desc = ''
        except ManifestError:
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

    import_manifest(obj, path_or_url, paths, WildlandObject.Type.BRIDGE, bridge_owner, only_first)


bridge_.add_command(sign)
bridge_.add_command(verify)
bridge_.add_command(edit)
bridge_.add_command(dump)
bridge_.add_command(publish)
bridge_.add_command(unpublish)
