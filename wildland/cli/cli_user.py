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
Manage users
"""
from collections import defaultdict
from typing import List, Optional
from pathlib import PurePosixPath, Path
import click

from wildland.wildland_object.wildland_object import WildlandObject
from wildland.bridge import Bridge
from wildland.cleaner import get_cli_cleaner

from .cli_base import aliased_group, ContextObj
from .cli_exc import CliError
from ..wlpath import WildlandPath
from .cli_common import sign, verify, edit, modify_manifest, add_fields, del_fields, dump, \
    check_if_any_options, check_options_conflict, publish, unpublish
from .cli_bridge import do_bridge_import
from ..log import get_logger
from ..core.wildland_objects_api import WLObjectType, WLUser, WLBridge
from ..core.wildland_result import WLErrorType


logger = get_logger('cli-user')
cleaner = get_cli_cleaner()

@aliased_group('user', short_help='user management')
def user_():
    """
    Manage users
    """


@user_.command(short_help='create user')
@click.option('--key', metavar='KEY',
              help='use existing key pair (provide a filename (without extension); it must be in '
                   '~/.config/wildland/keys/')
@click.option('--path', 'paths', multiple=True,
              help='path (can be repeated)')
@click.option('--add-pubkey', 'additional_pubkeys', multiple=True,
              help='an additional public key that this user owns (can be repeated)')
@click.argument('name', metavar='NAME', required=False)
@click.pass_obj
def create(obj: ContextObj, key, paths, additional_pubkeys, name):
    """
    Create a new user manifest and save it. Clean up created files if fails.
    """
    try:
        _user_create(obj, key, paths, additional_pubkeys, name)
    except Exception as ex:
        click.secho('Creation failed.', fg='red')
        cleaner.clean_up()
        raise ex


def _user_create(obj: ContextObj, key, paths, additional_pubkeys, name):
    """
    Create a new user manifest and save it.
    """
    if key:
        result, pubkey = obj.wlcore.user_get_public_key(key)
        if result.failure:
            raise CliError(f'Failed to use provided key:\n  {result}')
        click.echo(f'Using key: {key}')
        owner = key
    else:
        result, owner, pubkey = obj.wlcore.user_generate_key()
        if result.failure:
            raise CliError(f'Failed to use provided key:\n  {result}')
        click.echo(f'Generated key: {owner}')
    assert pubkey

    keys = [pubkey]
    if additional_pubkeys:
        keys.extend(additional_pubkeys)

    # do paths
    if paths:
        paths = list(paths)
    else:
        if name:
            paths = [f'/users/{name}']
        else:
            paths = [f'/users/{owner}']
        click.echo(f'No path specified, using: {paths[0]}')

    result, user = obj.wlcore.user_create(name, keys, paths)

    if result.failure or not user:
        if not key:
            obj.wlcore.user_remove_key(owner, force=False)
        raise CliError(f'Failed to create user: {result}')

    _, current_default = obj.wlcore.env.get_default_user()
    if not current_default:
        click.echo(f'Using {owner} as @default')
        obj.wlcore.env.set_default_user(owner)
    _, current_default_owner = obj.wlcore.env.get_default_owner()
    if not current_default_owner:
        click.echo(f'Using {owner} as @default-owner')
        obj.wlcore.env.set_default_owner(owner)

    click.echo(f'Adding {owner} to local owners')
    obj.wlcore.env.add_local_owners(owner)


@user_.command('list', short_help='list users', alias=['ls'])
@click.option('--verbose', '-v', is_flag=True,
              help='Show extended output')
@click.option('--list-secret-keys', '-K', is_flag=True,
              help='Show users with private key available only')
@click.pass_obj
def list_(obj: ContextObj, verbose, list_secret_keys):
    """
    Display known users.
    """

    default_user = obj.wlcore.env.get_default_user()[1]
    default_owner = obj.wlcore.env.get_default_owner()[1]
    default_override = (default_user != obj.wlcore.env.get_default_user(use_override=False)[1])

    result_users, users = obj.wlcore.user_list()
    result_bridges, bridges = obj.wlcore.bridge_list()

    if not result_bridges.success or not result_users.success:
        click.echo('Failed to list users:')
        for e in result_users.errors + result_bridges.errors:
            click.echo(f'Error {e.error_code}: {e.error_description}')

    # TODO: this used to use a client method called load_users_with_bridge_paths; perhaps this
    # will be obsolete soon?

    bridges_from_default_user = defaultdict(list)
    for bridge in bridges:
        if bridge.owner == default_user:
            bridges_from_default_user[bridge.user_id].extend(bridge.paths)

    for user in users:
        _, path = obj.wlcore.object_get_local_path(WLObjectType.USER, user.id)
        path_string = str(path)
        if list_secret_keys and not user.private_key_available:
            continue
        if user.owner == default_user:
            path_string += ' (@default)'
            if default_override:
                path_string += ' (@default overridden by wl start parameters)'
        if user.owner == default_owner:
            path_string += ' (@default-owner)'
        click.echo(path_string)
        click.echo(f'  owner: {user.owner}')
        if user.private_key_available:
            click.echo('  private and public keys available')
        else:
            click.echo('  only public key available')
        if user.owner not in bridges_from_default_user:
            click.echo('   no bridges to user available')
        else:
            for bridge_path in bridges_from_default_user[user.owner]:
                click.echo(f'   bridge path: {bridge_path}')
        for user_path in user.paths:
            click.echo(f'   user path: {user_path}')

        if verbose:
            for user_container in user.manifest_catalog_description:
                click.echo(f'   container: {user_container}')
        click.echo()


@user_.command('delete', short_help='delete a user', alias=['rm', 'remove'])
@click.pass_obj
@click.option('--force', '-f', is_flag=True,
              help='delete even if still has containers/storage')
@click.option('--cascade', is_flag=True,
              help='remove all containers and storage as well')
@click.option('--delete-keys', is_flag=True,
              help='also remove user keys')
@click.argument('names', metavar='NAME', nargs=-1)
def delete(obj: ContextObj, names, force, cascade, delete_keys):
    """
    Delete a user.
    """

    error_messages = ''
    for name in names:
        try:
            _delete(obj, name, force, cascade, delete_keys)
        except Exception as e:
            error_messages += f'{e}\n'

    if error_messages:
        raise CliError(f'Some users could not be deleted:\n{error_messages.strip()}')


def _delete(obj: ContextObj, name: str, force: bool, cascade: bool, delete_keys: bool):
    _, user = obj.wlcore.object_get(WLObjectType.USER, name)
    if not user:
        p = Path(name)
        if not p.exists():
            raise CliError(f'User {name} not found.')
        yaml_data = p.read_text()
        result, user = obj.wlcore.object_info(yaml_data)
        if not user:
            raise CliError(f'User {name} cannot be parsed: {str(result)}')

    result, usages = obj.wlcore.user_get_usages(user.id)
    if result.failure and not force:
        raise CliError(f'Fatal error while looking for user\'s containers: {str(result)}')

    used = False
    for usage in usages:
        if cascade:
            click.echo('Deleting container: {}'.format(usage.id))
            result = obj.wlcore.container_delete(usage.id)
            if result.failure:
                raise CliError(f'Cannot delete user\'s container: {result}')
        else:
            _, cont_path = obj.wlcore.object_get_local_path(WLObjectType.CONTAINER, usage.id)
            click.echo('Found container: {}'.format(cont_path))
            used = True

    if used and not force:
        raise CliError('User still has manifests, not deleting '
                       '(use --force or --cascade)')

    if delete_keys:
        result = obj.wlcore.user_remove_key(user.owner, force=force)
        if result.failure:
            raise CliError(str(result))

    _, default_user = obj.wlcore.env.get_default_user(use_override=False)
    if default_user == user.owner:
        click.echo('Removing @default from configuration file')
        obj.wlcore.env.reset_default_user()
    _, default_owner = obj.wlcore.env.get_default_owner()
    if default_owner == user.owner:
        click.echo('Removing @default-owner from configuration file')
        obj.wlcore.env.reset_default_owner()

    if obj.wlcore.env.is_local_owner(user.owner):
        obj.wlcore.env.remove_local_owners(user.owner)
        click.echo(f'Removing {user.owner} from local_owners')

    click.echo(f'Deleting: {user.owner}')
    result = obj.wlcore.user_delete(user.owner)
    if result.failure:
        raise CliError(f'Failed to delete user: {result}')


@user_.command('import', short_help='import bridge or user manifest', alias=['im'])
@click.pass_obj
@click.option('--path', 'paths', multiple=True,
              help='path for resulting bridge manifest (can be repeated); if omitted, will'
                   ' use user\'s paths')
@click.option('--bridge-owner', help="specify a different (then default) user to be used as the "
                                     "owner of created bridge manifests")
@click.argument('path-or-url')
def user_import(obj: ContextObj, path_or_url: str, paths: List[str], bridge_owner: Optional[str]):
    """
    Import a provided user or bridge manifest.
    Accepts a local path, an url or a Wildland path to manifest or to bridge.
    Optionally override bridge paths with paths provided via --path.
    Created bridge manifests will use system @default-owner, or --bridge-owner is specified.
    """
    try:
        _user_import(obj, path_or_url, paths, bridge_owner)
    except Exception as ex:
        click.secho('Import failed.', fg='red')
        cleaner.clean_up()
        raise CliError(f'Failed to import: {str(ex)}') from ex


def _user_import(obj: ContextObj, path_or_url: str, paths: List[str], bridge_owner: Optional[str]):
    """
    Import a provided user or bridge manifest.
    """
    p = Path(path_or_url)
    name = path_or_url
    name = name.split('/')[-1]

    if p.exists():
        yaml_data = p.read_bytes()
        name = p.name
        result, imported_object = obj.wlcore.object_import_from_yaml(yaml_data, name)
    else:
        result, imported_object = obj.wlcore.object_import_from_url(path_or_url, name)

    if result.failure:
        if len(result.errors) == 1 and result.errors[0].error_code == WLErrorType.FILE_EXISTS_ERROR:
            result, imported_object = obj.wlcore.user_get_by_id(result.errors[0].error_description)
            if not imported_object:
                raise CliError(f'Failed to import manifest: {str(result)}')
            click.echo('User already exists, skipping.')
        else:
            raise CliError(f'Failed to import manifest: {str(result)}')

    if isinstance(imported_object, WLUser):
        result, bridges = obj.wlcore.bridge_list()
        for bridge in bridges:
            if bridge.user_id == imported_object.owner:
                click.echo('Bridge already exists, skipping.')
                return
        if not paths:
            safe_paths = Bridge.create_safe_bridge_paths(
                imported_object.owner, [PurePosixPath(path) for path in imported_object.paths])
            paths = [str(path) for path in safe_paths]
        result, _ = obj.wlcore.bridge_create(paths, bridge_owner, imported_object.owner,
                                             user_url=path_or_url, name=name)
    elif isinstance(imported_object, WLBridge):
        # the user was actually trying to import a bridge. Well, we'll politely help them anyway
        obj.wlcore.bridge_delete(imported_object.id)
        do_bridge_import(obj.wlcore, path_or_url, paths, bridge_owner, False)
    else:
        raise CliError(f'Cannot import {path_or_url}: only user or bridge '
                       f'manifests can be imported')

    if result.failure:
        raise CliError(f'Failed to import {path_or_url}: {result}')

@user_.command('refresh', short_help='Iterate over bridges and pull latest user manifests',
               alias=['r'])
@click.pass_obj
@click.argument('name', metavar='USER', required=False)
def user_refresh(obj: ContextObj, name):
    """
    Iterates over bridges and fetches each user's file from the URL specified in the bridge
    """
    user_list: Optional[List[str]]

    if name:
        result, user = obj.wlcore.object_get(WLObjectType.USER, name)
        if result.failure or not user:
            raise CliError(f'User {name} cannot be loaded: {result}')
        user_list = [user.id]
    else:
        user_list = None

    result = obj.wlcore.user_refresh(user_list)
    if result.failure:
        raise CliError(f'Failed to refresh users: {result}')


user_.add_command(sign)
user_.add_command(verify)
user_.add_command(edit)
user_.add_command(dump)
user_.add_command(publish)
user_.add_command(unpublish)


@user_.command(short_help='modify user manifest')
@click.option('--add-path', metavar='PATH', multiple=True, help='path to add')
@click.option('--del-path', metavar='PATH', multiple=True, help='path to remove')
@click.option('--add-catalog-entry', metavar='PATH', multiple=True, help='container path to add')
@click.option('--del-catalog-entry', metavar='PATH', multiple=True, help='container path to remove')
@click.option('--add-pubkey', metavar='PUBKEY', multiple=True, help='raw public key to append')
@click.option('--add-pubkey-user', metavar='USER', multiple=True,
              help='user whose public keys should be appended to FILE')
@click.option('--del-pubkey', metavar='PUBKEY', multiple=True, help='public key to remove')
@click.argument('input_file', metavar='FILE')
@click.pass_context
def modify(ctx: click.Context,
           add_path, del_path, add_catalog_entry, del_catalog_entry,
           add_pubkey, add_pubkey_user, del_pubkey,
           input_file
           ):
    """
    Command for modifying user manifests.
    """
    _option_check(ctx, add_path, del_path, add_catalog_entry, del_catalog_entry,
                  add_pubkey, add_pubkey_user, del_pubkey)

    add_members = []
    add_pubkeys = []
    for p in add_pubkey:
        if WildlandPath.WLPATH_RE.match(p):
            add_members.append({"user-path": WildlandPath.get_canonical_form(p)})
        else:
            add_pubkeys.append(p)

    del_members = []
    del_pubkeys = []
    for p in del_pubkey:
        if WildlandPath.WLPATH_RE.match(p):
            del_members.append({"user-path": WildlandPath.get_canonical_form(p)})
        else:
            del_pubkeys.append(p)

    pubkeys = _get_all_pubkeys_and_check_conflicts(ctx, add_pubkeys, add_pubkey_user, del_pubkeys)

    to_add = {'paths': add_path, 'manifests-catalog': add_catalog_entry,
              'pubkeys': pubkeys, 'members': add_members}
    to_del = {'paths': del_path, 'manifests-catalog': del_catalog_entry,
              'pubkeys': del_pubkeys, 'members': del_members}

    modify_manifest(ctx, input_file,
                    edit_funcs=[add_fields, del_fields],
                    to_add=to_add,
                    to_del=to_del,
                    logger=logger)


def _option_check(ctx, add_path, del_path, add_catalog_entry, del_catalog_entry,
                  add_pubkey, add_pubkey_user, del_pubkey):
    check_if_any_options(ctx, add_path, del_path, add_catalog_entry, del_catalog_entry,
                         add_pubkey, add_pubkey_user, del_pubkey)
    check_options_conflict("path", add_path, del_path)
    check_options_conflict("catalog_entry", add_catalog_entry, del_catalog_entry)
    check_options_conflict("pubkey", add_pubkey, del_pubkey)


def _get_all_pubkeys_and_check_conflicts(ctx, add_pubkey, add_pubkey_user, del_pubkey):
    pubkeys = set(add_pubkey)

    conflicts = ""
    for name in add_pubkey_user:
        user_obj = ctx.obj.client.load_object_from_name(WildlandObject.Type.USER, name)

        click.echo(f'Pubkeys found in [{name}]:')

        for key in user_obj.pubkeys:
            click.echo(f'  {key}')

        pubkey_conflicts = set(del_pubkey).intersection(user_obj.pubkeys)
        if pubkey_conflicts:
            conflicts += 'Error: options conflict:'
            for c in pubkey_conflicts:
                conflicts += f'\n  --add-pubkey-user {name} and --del-pubkey {c}' \
                             f'\n    User {name} has a pubkey {c}'

        pubkeys.update(user_obj.pubkeys)
    if conflicts:
        raise CliError(conflicts)

    for key in pubkeys:
        if not ctx.obj.session.sig.is_valid_pubkey(key):
            raise CliError(f'Given pubkey [{key}] is not a valid pubkey')

    return pubkeys
