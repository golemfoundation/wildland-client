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

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import aliased_group, ContextObj, CliError
from ..manifest.template import TemplateManager
from ..exc import WildlandError

from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends


@aliased_group('storage-template', short_help='storage templates management')
def storage_template():
    """Manage storage templates"""


@storage_template.group('create', alias=['c'], short_help='create storage template')
def _create():
    """
    Creates storage template based on storage type.
    """


@storage_template.group('add', alias=['a'], short_help='append to an existing storage template')
def _append():
    """
    Appends to an existing storage template based on storage type.
    """


def _make_create_command(backend: Type[StorageBackend], create: bool):
    params = [
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

    callback = functools.partial(_do_create, backend=backend, create=create)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage template',
        params=params,
        callback=callback)
    return command


def _add_create_commands(group, create: bool):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend, create=create)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        create: bool,
        name,
        watcher_interval,
        base_url,
        read_only,
        access,
        **data):

    obj: ContextObj = click.get_current_context().obj

    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])
    tpl_exists = template_manager.get_file_path(name).exists()

    if tpl_exists and create:
        raise CliError(f'Template {name} already exists. Choose another name or use '
                       '[wl storage-template add] command to append to existing template.')

    if not tpl_exists and not create:
        raise CliError(f'Template {name} does not exist. Use [wl storage-template create] '
                       'command to create a new template.')

    params = backend.cli_create(data)
    params['type'] = backend.TYPE
    params['read-only'] = read_only

    if watcher_interval:
        params['watcher-interval'] = int(watcher_interval)

    if access:
        # We only accept '*' if '*' is the only entry, ie there can't be list of users
        # alongside with '*' entry
        if list(access) == ['*']:
            params['access'] = [{'user': '*'}]
        else:
            try:
                params['access'] = [
                    {'user': obj.client.load_object_from_name(WildlandObject.Type.USER, user).owner}
                    for user in access
                ]
            except WildlandError as ex:
                raise CliError(f'Failed to create storage template: {ex}') from ex

    if backend.LOCATION_PARAM:
        params[backend.LOCATION_PARAM] = str(params[backend.LOCATION_PARAM]).rstrip('/') + \
                                             '{{ local_dir if local_dir is defined else "/" }}' + \
                                             '/{{ uuid }}'

    if base_url:
        params['base-url'] = base_url.rstrip('/') + \
                                '{{ local_dir if local_dir is defined else "/" }}/{{ uuid }}'

    # remove default, non-required values
    for param, value in list(params.items()):
        if value is None or value == []:
            del params[param]

    path = template_manager.create_storage_template(name, params)

    if tpl_exists:
        click.echo(f"Appended to an existing storage template [{name}]")
    else:
        click.echo(f"Storage template [{name}] created in {path}")


@storage_template.command('list', short_help='list storage templates', alias=['ls'])
@click.option('--show-filenames', '-s', is_flag=True, required=False,
              help='show filenames for storage template sets and template files')
@click.pass_obj
def template_list(obj: ContextObj, show_filenames):
    """
    Display known storage templates
    """

    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

    click.echo("Available templates:")
    templates = template_manager.available_templates()

    if not templates:
        click.echo("    No templates available.")
    else:
        for template in templates:
            if show_filenames:
                click.echo(f"    {template} [{template_manager.get_file_path(str(template))}]")
            else:
                click.echo(f"    {template}")


@storage_template.command('remove', short_help='remove storage template', alias=['rm', 'd'])
@click.argument('name', required=True)
@click.pass_obj
def template_del(obj: ContextObj, name: str):
    """
    Remove a storage template set.
    """

    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])
    try:
        template_manager.remove_storage_template(name)
    except FileNotFoundError as fnf:
        raise CliError(f"Template [{name}] does not exist.") from fnf
    except WildlandError as ex:
        raise CliError(f'Failed to delete template: {ex}') from ex

    click.echo(f'Deleted [{name}] storage template.')


_add_create_commands(_create, create=True)
_add_create_commands(_append, create=False)
