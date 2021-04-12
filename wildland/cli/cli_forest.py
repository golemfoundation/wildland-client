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
from typing import List, Optional
from urllib.parse import urljoin

import os
import click

from .cli_storage import do_create_storage_from_set
from ..container import Container
from ..storage import StorageBackend, Storage
from ..user import User
from ..publish import Publisher
from ..manifest.template import TemplateManager, StorageSet
from ..manifest.manifest import WildlandObjectType
from .cli_base import aliased_group, ContextObj, CliError
from .cli_common import modify_manifest, add_field
from ..exc import WildlandError


@aliased_group('forest', short_help='Wildland Forest management')
def forest_():
    """
    Manage Wildland Forests
    """


@forest_.command(short_help='Bootstrap Wildland Forest')
@click.argument('user', metavar='USER', required=True)
@click.argument('storage_set', required=False)
@click.argument('data_storage_set', required=False)
@click.option('--access', metavar='USER', required=False, multiple=True,
              help='Name of users to encrypt the container with. Can be used multiple times. '
                   'If not set, the container is unencrypted.')
@click.option('--manifest-local-dir', metavar='PATH', required=False, multiple=False,
              show_default=True, default='/',
              help='Set manifests local directory. Must be an absolute path.')
@click.option('--data-local-dir', metavar='PATH', required=False, multiple=False,
              show_default=True, default='/',
              help='Set data local directory. Must be an absolute path.')
@click.pass_context
def create(ctx: click.Context,
           user: str,
           storage_set: str = None,
           data_storage_set: str = None,
           manifest_local_dir: str = '/',
           data_local_dir: str = '/',
           access: List[str] = None):
    """
    Bootstrap a new Forest for given USER.
    You must have private key of that user in order to use this command.

    \b
    Arguments:
      USER                  name of the user who owns the Forest (mandatory)
      STORAGE_SET           storage set used to create Forest containers, if not given, user's
                            default storage-set is used instead
      DATA_STORAGE_SET      storage set used to create Forest data container, if not given, the
                            STORAGE_SET is used instead

    Description

    This command creates three containers

    \b
      1. A container for Forest manifests
      2. An infrastructure container for the Forest
      3. A container for Forest data

    The first two containers are created using STORAGE_SET, the latter using
    DATA_STORAGE_SET, storage templates.

    Manifest storage set *must* contain a template with RW storage as well as `base-url`
    parameter defined, which is used to determine the Forest's infrastructure location.

    After the containers are created, the following steps take place:

    \b
      1. An url to infrastructure container is generated based on
         `base-url` and appended to USER's manifest.
      2. USER manifest and instracture manifest are copied to the
         storage from Forest manifests container
      3. Both infrastructure and data Forest containers are published
         to USER's infrastracture.

    """
    _boostrap_forest(ctx,
                     user,
                     manifest_local_dir,
                     data_local_dir,
                     access=access,
                     manifest_storage_set_name=storage_set,
                     data_storage_set_name=data_storage_set)


