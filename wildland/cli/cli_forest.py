# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
Manage bridges
"""

from pathlib import Path, PurePosixPath
from typing import List, Dict, Any

import os
import uuid
import click

from wildland.wildland_object.wildland_object import WildlandObject
from .cli_storage import do_create_storage_from_templates
from ..container import Container
from ..storage import StorageBackend
from ..storage_backends.file_subcontainers import FileSubcontainersMixin
from ..user import User
from ..publish import Publisher
from ..manifest.manifest import Manifest
from ..manifest.template import TemplateManager, StorageTemplate
from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import modify_manifest, add_field
from .cli_container import _mount as mount_container
from .cli_container import _unmount as unmount_container
from ..exc import WildlandError


@aliased_group('forest', short_help='Wildland Forest management')
def forest_():
    """
    Manage Wildland Forests
    """


@forest_.command(short_help='Mount Wildland Forest')
@click.argument('forest_names', nargs=-1, required=True)
@click.option('--save', '-s', is_flag=True,
              help='Save the forest containers to be mounted at startup')
@click.option('--list-all', '-l', is_flag=True,
              help='During mount, list all forest containers, including those '
                   'who did not need to be changed')
@click.pass_context
def mount(ctx: click.Context, forest_names, save:bool, list_all: bool):
    """
    Mount a forest given by name or path to manifest. Repeat the argument to
    mount multiple forests.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    obj: ContextObj = ctx.obj

    forests = []
    for forest_name in forest_names:
        if forest_name.endswith('*:') or not forest_name.endswith(':'):
            raise WildlandError(
                f'Failed to parse forest name: {forest_name}. '
                f'For example, ":/forests/User:" is a valid forest name')
        forests.append(f'{forest_name}*:')
    mount_container(obj, forests, save=save, list_all=list_all)


@forest_.command(short_help='Unmount Wildland Forest')
@click.option('--path', metavar='PATH', help='mount path to search for')
@click.argument('forest_names', nargs=-1, required=True)
@click.pass_context
def unmount(ctx: click.Context, path: str, forest_names):
    """
    Unmount a forest given by name or path to manifest. Repeat the argument to
    unmount multiple forests.

    The Wildland system has to be mounted first, see ``wl start``.
    """
    obj: ContextObj = ctx.obj

    forests = []
    for forest_name in forest_names:
        if forest_name.endswith('*:') or not forest_name.endswith(':'):
            raise WildlandError(
                f'Failed to parse forest name: {forest_name}. '
                f'For example, ":/forests/User:" is a valid forest name')
        forests.append(f'{forest_name}*:')
    unmount_container(obj, path=path, container_names=forests)


@forest_.command(short_help='Bootstrap Wildland Forest')
@click.argument('user', metavar='USER', required=True)
@click.argument('storage_template', required=True)
@click.option('--access', metavar='USER', required=False, multiple=True,
              help='Name of users to encrypt the container with. Can be used multiple times. '
                   'If not set, the container is unencrypted.')
@click.option('--manifest-local-dir', metavar='PATH', required=False, multiple=False,
              show_default=True, default='/.manifests',
              help='Set manifests local directory. Must be an absolute path.')
@click.pass_context
def create(ctx: click.Context,
           user: str,
           storage_template: str,
           manifest_local_dir: str = '/.manifests/',
           access: List[str] = None):
    """
    Bootstrap a new Forest for given USER.
    You must have private key of that user in order to use this command.

    \b
    Arguments:
      USER                  name of the user who owns the Forest (mandatory)
      STORAGE_TEMPLATE      storage template used to create Forest containers

    Description

    This command creates an infrastructure container for the Forest.
    The storage template *must* contain at least one read-write storage.

    After the container is created, the following steps take place:

    \b
      1. A link object to infrastructure container is generated
         and appended to USER's manifest.
      2. USER manifest and instracture manifest are copied to the
         storage from Forest manifests container

    """
    _boostrap_forest(ctx,
                     user,
                     storage_template,
                     manifest_local_dir,
                     access)


