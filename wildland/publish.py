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
from .container import Container
from .exc import WildlandError
from .manifest.manifest import ManifestError, Manifest
from .storage_driver import StorageDriver
from .storage import Storage

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

    >>> Publisher(client, container1).publish_manifest()
    >>> Publisher(client, container2).unpublish_manifest()
    """
    def __init__(self, client: Client, container: Container,
                 catalog_entry: Optional[Container] = None):
        self.client = client
        self.container = container

        if catalog_entry is not None:
            raise NotImplementedError(
                'choosing catalog entry is not supported')

        self.container_uuid_path = self.container.uuid_path

    def publish_container(self) -> None:
        """
        Publish the manifest
        """
        infra_storage = next(_InfraChecker.get_storages_for_publish(
            self.client, self.container.owner))
        _StoragePublisher(self, infra_storage).publish_container()
        if self.container.local_path:
            _PublisherCache(self.client).remove(self.container.local_path)

    def unpublish_container(self) -> None:
        """
        Unpublish the manifest
        """
        for storage in _InfraChecker.get_storages_for_publish(self.client, self.container.owner):
            _StoragePublisher(self, storage).unpublish_container()
        if self.container.local_path:
            _PublisherCache(self.client).add(self.container.local_path)

    def republish_container(self) -> None:
        """
        If the manifest is already published, republish it in the same manifest catalog.
        """
        published = []
        try:
            for storage in _InfraChecker.get_storages_for_publish(
                    self.client, self.container.owner):
                if _InfraChecker.is_published_in_storage(storage, self.container_uuid_path):
                    published.append(storage)
        except WildlandError:
            pass

        for storage in published:
            _StoragePublisher(self, storage).publish_container()

        if published and self.container.local_path:
            _PublisherCache(self.client).remove(self.container.local_path)

    @staticmethod
    def list_unpublished_containers(client) -> List[str]:
        """
        Return list of unpublished containers for given client.
        """
        not_published = list(_PublisherCache(client).load_cache())
        return not_published


class _InfraChecker:
    """
    Helper class: checking which container has been published and finding
    suitable storages to publish the container manifest.

    Group of static methods used in Publisher and _PublisherCache.
    """

    @staticmethod
    def is_published(client: Client, owner: str, container_uuid_path: PurePosixPath) -> bool:
        """
        Check if the container is published in any storage.
        """
        try:
            for storage in _InfraChecker.get_storages_for_publish(client, owner):
                if _InfraChecker.is_published_in_storage(storage, container_uuid_path):
                    return True
        except WildlandError:
            pass
        return False

    @staticmethod
    def is_published_in_storage(infra_storage: Storage,
                                container_uuid_path: PurePosixPath) -> bool:
        """
        Check if the container is published in given manifest catalog storage.
        """
        assert infra_storage.params['manifest-pattern']['type'] == 'glob'
        pattern = infra_storage.params['manifest-pattern']['path']

        path_pattern = pattern.replace('*', container_uuid_path.name)

        container_relpath = PurePosixPath(
            path_pattern.replace('{path}', str(container_uuid_path.relative_to('/')))
        ).relative_to('/')

        with StorageDriver.from_storage(infra_storage) as driver:
            try:
                driver.read_file(container_relpath)
                return True
            except FileNotFoundError:
                return False

    @staticmethod
    def get_storages_for_publish(client: Client, container_owner: str
                                 ) -> Generator[Storage, None, None]:
        """
        Iterate over all suitable storages to publish container manifest.
        """
        owner = client.load_object_from_name(WildlandObject.Type.USER, container_owner)

        ok = False
        rejected = []

        for container_candidate in owner.load_catalog():
            try:
                all_storages = list(
                    client.all_storages(container=container_candidate))

                if not all_storages:
                    rejected.append(
                        f'container {container_candidate.uuid} '
                        'has no available storages')
                    continue

                for storage_candidate in all_storages:
                    if 'manifest-pattern' not in storage_candidate.params or \
                            storage_candidate.params['manifest-pattern']['type'] != 'glob':
                        rejected.append(
                            f'storage {storage_candidate.params["backend-id"]} of '
                            f'container {container_candidate.uuid} '
                            'does not have manifest_pattern')
                        continue

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
                        with StorageDriver.from_storage(storage_candidate) as _driver:
                            ok = True
                            yield storage_candidate

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
            raise WildlandError(
                'Cannot find any container suitable as publishing platform:'
                + ''.join(f'\n- {i}' for i in rejected))


class _StoragePublisher:
    """
    Helper class: publish/unpublish for a single storage

    This is because publishing is done to single storage, but unpublish should
    be attempted from all viable manifests catalog entries to avoid a situation when user
    commands an unpublish, we find no manifests in some container and report to
    user that there no manifests, which would obviously be wrong.
    """

    def __init__(self, publisher: Publisher, catalog_storage: Storage):
        self.client = publisher.client
        self.container = publisher.container
        self.container_uuid_path = publisher.container_uuid_path

        # TODO this requires a more subtle manifest-pattern rewrite including more types
        # of writeable and publishable-to storages
        self.catalog_storage = catalog_storage
        assert self.catalog_storage.params['manifest-pattern']['type'] == 'glob'
        self.pattern = self.catalog_storage.params['manifest-pattern']['path']

    def _get_relpath_for_storage_manifest(self, backend_id):
        # we publish only a single manifest for a storage, under `/.uuid/` path
        container_manifest = next(
            self._get_relpaths_for_container_manifests(self.container))
        return container_manifest.with_name(
            container_manifest.name.removesuffix('.yaml')
            + f'.{backend_id}.yaml'
        )

    def _get_relpaths_for_container_manifests(self, container):
        path_pattern = self.pattern.replace('*', container.uuid)

        # always return /.uuid/ path first
        yield PurePosixPath(
            path_pattern.replace('{path}', str(self.container_uuid_path.relative_to('/')))
        ).relative_to('/')

        if '{path}' in path_pattern:
            for path in container.expanded_paths:
                if path == self.container_uuid_path:
                    continue
                yield PurePosixPath(path_pattern.replace(
                    '{path}', str(path.relative_to('/')))).relative_to('/')

    def unpublish_container(self) -> None:
        """
        Unpublish a container from a container owner.
        """
        self.publish_container(just_unpublish=True)

    def publish_container(self, just_unpublish: bool = False) -> None:
        """
        Publish a container to a container owner by the same user.
        """
        # Marczykowski-Górecki's Algorithm:
        # 1) choose manifests catalog entry from container owner
        #    - if the container was published earlier, the same entry
        #      should be chosen; this will make sense when user will be able to
        #      choose to which catalog entry the container should be published
        # 2) generate all new relpaths for the container and storages
        # 3) try to fetch container from new relpaths; check if the file
        #    contains the same container; if yes, generate relpaths for old
        #    paths
        # 4) remove old copies of manifest for container and storages (only
        #    those that won't be overwritten later)
        # 5) post new storage manifests
        # 6) post new container manifests starting with /.uuid/ one
        #
        # For unpublishing, instead of 4), 5) and 6), all manifests are removed
        # from relpaths and no new manifests are published.

        container_relpaths = list(
            self._get_relpaths_for_container_manifests(self.container))
        storage_relpaths = {}
        old_relpaths_to_remove = set()

        with StorageDriver.from_storage(self.catalog_storage) as driver:
            # replace old relative URLs with new, better URLs
            for backend in self.container.load_storages(include_inline=False):
                relpath = self._get_relpath_for_storage_manifest(backend.backend_id)
                assert relpath not in storage_relpaths
                storage_relpaths[relpath] = backend
                self.container.add_storage_from_obj(
                    backend, inline=False, new_url=driver.storage_backend.get_url_for_path(relpath))

            # fetch from /.uuid path
            try:
                old_container_manifest_data = driver.read_file(container_relpaths[0])
            except FileNotFoundError:
                pass
            else:
                old_container = self.client.load_object_from_bytes(
                    WildlandObject.Type.CONTAINER, old_container_manifest_data)
                assert isinstance(old_container, Container)

                if not old_container.uuid == self.container.uuid:
                    # we just downloaded this file from container_relpaths[0], so
                    # things are very wrong here
                    raise WildlandError(
                        f'old version of container manifest at storage '
                        f'{driver.storage.params["backend-id"]} has serious '
                        f'problems; please remove it manually')

                old_relpaths_to_remove.update(set(
                    self._get_relpaths_for_container_manifests(old_container)))
                for url in old_container.load_raw_backends(include_inline=False):
                    old_relpaths_to_remove.add(
                        driver.storage_backend.get_path_for_url(url))

            if just_unpublish:
                old_relpaths_to_remove.update(container_relpaths)
                old_relpaths_to_remove.update(storage_relpaths)
            else:
                old_relpaths_to_remove.difference_update(container_relpaths)
                old_relpaths_to_remove.difference_update(storage_relpaths)

            # remove /.uuid path last, if present (bool sorts False < True)
            for relpath in sorted(old_relpaths_to_remove,
                                  key=(lambda path: path.parts[:2] == ('/', '.uuid'))):
                try:
                    driver.remove_file(relpath)
                except FileNotFoundError:
                    pass

            if not just_unpublish:
                for relpath, storage in storage_relpaths.items():
                    driver.makedirs(relpath.parent)
                    driver.write_file(relpath, self.client.session.dump_object(storage))

                for relpath in container_relpaths:
                    driver.makedirs(relpath.parent)
                    driver.write_file(relpath, self.client.session.dump_object(self.container))


class _PublisherCache:
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

    def add(self, path: Path) -> None:
        """
        Cache path.
        """
        to_add = self.client.dirs[WildlandObject.Type.CONTAINER] / path
        if not to_add.exists():
            # we tried to add a file that's not actually in the containers/ dir
            return
        if self._is_invalid(ignore=to_add):
            self._update()
        cache = self._load()
        cache.add(str(to_add))
        self._save(cache)

    def remove(self, path: Path) -> None:
        """
        Remove path from cache.
        """
        to_remove = self.client.dirs[WildlandObject.Type.CONTAINER] / path
        if not to_remove.exists():
            # we tried to remove a file that's not actually in the containers/ dir
            return
        if self._is_invalid(ignore=to_remove):
            self._update()
        cache = self._load()
        cache.discard(str(to_remove))
        self._save(cache)

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
                    not _InfraChecker.is_published(self.client, owner, uuid):
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
