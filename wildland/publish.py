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
Stuff related to publishing and unpublishing wildland objects.
"""

import functools
from pathlib import Path, PurePosixPath
from typing import Optional, Generator, List, Set, Tuple

from wildland.wildland_object.wildland_object import WildlandObject, PublishableWildlandObject
from .client import Client
from .storage_backends.base import StorageBackend
from .user import User
from .container import Container
from .exc import WildlandError
from .manifest.manifest import ManifestError, Manifest
from .storage_driver import StorageDriver
from .log import get_logger

logger = get_logger('publish')


class Publisher:
    # Between two publish operations, things might have changed:
    # - different wildland object paths,
    # - different set of storages (for Container object).
    # Things that (we assume) didn't change:
    # - wildland object's primary (ie. uuid) path,
    # - manifest-pattern,
    # - public-url.

    """
    A behavior for publishing and unpublishing manifests
    >>> user: User; client: Client; wl_object: PublishableWildlandObject
    >>> publisher = Publisher(client, user)
    >>> publisher.publish(wl_object)
    >>> publisher.republish(wl_object)
    >>> publisher.unpublish(wl_object)
    """

    def __init__(self, client: Client, user: User, catalog_entry: Optional[Container] = None):
        self.client = client
        self.user = user

        if catalog_entry is not None:
            raise NotImplementedError('choosing catalog entry is not supported')

    @functools.cache
    def _cache(self, obj_type: WildlandObject.Type):
        """
        Return wl object cache instance based on object type
        """
        return _UnpublishedWildlandObjectCache(self.client, obj_type)

    def publish(self, wl_object: PublishableWildlandObject) -> None:
        """
        Publish a Wildland Object to the user's catalog.
        """
        # get first available user catalog storage
        catalog_storage = next(Publisher.get_catalog_storages(self.client, self.user))
        catalog_storage.add_child(self.client, wl_object)
        self._cache(wl_object.type).remove(wl_object)

    def unpublish(self, wl_object: PublishableWildlandObject) -> None:
        """
        Unpublish a Wildland Object to the user's catalog.
        """
        for catalog_storage in Publisher.get_catalog_storages(self.client, self.user):
            catalog_storage.remove_child(self.client, wl_object)
        self._cache(wl_object.type).add(wl_object)

    def republish(self, wl_object: PublishableWildlandObject) -> None:
        """
        If the manifest is already published, republish it in the same manifest catalog.
        """
        published = []
        try:
            for catalog_storage in Publisher.get_catalog_storages(self.client, self.user):
                if catalog_storage.has_child(wl_object.get_primary_publish_path()):
                    published.append(catalog_storage)
        except WildlandError:
            pass

        for catalog_storage in published:
            catalog_storage.add_child(self.client, wl_object)

        if published:
            self._cache(wl_object.type).remove(wl_object)

    @staticmethod
    def list_unpublished_objects(client: Client, obj_type: WildlandObject.Type) -> List[str]:
        """
        Return list of unpublished wl objects of a given type
        """
        not_published = list(_UnpublishedWildlandObjectCache(
            client,
            obj_type
        ).load_cache())

        return not_published

    @staticmethod
    def is_published(client: Client, owner: str, uuid_path: PurePosixPath) -> bool:
        """
        Check if the wildland object is published in any storage.
        """
        user = client.load_object_from_name(WildlandObject.Type.USER, owner)
        try:
            for storage in Publisher.get_catalog_storages(client, user, writable_only=False):
                if storage.has_child(uuid_path):
                    return True
        except WildlandError:
            pass
        return False

    @staticmethod
    def get_catalog_storages(client: Client, owner: User, writable_only: bool = True) \
            -> Generator[StorageBackend, None, None]:
        """
        Iterate over all suitable storages to publish a Wildland Object manifest.
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

                    if writable_only and not storage_candidate.is_writeable:
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


class _UnpublishedWildlandObjectCache:
    """
    Helper class: caching paths of unpublished wildland objects in '.unpublished' file.

    To avoid loading all wildland objects and checking where are published every
    time during mounting. Caching unpublished wildland objects seems better than
    published ones since publishable wildland objects are published by default.
    """

    def __init__(self, client: Client, obj_type: WildlandObject.Type):
        self.client = client
        self.obj_type = obj_type
        self.file: Path = client.dirs[obj_type] / '.unpublished'

    def load_cache(self) -> Set[str]:
        """
        Return updated cache content.
        """
        if self._is_invalid():
            self._update()
        return self._load()

    def add(self, wl_object: PublishableWildlandObject) -> None:
        """
        Cache wildland object's local path (if exist).
        """
        to_add = self._get_changed(wl_object)
        if not to_add:
            return
        cache = self._load()
        cache.add(str(to_add))
        self._save(cache)

    def remove(self, wl_object: PublishableWildlandObject) -> None:
        """
        Remove wildland object's local path (if exist) from cache.
        """
        to_remove = self._get_changed(wl_object)
        if not to_remove:
            return
        cache = self._load()
        cache.discard(str(to_remove))
        self._save(cache)

    def _get_changed(self, wl_object: PublishableWildlandObject) -> Optional[Path]:
        path = wl_object.local_path
        if not path:
            return None

        changed = self.client.dirs[self.obj_type] / path
        if not changed.exists():
            # we tried to modify a file that's not actually in the local dir
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
        wl_objects = self._load_all_object_manifests()

        cache = set()
        for path, publish_path, owner in wl_objects:
            user = self.client.load_object_from_name(WildlandObject.Type.USER, owner)
            # ensure that a user has a catalog where we can actually publish the objects
            if publish_path and user.has_catalog and \
                    not Publisher.is_published(self.client, owner, publish_path):
                cache.add(str(path))

        self._save(cache)

    def _load_all_object_manifests(self) \
            -> Generator[Tuple[Path, Optional[PurePosixPath], str], None, None]:
        for path in sorted(self.file.parent.glob('*.yaml')):
            try:
                wl_object = self.client.load_object_from_name(
                    self.obj_type,
                    str(path)
                )

                assert isinstance(wl_object, PublishableWildlandObject)
                assert isinstance(wl_object.manifest, Manifest)

                publish_path = wl_object.get_primary_publish_path()
                owner = wl_object.manifest.owner

            except WildlandError as e:
                logger.warning('error loading %s manifest: %s: %s',
                               self.obj_type.value, path, e)
            else:
                yield path, publish_path, owner
