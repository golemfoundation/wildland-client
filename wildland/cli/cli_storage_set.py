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

"""
Storage set management
"""

import click
import yaml

from .cli_base import aliased_group, ContextObj
from ..exc import WildlandError
from ..manifest.manifest import ManifestError, WildlandObjectType
from ..manifest.template import TemplateManager, SET_SUFFIX, TemplateWithType


@aliased_group('storage-set', short_help='storage setup sets management')
def storage_set_():
    """Manage storages for container"""


@storage_set_.command('list', short_help='list storage setup sets', alias=['ls'])
@click.option('--show-filenames', '-s', is_flag=True, required=False,
              help='show filenames for storage template sets and template files')
@click.pass_obj
def set_list_(obj: ContextObj, show_filenames):
    """
    Display known storage setup sets and available storage templates.
    """

    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])

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
    target_path = obj.client.dirs[WildlandObjectType.SET] / (name + SET_SUFFIX)
    if target_path.exists():
        click.echo(f'Cannot create storage template set: set file {target_path} already exists.')
        return
    templates = [
        *(TemplateWithType(template_name, 'file') for template_name in template),
        *(TemplateWithType(template_name, 'inline') for template_name in inline),
    ]
    if not templates:
        click.echo('Cannot create storage template set: no templates provided.')
        return
    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])

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

    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])
    try:
        removed_path = template_manager.remove_storage_set(name)
    except FileNotFoundError as fnf:
        raise WildlandError(f'template set {name} not found.') from fnf

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
    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])
    try:
        template_manager.get_storage_set(name)
    except FileNotFoundError as fnf:
        raise WildlandError(f'Storage set {name} does not exist') from fnf

    try:
        user = obj.client.load_object_from_name(WildlandObjectType.USER, user_name)
    except ManifestError as ex:
        raise WildlandError(f'User {user_name} load failed: {ex}') from ex

    default_sets = obj.client.config.get('default-storage-set-for-user')
    default_sets[user.owner] = name
    obj.client.config.update_and_save({'default-storage-set-for-user': default_sets})

    click.echo(f'Default storage set for {user_name} set to {name}.')


@storage_set_.group(short_help='modify storage set')
def modify():
    """
    Commands for modifying container manifests.
    """


@modify.command(short_help='add template to storage set')
@click.option('--template', '-t', multiple=True, required=False,
              help='add this template file to set')
@click.option('--inline', '-i', multiple=True, required=False,
              help='add this template file to set as an inline template')
@click.argument('storage_set', metavar='TEMPLATE_SET')
@click.pass_obj
def add_template(obj: ContextObj, storage_set, template, inline):
    """
    Add path to the manifest.
    """
    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])
    try:
        storage_set = template_manager.get_storage_set(storage_set)
    except FileNotFoundError as fnf:
        raise WildlandError(f'Template set \'{storage_set}\' not found.') from fnf

    templates_to_add = [(t, 'file') for t in template] + [(t, 'inline') for t in inline]

    for template_name, template_type in templates_to_add:
        try:
            storage_set.add_template(template_name, template_type)
        except FileNotFoundError as fnf:
            raise WildlandError(f'Template file {template_name} not found.') from fnf

    click.echo(f'Saving modified storage set {storage_set.name} to {storage_set.path}.')
    storage_set.path.write_text(yaml.dump(storage_set.to_dict()))


@modify.command(short_help='remove path from the manifest')
@click.option('--template', '-t', multiple=True, required=False,
              help='remove this template file from set')
@click.argument('storage_set', metavar='TEMPLATE_SET')
@click.pass_obj
def del_template(obj: ContextObj, storage_set, template):
    """
    Remove path from the manifest.
    """
    template_manager = TemplateManager(obj.client.dirs[WildlandObjectType.SET])
    try:
        storage_set = template_manager.get_storage_set(storage_set)
    except FileNotFoundError as fnf:
        raise WildlandError(f'Template set \'{storage_set}\' not found.') from fnf

    for t in template:
        try:
            storage_set.remove_template(t)
        except FileNotFoundError as fnf:
            raise WildlandError(f'Template file {t} not found.') from fnf

    click.echo(f'Saving modified storage set {storage_set.name} to {storage_set.path}.')
    storage_set.path.write_text(yaml.dump(storage_set.to_dict()))
