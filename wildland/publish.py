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
Stuff related to publishing and unpublishing containers.
"""

import logging
from pathlib import Path, PurePosixPath
from typing import Optional, Generator, List, Set, Tuple

from wildland.wildland_object.wildland_object import WildlandObject
from .client import Client
from .storage_backends.base import StorageBackend
from .user import User
from .container import Container
from .exc import WildlandError
from .manifest.manifest import ManifestError, Manifest
from .storage_driver import StorageDriver

logger = logging.getLogger('publish')


class Publisher:
    # Between two publish operations, things might have changed:
    # - different container paths,
    # - different set of storages.
    # Things that (we assume) didn't change:
    # - container uuid,
    # - manifest-pattern,
    # - public-url.

    """
    A behavior for publishing and unpublishing manifests
    >>> user: User; client: Client; container: Container
    >>> publisher = Publisher(client, user)
    >>> publisher.publish_container(container)
    >>> publisher.republish_container(container)
    >>> publisher.unpublish_container(container)
    """
    def __init__(self, client: Client, user: User, catalog_entry: Optional[Container] = None):
        self.client = client
        self.user = user
        self.cache = _UnpublishedContainersCache(self.client)

        if catalog_entry is not None:
            raise NotImplementedError('choosing catalog entry is not supported')

    def publish_container(self, container: Container) -> None:
        """
        Publish the container manifest to user catalog.
        """
        # get first available user catalog storage
        catalog_storage = next(Publisher.get_catalog_storages(self.client, self.user))
        catalog_storage.add_child(self.client, container)
        self.cache.remove(container)

    def unpublish_container(self, container: Container) -> None:
        """
        Unpublish the manifest from user catalog.
        """
        for catalog_storage in Publisher.get_catalog_storages(self.client, self.user):
            catalog_storage.remove_child(self.client, container)
        self.cache.add(container)

    def republish_container(self, container: Container) -> None:
        """
        If the manifest is already published, republish it in the same manifest catalog.
        """
        published = []
        try:
            for catalog_storage in Publisher.get_catalog_storages(self.client, self.user):
                if catalog_storage.has_child(container.uuid_path):
                    published.append(catalog_storage)
        except WildlandError:
            pass

        for catalog_storage in published:
            catalog_storage.add_child(self.client, container)

        if published:
            self.cache.remove(container)

    @staticmethod
    def list_unpublished_containers(client) -> List[str]:
        """
        Return list of unpublished containers for given client.
        """
        not_published = list(_UnpublishedContainersCache(client).load_cache())
        return not_published

    @staticmethod
    def is_published(client: Client, owner: str, container_uuid_path: PurePosixPath) -> bool:
        """
        Check if the container is published in any storage.
        """
        user = client.load_object_from_name(WildlandObject.Type.USER, owner)
        try:
            for storage in Publisher.get_catalog_storages(client, user):
                if storage.has_child(container_uuid_path):
                    return True
        except WildlandError:
            pass
        return False

    @staticmethod
    def get_catalog_storages(client: Client, owner: User) -> Generator[StorageBackend, None, None]:
        """
        Iterate over all suitable storages to publish container manifest.
        """

        ok = False
        rejected = []

        for container_candidate in owner.load_catalog():
            try:
                all_storages = list(client.all_storages(container=container_candidate))

                if not all_storages:
                    rejected.append(
                        f'container {container_candidate.uuid} '
                        'has no available storages')
                    continue

                for storage_candidate in all_storages:

                    if not storage_candidate.is_writeable:
                        rejected.append(
                            f'storage {storage_candidate.params["backend-id"]} of '
                            f'container {container_candidate.uuid} '
                            'is not writeable')
                        continue

                    # Attempt to mount the storage driver first.
                    # Failure in attempt to mount the backend should try the next storage from the
                    # container and if still not mounted, move to the next container
                    try:
                        with StorageDriver.from_storage(storage_candidate) as driver:
                            if not driver.storage_backend.supports_publish:
                                rejected.append(
                                    f'storage {storage_candidate.params["backend-id"]} of '
                                    f'container {container_candidate.uuid} '
                                    'is not a catalog storage (does not have manifest_pattern)')
                                continue

                            ok = True
                            yield driver.storage_backend

                            # yield at most a single storage for a container
                            break

                    except (WildlandError, PermissionError, FileNotFoundError) as ex:
                        rejected.append(
                            f'storage {storage_candidate.params["backend-id"]} of '
                            f'container {container_candidate.uuid} '
                            f'could not be mounted: {ex!s}')
                        logger.debug(
                            'Failed to mount storage when publishing with '
                            'exception: %s',
                            ex)
                        continue

            except (ManifestError, WildlandError) as ex:
                rejected.append(
                    f'container {repr(container_candidate)} has serious problems: {ex!s}')
                logger.debug(
                    'Failed to load container when publishing with exception: %s', ex)
                continue

        if not ok:
            err_msg = 'Cannot find any container suitable as publishing platform'
            if rejected:
                err_msg += ': ' + ''.join(f'\n- {i}' for i in rejected)
            raise WildlandError(err_msg)


class _UnpublishedContainersCache:
    """
    Helper class: caching paths of unpublished containers in '.unpublished' file.

    To avoid loading all containers and checking where are published every
    time during mounting. Caching unpublished containers seems better than
    published ones since containers are publishing by default.
    """

    def __init__(self, client: Client):
        self.client = client
        self.file: Path = client.dirs[WildlandObject.Type.CONTAINER] / '.unpublished'

    def load_cache(self) -> Set[str]:
        """
        Return updated cache content.
        """
        if self._is_invalid():
            self._update()
        return self._load()

    def add(self, container: Container) -> None:
        """
        Cache container local path (if exist).
        """
        to_add = self._get_changed(container)
        if not to_add:
            return
        cache = self._load()
        cache.add(str(to_add))
        self._save(cache)

    def remove(self, container: Container) -> None:
        """
        Remove container local path (if exist) from cache.
        """
        to_remove = self._get_changed(container)
        if not to_remove:
            return
        cache = self._load()
        cache.discard(str(to_remove))
        self._save(cache)

    def _get_changed(self, container: Container) -> Optional[Path]:
        path = container.local_path
        if not path:
            return None

        changed = self.client.dirs[WildlandObject.Type.CONTAINER] / path
        if not changed.exists():
            # we tried to modify a file that's not actually in the containers/ dir
            return None

        if self._is_invalid(ignore=changed):
            self._update()

        return changed

    def _load(self) -> Set[str]:
        with open(self.file, 'r') as f:
            lines = f.readlines()
            cache = set(line.rstrip() for line in lines)
        return cache

    def _save(self, cache: Set[str]) -> None:
        with open(self.file, 'w') as f:
            f.writelines([path + '\n' for path in cache])

    def _is_invalid(self, ignore: Optional[Path] = None) -> bool:
        if not self.file.exists():
            return True

        manifests = list(self.file.parent.glob('*.yaml'))
        if ignore and ignore in manifests:
            manifests.remove(ignore)
        if not manifests:
            return False

        newest = max(manifests, key=lambda y: y.stat().st_mtime)
        return self.file.stat().st_mtime < newest.stat().st_mtime

    def _update(self) -> None:
        containers = self._load_all_containers_info()

        cache = set()
        for path, uuid, owner in containers:
            user = self.client.load_object_from_name(WildlandObject.Type.USER, owner)
            # ensure that a user has a catalog that we can actually publish containers to it
            if uuid and user.has_catalog and \
                    not Publisher.is_published(self.client, owner, uuid):
                cache.add(str(path))

        self._save(cache)

    def _load_all_containers_info(self) \
            -> Generator[Tuple[Path, Optional[PurePosixPath], str], None, None]:
        for path in sorted(self.file.parent.glob('*.yaml')):
            try:
                data = path.read_bytes()
                manifest = Manifest.from_bytes(data, self.client.session.sig,
                                               allow_only_primary_key=False,
                                               trusted_owner=None, decrypt=True)

                for c_path in manifest.fields['paths']:
                    pure_path = PurePosixPath(c_path)
                    if pure_path.parent == PurePosixPath('/.uuid/'):
                        uuid: Optional[PurePosixPath] = pure_path
                        break
                else:
                    uuid = None

                owner = manifest.fields['owner']

            except WildlandError as e:
                logger.warning('error loading %s manifest: %s: %s',
                               WildlandObject.Type.CONTAINER.value, path, e)
            else:
                yield path, uuid, owner