def _boostrap_forest(ctx: click.Context,
                     user: str,
                     manifest_local_dir: str = '/',
                     data_local_dir: str = '/',
                     access: List[str] = None,
                     manifest_storage_set_name: str = None,
                     data_storage_set_name: str = None):

    obj: ContextObj = ctx.obj
    obj.client.recognize_users()

    # Load users manifests
    try:
        forest_owner = obj.client.load_object_from_name(WildlandObjectType.USER, user)
    except WildlandError as we:
        raise CliError(f'User [{user}] could not be loaded. {we}') from we

    if not obj.client.session.sig.is_private_key_available(forest_owner.owner):
        raise CliError(f'Forest owner\'s [{user}] private key not found.')

    if access:
        try:
            access_list = [{'user': obj.client.load_object_from_name(
                WildlandObjectType.USER, user_name).owner}
                           for user_name in access]
        except WildlandError as we:
            raise CliError(f'User could not be loaded. {we}') from we
    else:
        access_list = [{'user': '*'}]

    # Determine manifest and data storage sets
    if not data_storage_set_name:
        data_storage_set_name = manifest_storage_set_name

    manifest_storage_set = _resolve_storage_set(obj, forest_owner, manifest_storage_set_name)
    data_storage_set     = _resolve_storage_set(obj, forest_owner, data_storage_set_name)

    # Create containers

    manifests_container = _create_container(obj, forest_owner, [],
                                            f'{user}-forest-manifests', access_list,
                                            manifest_storage_set, manifest_local_dir)

    infra_container     = _create_container(obj, forest_owner, [Path('/.manifests')],
                                            f'{user}-forest-infra', access_list,
                                            manifest_storage_set,
                                            str(Path(manifest_local_dir) / '.manifests/'))

    data_container      = _create_container(obj, forest_owner, [Path(f'/home/{user}')],
                                            f'{user}-forest-data', access_list,
                                            data_storage_set, data_local_dir)


    assert manifests_container.local_path is not None
    assert infra_container.local_path is not None
    assert data_container.local_path is not None
    assert forest_owner.local_path is not None

    infra_storage = obj.client.select_storage(container=infra_container,
                                              predicate=lambda x: x.is_writeable)

    # If a writeable infra storage doesn't have manifest_pattern defined,
    # forcibly set manifest pattern for all storages in this container.
    if not infra_storage.manifest_pattern:
        for storage in list(obj.client.all_storages(manifests_container)):
            storage.manifest_pattern = Storage.DEFAULT_MANIFEST_PATTERN
            obj.client.add_storage_to_container(infra_container, storage)

        obj.client.save_object(WildlandObjectType.CONTAINER, manifests_container)

    manifests_storage = obj.client.select_storage(container=manifests_container,
                                                  predicate=lambda x: x.is_writeable)
    manifests_backend = StorageBackend.from_params(manifests_storage.params)

    if not manifests_storage.base_url:
        manifests_container.local_path.unlink()
        infra_container.local_path.unlink()
        data_container.local_path.unlink()
        raise CliError("Given manifest storage does not have base-url defined.")

    # Provision manifest storage with infrastructure container
    _boostrap_manifest(manifests_backend, infra_container.local_path,
                       Path(f"{user}-index.yaml"))

    manifest_url = urljoin(manifests_storage.base_url + "/", f"{user}-index.yaml")
    modify_manifest(ctx, str(forest_owner.local_path), add_field,
                    'infrastructures', [str(manifest_url)])

    _boostrap_manifest(manifests_backend, forest_owner.local_path, Path(f'{user}.yaml'))

    # Publish infrastructure manifests and home containers
    obj.client.recognize_users()
    Publisher(obj.client, infra_container).publish_container()
    Publisher(obj.client, data_container).publish_container()


def _resolve_storage_set(obj, user: User, storage_set: Optional[str]) -> StorageSet:
    default_set = obj.client.config.get('default-storage-set-for-user')\
                                   .get(user.owner, None)

    if storage_set is None:
        if default_set is None:
            raise CliError('No storage set available')

        storage_set = default_set

    try:
        return TemplateManager(obj.client.dirs[WildlandObjectType.SET]).get_storage_set(storage_set)
    except FileNotFoundError as fnf:
        raise CliError(f'Storage set [{storage_set}] not found. {fnf}') from fnf


def _create_container(obj: ContextObj,
                      user: User,
                      container_paths: List[Path],
                      container_name: str,
                      access: List[dict],
                      storage_set: StorageSet,
                      storage_local_dir: str = '') -> Container:

    container = Container(owner=user.owner, paths=[PurePosixPath(p) for p in container_paths],
                          backends=[], access=access)

    obj.client.save_new_object(WildlandObjectType.CONTAINER, container, container_name)
    do_create_storage_from_set(obj.client, container, storage_set, storage_local_dir)

    return container


def _boostrap_manifest(backend: StorageBackend, manifest_path: Path, file_path: Path):
    with backend:
        with backend.create(PurePosixPath(file_path), os.O_CREAT | os.O_WRONLY) as manifest_obj:
            data = manifest_path.read_bytes()
            manifest_obj.write(data, 0)
