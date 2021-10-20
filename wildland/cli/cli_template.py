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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Storage templates management
"""

import types
from typing import Optional, Sequence, Type
import functools
import click

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_base import aliased_group, ContextObj, CliError
from ..manifest.schema import SchemaError
from ..manifest.template import TemplateManager
from ..exc import WildlandError

from ..storage_backends.base import StorageBackend
from ..storage_backends.dispatch import get_storage_backends
from ..utils import format_command_options


@aliased_group('template', short_help='storage templates management')
def template():
    """
    Manage storage templates.
    """


@template.group('create', alias=['c'], short_help='create storage template')
def _create():
    """
    Creates storage template based on storage type.
    """


@template.group('add', alias=['a'], short_help='append to an existing storage template')
def _append():
    """
    Appends to an existing storage template based on storage type.
    """


def _make_create_command(backend: Type[StorageBackend], create: bool):
    params = [
        click.Option(['--access'], multiple=True, required=False, metavar='USER',
                     help='Limit access to this storage to the provided users. '
                          'By default the @default owner is used.'),
        click.Option(['--watcher-interval'], metavar='SECONDS', required=False, type=int,
                     help='Set the storage watcher-interval in seconds.'),
        click.Option(['--read-only'], metavar='BOOL', is_flag=True,
                     help='Mark storage as read-only.'),
        click.Option(['--default-cache'], metavar='BOOL', is_flag=True,
                     help='Mark template as default for container caches'),
        click.Argument(['name'], metavar='NAME', required=True),
    ]

    params.extend(backend.cli_options())

    callback = functools.partial(_do_create, backend=backend, create=create)

    command = click.Command(
        name=backend.TYPE,
        help=f'Create {backend.TYPE} storage template',
        params=params,
        callback=callback)
    setattr(command, "format_options", types.MethodType(format_command_options, command))
    return command


def _add_create_commands(group: click.core.Group, create: bool):
    for backend in get_storage_backends().values():
        try:
            command = _make_create_command(backend, create=create)
        except NotImplementedError:
            continue
        group.add_command(command)


def _do_create(
        backend: Type[StorageBackend],
        create: bool,
        name: str,
        watcher_interval: Optional[int],
        read_only: bool,
        default_cache: bool,
        access: Sequence[str],
        **data):

    obj: ContextObj = click.get_current_context().obj

    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])
    tpl_exists = template_manager.get_file_path(name).exists()

    if tpl_exists and create:
        raise CliError(f'Template {name} already exists. Choose another name or use '
                       '[wl template add] command to append to existing template.')

    if not tpl_exists and not create:
        raise CliError(f'Template {name} does not exist. Use [wl template create] '
                       'command to create a new template.')

    if default_cache and read_only:
        raise CliError('Cache storage cannot be read-only.')

    params = backend.cli_create(data)
    params['type'] = backend.TYPE
    params['read-only'] = read_only

    if watcher_interval:
        params['watcher-interval'] = watcher_interval

    if access:
        # We only accept '*' if '*' is the only entry, ie there can't be list of users alongside
        # with '*' entry
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

    local_dir_postfix = '{{ local_dir if local_dir is defined else "" }}/{{ uuid }}'

    if backend.LOCATION_PARAM:
        params[backend.LOCATION_PARAM] = \
            (params[backend.LOCATION_PARAM] or '').rstrip('/') + local_dir_postfix

    # remove default, non-required values
    for param_key in [k for k, v in params.items() if v is None or v == []]:
        del params[param_key]

    path = template_manager.create_storage_template(name, params)

    if tpl_exists:
        click.echo(f'Appended to an existing storage template [{name}]')
    else:
        click.echo(f'Storage template [{name}] created in {path}')

    if default_cache:
        obj.client.config.update_and_save({'default-cache-template': name})


@template.command('list', short_help='list storage templates', alias=['ls'])
@click.option('--show-filenames', '-s', is_flag=True, required=False,
              help='show filenames for storage template sets and template files')
@click.pass_obj
def template_list(obj: ContextObj, show_filenames: bool):
    """
    Display known storage templates
    """

    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

    click.echo('Available templates:')
    templates = template_manager.available_templates()

    if not templates:
        click.echo('No templates available.')
    else:
        for tpl in sorted(templates):
            if show_filenames:
                click.echo(f"    {tpl} [{template_manager.get_file_path(str(tpl))}]")
            else:
                click.echo(f"    {tpl}")


@template.command('remove', short_help='remove storage template', alias=['rm', 'delete'])
@click.argument('names', metavar='NAME', nargs=-1, required=True)
@click.pass_obj
def template_del(obj: ContextObj, names):
    """
    Remove a storage template set.
    """

    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])
    error_messages = ''
    for name in names:
        try:
            template_manager.remove_storage_template(name)
            click.echo(f'Deleted [{name}] storage template.')
        except FileNotFoundError:
            error_messages += f'Template [{name}] does not exist.\n'
        except WildlandError as ex:
            error_messages += f'{ex}\n'

    if error_messages:
        raise CliError(f'Some templates could not be deleted:\n{error_messages.strip()}')


@template.command('dump', short_help='dump contents of a storage template')
@click.argument('input_template', metavar='PATH/NAME')
@click.pass_obj
def template_dump(obj: ContextObj, input_template: str):
    """
    Dump contents of a storage template's .jinja file.
    """
    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

    try:
        template_bytes = template_manager.get_template_bytes(input_template)
        click.echo(template_bytes.decode())
    except FileNotFoundError:
        click.echo(f'Could not find template: {input_template}')


@click.command('edit', short_help='edit template in an external tool')
@click.option('--editor', metavar='EDITOR', help='custom editor')
@click.argument('input_template', metavar='PATH/NAME')
@click.pass_obj
def template_edit(obj: ContextObj, editor: Optional[str], input_template: str):
    """
    Edit template's .jinja file in an external tool. After editing, validate it.
    """
    template_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])
    try:
        original_data = template_manager.get_template_bytes(input_template)
        edited_file = click.edit(original_data.decode(), editor=editor, extension='.yaml',
                                 require_save=False)
        assert edited_file
        data = edited_file.encode()

        if original_data == data:
            click.echo('No changes detected, not saving.')
            return

        edited_yaml = template_manager.get_jinja_yaml(edited_file)
        for template_data in edited_yaml:
            storage_type = template_data['type']
            if not storage_type or not StorageBackend.is_type_supported(storage_type):
                raise WildlandError(f'Unrecognized storage type: {storage_type}')
            backend = StorageBackend.types()[storage_type]
            backend.SCHEMA.validate(template_data)

        template_manager.save_template_content(input_template, edited_file)
    except FileNotFoundError:
        click.secho(f'Could not find template: {input_template}', fg="red")
    except SchemaError as e:
        click.secho(f'Incorrectly formatted template: {e}', fg="red")
    except Exception as e:
        click.secho(f'Error occurred when editing template: {e}', fg="red")


_add_create_commands(_create, create=True)
_add_create_commands(_append, create=False)
template.add_command(template_dump)
template.add_command(template_edit)
