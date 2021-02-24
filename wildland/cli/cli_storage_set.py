# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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
Storage set management
'''

import click

from .cli_base import aliased_group, ContextObj, CliError
from ..manifest.manifest import ManifestError
from ..manifest.template import TemplateManager, SET_SUFFIX


@aliased_group('storage-set', short_help='storage setup sets management')
def storage_set_():
    '''Manage storages for container'''


@storage_set_.command('list', short_help='list storage setup sets', alias=['ls'])
@click.option('--show-filenames', '-s', is_flag=True, required=False,
              help='show filenames for storage template sets and template files')
@click.pass_obj
def set_list_(obj: ContextObj, show_filenames):
    """
    Display known storage setup sets and available storage templates.
    """

    template_manager = TemplateManager(obj.client.template_dir)

    click.echo("Existing storage template sets:")
    sets = template_manager.storage_sets()
    if not sets:
        click.echo("    No storage template sets defined.")
    else:
        for storage_set in sets:
            if show_filenames:
                click.echo(f"    {storage_set} [{storage_set.path}]")
            else:
                click.echo(f"    {storage_set}")

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


@storage_set_.command('add', short_help='add storage setup set', alias=['a'])
@click.option('--template', '-t', multiple=True, required=False,
              help='add this template file to set')
@click.option('--inline', '-i', multiple=True, required=False,
              help='add this template file to set as an inline template')
@click.argument('name', required=True)
@click.pass_obj
def set_add_(obj: ContextObj, template, inline, name):
    """
    Add a storage setup set.
    """
    target_path = obj.client.template_dir / (name + SET_SUFFIX)
    if target_path.exists():
        click.echo(f'Cannot create storage template set: set file {target_path} already exists.')
        return
    templates = [(template_name, 'file') for template_name in template] +\
                [(template_name, 'inline') for template_name in inline]
    if not templates:
        click.echo('Cannot create storage template set: no templates provided.')
        return
    template_manager = TemplateManager(obj.client.template_dir)

    return_path = template_manager.create_storage_set(name, templates, target_path)
    if return_path:
        click.echo(f'Created storage template set {name} in {return_path}.')


@storage_set_.command('remove', short_help='remove storage setup set', alias=['rm', 'd'])
@click.argument('name', required=False)
@click.pass_obj
def set_del_(obj: ContextObj, name):
    """
    Remove a storage template set.
    """

    template_manager = TemplateManager(obj.client.template_dir)
    removed_path = template_manager.remove_storage_set(name)

    click.echo(f'Deleted storage template set {removed_path}.')


@storage_set_.command('set-default', short_help='set default storage-set for a user')
@click.option('--user', required=True)
@click.argument('name', required=True)
@click.pass_obj
def set_default_(obj: ContextObj, user, name):
    """
    Set default for a user.
    """

    user_name = user
    template_manager = TemplateManager(obj.client.template_dir)
    try:
        template_manager.get_storage_set(name)
    except FileNotFoundError as fnf:
        raise CliError(f'Storage set {name} does not exist') from fnf

    obj.client.recognize_users()
    try:
        user = obj.client.load_user_by_name(user_name)
    except ManifestError as ex:
        raise CliError(f'User {user_name} load failed: {ex}') from ex

    default_sets = obj.client.config.get('default-storage-set-for-user')
    default_sets[user.owner] = name
    obj.client.config.update_and_save({'default-storage-set-for-user': default_sets})

    click.echo(f'Default storage set for {user_name} set to {name}.')
