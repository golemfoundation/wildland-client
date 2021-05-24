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

import logging
import pathlib
from typing import Optional, Generator

from wildland.wildland_object.wildland_object import WildlandObject
from .client import Client
from .container import Container
from .exc import WildlandError
from .manifest.manifest import ManifestError
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
    # - base-url.

    """
    A behavior for publishing and unpublishing manifests

    >>> Publisher(client, container1).publish_manifest()
    >>> Publisher(client, container2).unpublish_manifest()
    """
    def __init__(self, client: Client, container: Container,
            infrastructure: Optional[Container] = None):
        self.client = client
        self.container = container

        if infrastructure is not None:
            raise NotImplementedError(
                'choosing infrastructure is not supported')

        self.container_uuid_path = self.container.uuid_path

    def publish_container(self) -> None:
        """
        Publish the manifest
        """
        _StoragePublisher(self, next(self._get_storages_for_publish())
            ).publish_container(False)

    def unpublish_container(self) -> None:
        """
        Unpublish the manifest
        """
        for storage in self._get_storages_for_publish():
            _StoragePublisher(self, storage).publish_container(True)

    def _get_storages_for_publish(self) -> Generator[Storage, None, None]:
        '''
        Iterate over all suitable storages to publish container manifest.
        '''
        owner = self.client.load_object_from_name(WildlandObject.Type.USER, self.container.owner)

        ok = False
        rejected = []

        for container_candidate in owner.load_infrastractures():
            try:
                all_storages = list(
                    self.client.all_storages(container=container_candidate))

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
    be attempted from all viable infra containers to avoid a situation when user
    commands an unpublish, we find no manifests at some container and report to
    user that there no manifests, which would obviously be wrong.
    """

    def __init__(self, publisher: Publisher, infra_storage: Storage):
        self.client = publisher.client
        self.container = publisher.container
        self.container_uuid_path = publisher.container_uuid_path

        # TODO this requires a more subtle manifest-pattern rewrite including more types
        # of writeable and publisheable-to storages
        self.infra_storage = infra_storage
        assert self.infra_storage.params['manifest-pattern']['type'] == 'glob'
        self.pattern = self.infra_storage.params['manifest-pattern']['path']

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
        yield pathlib.PurePosixPath(
            path_pattern.replace('{path}', str(self.container_uuid_path.relative_to('/')))
        ).relative_to('/')

        if '{path}' in path_pattern:
            for path in container.expanded_paths:
                if path == self.container_uuid_path:
                    continue
                yield pathlib.PurePosixPath(path_pattern.replace(
                    '{path}', str(path.relative_to('/')))).relative_to('/')

    def publish_container(self, just_unpublish: bool) -> None:
        """
        Publish a container to a container owner by the same user.
        """
        # Marczykowski-Górecki's Algorithm:
        # 1) choose infrastructure container from container owner
        #    - if the container was published earlier, the same infrastructure
        #      should be chosen; this will make sense when user will be able to
        #      choose to which infrastructure the container should be published
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

        with StorageDriver.from_storage(self.infra_storage) as driver:
            # replace old relative URLs with new, better URLs
            for backend in self.container.load_backends(include_inline=False):
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
