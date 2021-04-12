# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
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

"""
Storage set management
"""

from typing import Type
import functools
import click

from .cli_base import aliased_group, ContextObj, CliError
from ..manifest.template import TemplateManager
from ..manifest.manifest import WildlandObjectType
from ..exc import WildlandError

from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends


@aliased_group('storage-template', short_help='storage templates management')
def storage_template():
    """Manage storage templates"""


@storage_template.group('create', short_help='create storage template')
def create():
    """
    Creates storage template based on storage type.
    """


def _make_create_command(backend: Type[StorageBackend]):
    params = [
        click.Option(['--manifest-pattern'], metavar='GLOB',
                     help='Set the manifest pattern for storage.'),
        click.Option(['--access'], multiple=True, required=False, metavar='USER',
                     help="Limit access to this storage to the provided users. "
                          "By default the @default owner is used."),
        click.Option(['--watcher-interval'], metavar='SECONDS', required=False,
                     help='Set the storage watcher-interval in seconds.'),
        click.Option(['--base-url'], metavar='URL', required=False,
                     help='Set public base URL.'),
        click.Option(['--read-only'], metavar='BOOL', is_flag=True,
                     help='Mark storage as read-only.'),
        click.Argument(['name'], metavar='NAME', required=True),
    ]

    params.extend(backend.cli_options())

    callback = functools.partial(_do_create, backend=backend)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage template',
        params=params,
        callback=callback)
    return command


def _add_create_commands(group):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        name,
        manifest_pattern,
        watcher_interval,
        base_url,
        read_only,
        access,
        **data):

    obj: ContextObj = click.get_current_context().obj

    obj.client.recognize_users()

    params = backend.cli_create(data)

    params['type'] = backend.TYPE

    params['read-only'] = read_only

    if watcher_interval:
        params['watcher-interval'] = int(watcher_interval)

    manifest_pattern_dict = None
    if manifest_pattern:
        manifest_pattern_dict = {
            'type': 'glob',
            'path': manifest_pattern,
        }
    params['manifest-pattern'] = manifest_pattern_dict

    if access:
        # We only accept '*' if '*' is the only entry, ie there can't be list of users
        # alongside with '*' entry
        if list(access) == ['*']:
            params['access'] = [{'user': '*'}]
        else:
            try:
                params['access'] = [
                    {'user': obj.client.load_object_from_name(WildlandObjectType.USER, user).owner}
                    for user in access
                ]
            except WildlandError as ex:
                raise CliError(f'Failed to create storage template: {ex}') from ex

    if backend.LOCATION_PARAM:
        params[backend.LOCATION_PARAM] = str(params[backend.LOCATION_PARAM]).rstrip('/') + \
                                            "{{ local_dir if local_dir is defined else '/' }}"

    if base_url:
        params['base-url'] = base_url.rstrip('/') + \
                                "{{ local_dir if local_dir is defined else '/' }}"

    # remove default, non-required values
    for param, value in list(params.items()):
        if value is None or value == []:
            del params[param]

    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])

    try:
        path = template_manager.create_storage_template(name, params)
        click.echo(f"Template [{name}] created in {path}")
    except FileExistsError as fee:
        raise CliError(f"Template [{name}] already exists. Choose another name.") from fee


@storage_template.command('list', short_help='list storage templates', alias=['ls'])
@click.option('--show-filenames', '-s', is_flag=True, required=False,
              help='show filenames for storage template sets and template files')
@click.pass_obj
def template_list(obj: ContextObj, show_filenames):
    """
    Display known storage templates
    """

    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])

    click.echo("Available templates:")
    templates = template_manager.available_templates()

    if not templates:
        click.echo("    No templates available.")
    else:
        for template in templates:
            if show_filenames:
                click.echo(f"    {template} [{template_manager.template_dir / template.file_name}]")
            else:
                click.echo(f"    {template}")


@storage_template.command('remove', short_help='remove storage template', alias=['rm', 'd'])
@click.option('--force', is_flag=True, default=False,
              help="Force delete even if attached to a set.")
@click.option('--cascade', is_flag=True, default=False,
              help="Delete together with attached sets")
@click.argument('name', required=True)
@click.pass_obj
def template_del(obj: ContextObj, name: str, force: bool, cascade: bool):
    """
    Remove a storage template set.
    """

    if force and cascade:
        raise CliError("Remove command accepts either force or cascade option, but not both.")

    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])
    try:
        template_manager.remove_storage_template(name, force, cascade)
    except FileNotFoundError as fnf:
        raise CliError(f"Template [{name}] does not exist.") from fnf
    except WildlandError as ex:
        raise CliError(f'Failed to delete template: {ex}') from ex

    click.echo(f'Deleted [{name}] storage template.')


_add_create_commands(create)
