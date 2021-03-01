# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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

'''
Stuff related to publishing and unpublishing containers.
'''

import collections
import logging
import pathlib
from typing import cast

from . import (
    client as _client,
    container as _container,
    search as _search,
    storage as _storage,
)
from .exc import WildlandError
from .manifest.manifest import ManifestError

logger = logging.getLogger('publish')

def get_storage_for_publish(client: _client.Client, owner: str) -> _storage.Storage:
    '''
    Retrieves suitable storage to publish container manifest.
    '''

    myowner = client.load_user_by_name(owner)

    rejected = []
    if not myowner.containers:
        rejected.append(f'user {owner} has no infrastructure containers')

    for c in myowner.containers:
        try:
            container_candidate = client.load_container_from_url_or_dict(
                c, owner)

            all_storages = list(
                client.all_storages(container=container_candidate))

            if not all_storages:
                rejected.append(
                    f'container {container_candidate.ensure_uuid()} '
                    'has no available storages')
                continue

            for storage_candidate in all_storages:
                if storage_candidate.manifest_pattern is None:
                    rejected.append(
                        f'storage {storage_candidate.params["backend-id"]} of '
                        f'container {container_candidate.ensure_uuid()} '
                        'does not have manifest_pattern')
                    continue

                if not storage_candidate.is_writeable:
                    rejected.append(
                        f'storage {storage_candidate.params["backend-id"]} of '
                        f'container {container_candidate.ensure_uuid()} '
                        'is not writeable')
                    continue

                # Attempt to mount the storage driver first.
                # Failure in attempt to mount the backend should try the next storage from the
                # container and if still not mounted, move to the next container
                try:
                    with _search.StorageDriver.from_storage(storage_candidate) as _driver:
                        return storage_candidate

                except (WildlandError, PermissionError, FileNotFoundError) as ex:
                    rejected.append(
                        f'storage {storage_candidate.params["backend-id"]} of '
                        f'container {container_candidate.ensure_uuid()} '
                        f'could not be mounted: {ex!s}')
                    logger.debug(
                        'Failed to mount storage when publishing with '
                        'exception: %s',
                        ex)
                    continue

        except (ManifestError, WildlandError) as ex:
            rejected.append(
                f'container {container_candidate.ensure_uuid()} has '
                'serious problems: {ex!s}')
            logger.debug(
                'Failed to load container when publishing with '
                'exception: %s',
                ex)
            continue

    raise WildlandError(
        'Cannot find any container suitable as publishing platform:'
        + ''.join(f'\n- {i}' for i in rejected))

def _manifest_filenames_from_pattern(
        path_pattern, obj_uuid, container_expanded_paths):
    path_pattern = path_pattern.replace('*', obj_uuid)

    if '{path}' not in path_pattern:
        yield pathlib.PurePosixPath(path_pattern).relative_to('/')
        return

    for path in container_expanded_paths:
        yield pathlib.PurePosixPath(path_pattern.replace(
            '{path}', str(path.relative_to('/')))).relative_to('/')

def _publish_storage_to_driver(
        client: _client.Client,
        driver: _search.StorageDriver,
        storage: _storage.Storage,
        container_expanded_paths):
    data = client.session.dump_storage(storage)

    relpath = None
    for relpath in _manifest_filenames_from_pattern(
            driver.storage.manifest_pattern['path'],
            storage.params['backend-id'],
            container_expanded_paths=container_expanded_paths):
        driver.makedirs(relpath.parent)
        relpath = driver.write_file(relpath, data)
    assert relpath is not None
    return driver.storage_backend.get_url_for_path(relpath)

def _publish_container_to_driver(
        client: _client.Client,
        driver: _search.StorageDriver,
        container: _container.Container):
    data = client.session.dump_container(container)

    relpath = None
    for relpath in _manifest_filenames_from_pattern(
            driver.storage.manifest_pattern['path'],
            container.ensure_uuid(),
            container_expanded_paths=container.expanded_paths):
        driver.makedirs(relpath.parent)
        relpath = driver.write_file(relpath, data)
    assert relpath is not None
    return driver.storage_backend.get_url_for_path(relpath)

def publish_container(client: _client.Client, container: _container.Container) -> None:
    '''
    Publish a container to a container owner by the same user.
    '''

    storage = get_storage_for_publish(client, container.owner)
    assert storage.manifest_pattern['type'] == 'glob'
    with _search.StorageDriver.from_storage(storage) as driver:
        for i in range(len(container.backends)):
            if isinstance(container.backends[i], collections.abc.Mapping):
                continue
            backend = client.load_storage_from_url(
                cast(str, container.backends[i]), container.owner)
            new_url = _publish_storage_to_driver(client, driver, backend,
                container_expanded_paths=container.expanded_paths)
            assert new_url is not None
            container.backends[i] = new_url

        _publish_container_to_driver(client, driver, container)