def _boostrap_forest(ctx: click.Context,
                     user: str,
                     manifest_storage_template_name: str,
                     manifest_local_dir: str = '/',
                     access: List[str] = None):

    obj: ContextObj = ctx.obj

    # Load users manifests
    try:
        forest_owner = obj.client.load_object_from_name(WildlandObject.Type.USER, user)
    except WildlandError as we:
        raise CliError(f'User [{user}] could not be loaded. {we}') from we

    if not obj.client.session.sig.is_private_key_available(forest_owner.owner):
        raise CliError(f'Forest owner\'s [{user}] private key not found.')

    if access:
        if len(access) == 1 and access[0] == '*':
            access_list = [{'user': '*'}]
        else:
            try:
                access_list = [{'user': obj.client.load_object_from_name(
                                WildlandObject.Type.USER, user_name).owner}
                               for user_name in access]
            except WildlandError as we:
                raise CliError(f'User could not be loaded. {we}') from we
    else:
        access_list = [{'user': forest_owner.owner}]

    storage_templates = _resolve_storage_templates(obj, manifest_storage_template_name)

    infra_container = None

    try:
        infra_container = _create_container(obj, forest_owner, [Path('/.manifests')],
                                            f'{user}-forest-infra', access_list,
                                            storage_templates, manifest_local_dir)

        assert infra_container.local_path is not None
        assert forest_owner.local_path is not None

        infra_storage = obj.client.select_storage(container=infra_container,
                                                  predicate=lambda x: x.is_writeable)

        # If a writeable infra storage doesn't have manifest_pattern defined,
        # forcibly set manifest pattern for all storages in this container.
        # TODO: improve support for more complex forms of writeable storages and more complex
        # manifest-patterns

        infra_backend = StorageBackend.from_params(infra_storage.params)
        if isinstance(infra_backend, FileSubcontainersMixin) and \
                not infra_backend.params.get('manifest-pattern', None):
            infra_backend.params['manifest-pattern'] = infra_backend.DEFAULT_MANIFEST_PATTERN

        # Additionally ensure that they are going to be stored inline and override old storages
        # completely

        old_storages = list(obj.client.all_storages(infra_container))

        infra_container.clear_storages()

        for storage in old_storages:
            storage.params['manifest-pattern'] = infra_storage.params['manifest-pattern']
            obj.client.add_storage_to_container(infra_container, storage, inline=True)

        obj.client.save_object(WildlandObject.Type.CONTAINER, infra_container)

        manifests_storage = obj.client.select_storage(container=infra_container,
                                                      predicate=lambda x: x.is_writeable)
        manifests_backend = StorageBackend.from_params(manifests_storage.params)

        # Provision manifest storage with infrastructure container
        _boostrap_manifest(manifests_backend, infra_container.local_path,
                           Path('.manifests.yaml'))

        for storage in obj.client.all_storages(container=infra_container):

            link_obj: Dict[str, Any] = {'object': 'link', 'file': '/.manifests.yaml'}

            if not storage.base_url:
                fields = storage.to_manifest_fields(inline=True)
                if not storage.access:
                    fields['access'] = access_list
            else:
                fields = {
                    'object': 'storage', 'type': 'http', 'version': Manifest.CURRENT_VERSION,
                    'backend-id': str(uuid.uuid4()), 'owner': infra_container.owner,
                    'url': storage.base_url, 'access': storage.access or access_list}

            link_obj['storage']= fields

            modify_manifest(ctx, str(forest_owner.local_path), add_field,
                            'infrastructures', [link_obj])

        # Refresh users infrastructures
        obj.client.recognize_users_and_bridges()

        _boostrap_manifest(manifests_backend, forest_owner.local_path, Path('forest-owner.yaml'))
        Publisher(obj.client, infra_container).publish_container()
    except Exception as ex:
        raise CliError(f'Could not create a Forest. {ex}') from ex
    finally:
        if infra_container and infra_container.local_path:
            infra_container.local_path.unlink()


def _resolve_storage_templates(obj, template_name: str) -> List[StorageTemplate]:
    try:
        tpl_manager = TemplateManager(obj.client.dirs[WildlandObject.Type.TEMPLATE])

        return tpl_manager.get_template_file_by_name(template_name).templates
    except WildlandError as we:
        raise CliError(f'Could not load [{template_name}] storage template. {we}') from we


def _create_container(obj: ContextObj,
                      user: User,
                      container_paths: List[Path],
                      container_name: str,
                      access: List[dict],
                      storage_templates: List[StorageTemplate],
                      storage_local_dir: str = '') -> Container:

    container = Container(owner=user.owner, paths=[PurePosixPath(p) for p in container_paths],
                          backends=[], client=obj.client, access=access)

    obj.client.save_new_object(WildlandObject.Type.CONTAINER, container, container_name)
    do_create_storage_from_templates(obj.client, container, storage_templates, storage_local_dir)

    return container


def _boostrap_manifest(backend: StorageBackend, manifest_path: Path, file_path: Path):
    with backend:
        with backend.create(PurePosixPath(file_path), os.O_CREAT | os.O_WRONLY) as manifest_obj:
            data = manifest_path.read_bytes()
            manifest_obj.write(data, 0)
