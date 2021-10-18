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
Utilities for URL resolving and traversing the path
"""

from __future__ import annotations
from copy import deepcopy

import types
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional, Tuple, Iterable, Mapping, List, Set, Union, Dict
from typing import TYPE_CHECKING

import wildland
from wildland.wildland_object.wildland_object import WildlandObject
from .fs_client import WildlandFSClient
from .storage_driver import StorageDriver
from .user import User
from .container import Container
from .bridge import Bridge
from .storage import Storage
from .storage_backends.base import StorageBackend
from .manifest.manifest import ManifestError
from .wlpath import WildlandPath, PathError
from .exc import WildlandError
from .log import get_logger

if TYPE_CHECKING:
    import wildland.client  # pylint: disable=cyclic-import

logger = get_logger('search')


@dataclass
class Step:
    """
    A single step of a resolved path.
    """

    # Owner of the current manifest
    owner: str

    # Client with the current key loaded
    client: wildland.client.Client

    # Container
    container: Optional[Container]

    # Bridge, if bridge is used at this step
    bridge: Optional[Bridge]

    # User, if we're changing users at this step
    user: Optional[User]

    # Previous step, if any
    previous: Optional['Step']

    # file pattern used to lookup the next step (if any)
    pattern: Optional[PurePosixPath] = None

    def steps_chain(self):
        """Iterate over all steps leading to this resolved path"""
        step: Optional[Step] = self
        while step is not None:
            yield step
            step = step.previous

    def __eq__(self, other):
        if not isinstance(other, Step):
            return NotImplemented
        return (self.owner == other.owner and
                self.bridge == other.bridge and
                self.user == other.user and
                self.container == other.container
        )

    def __hash__(self):
        return hash((
            self.owner,
            self.user,
            self.bridge,
            self.container
        ))

class Search:
    """
    A class for traversing a Wildland path.

    Usage:

    .. code-block:: python

        search = Search(client, wlpath, client.config.aliases)
        search.read_file()
    """

    #: cache of results of (Step, part) resolve, shared between different Search instances;
    #: for initial step, the first element is initial_owner field
    _resolve_cache: Dict[Tuple[Union[str, Step], PurePosixPath], Iterable[Step]] = {}

    def __init__(self,
            client: wildland.client.Client,
            wlpath: WildlandPath,
            aliases: Mapping[str, str] = types.MappingProxyType({}),
            fs_client: Optional[WildlandFSClient] = None):
        self.client = client
        self.wlpath = wlpath
        self.aliases = aliases
        self.initial_owner = self._subst_alias(wlpath.owner or '@default')
        self.fs_client = fs_client

        self.local_containers = list(self.client.load_all(WildlandObject.Type.CONTAINER))
        self.local_users = self.client.get_local_users(reload=True)
        self.local_bridges = self.client.get_local_bridges(reload=True)

    def resolve_raw(self) -> Iterable[Step]:
        """
        Resolve the non-file part of the wildland path and yield raw resolution results.

        :return: result of path resolution, may be multiple entries
        """
        yield from self._resolve_all()

    def read_container(self) -> Iterable[Container]:
        """
        Yield all containers matching the given WL path.
        """
        if self.wlpath.file_path is not None:
            raise PathError(f'Expecting a container path, not a file path: {self.wlpath}')

        for step in self._resolve_all():
            if step.container:
                yield step.container

    def read_bridge(self) -> Iterable[Bridge]:
        """
        Yield all bridges matching the given WL path.
        """
        if self.wlpath.file_path is not None:
            raise PathError(f'Expecting an object path, not a file path: {self.wlpath}')

        for step in self._resolve_all():
            if step.bridge and not step.container:
                self.client.recognize_users_from_search(step)
                yield step.bridge

    def read_file(self) -> bytes:
        """
        Read a file under the Wildland path.
        """

        # If there are multiple containers, this method uses the first
        # one. Perhaps it should try them all until it finds a container where
        # the file exists.

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        for step in self._resolve_all():
            if not step.container:
                continue
            try:
                _, storage_backend = self._find_storage(step)
            except ManifestError:
                continue
            with StorageDriver(storage_backend) as driver:
                try:
                    return driver.read_file(self.wlpath.file_path.relative_to('/'))
                except FileNotFoundError:
                    continue

        raise FileNotFoundError

    def write_file(self, data: bytes, create_parents: bool = False):
        """
        Read a file under the Wildland path.
        """

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        for step in self._resolve_all():
            if not step.container:
                continue
            try:
                _, storage_backend = self._find_storage(step)
            except ManifestError:
                continue
            try:
                with StorageDriver(storage_backend) as driver:
                    if create_parents:
                        driver.makedirs(self.wlpath.file_path.parent)
                    return driver.write_file(self.wlpath.file_path.relative_to('/'), data)
            except FileNotFoundError:
                continue

        raise PathError(f'Container not found for path: {self.wlpath}')

    @classmethod
    def clear_cache(cls):
        """
        Clear path resolution cache.

        Calling this method is necessary, if it's necessary to re-download
        user's manifests catalog content during lifetime of the same process.
        This may be the case for example after (re)publishing some new container.
        """
        cls._resolve_cache.clear()

    def _get_params_for_mount_step(self, step: Step) -> \
            Tuple[PurePosixPath,
                  Optional[Tuple[Container,
                                 Iterable[Storage],
                                 Iterable[PurePosixPath],
                                 Optional[Container]]]]:
        """
        Return a FUSE mount command for a container for given step (if not mounted already).

        :param step:
        :return: a mount path and params to mount (if necessary)
        """
        assert step.container is not None
        assert self.fs_client is not None
        storage = self.client.select_storage(step.container)
        fuse_path = self.fs_client.get_primary_unique_mount_path(step.container, storage)
        if list(self.fs_client.find_all_storage_ids_for_path(fuse_path)):
            # already mounted
            return fuse_path, None
        mount_params: Tuple[Container,
                            Iterable[Storage],
                            Iterable[PurePosixPath],
                            Optional[Container]] = (step.container, [storage], [], None)
        return fuse_path, mount_params

    def get_watch_params(self) -> Tuple[List, Set[PurePosixPath]]:
        """
        Prepare parameters required to watch given WL path for changes
        (including any container involved in path resolution).

        This function returns a tuple of:
         - list of mount parameters (for WildlandFSClient.mount_multiple_containers())
         - set of patterns (relative to the FUSE mount point) to watch

        Watching the patterns is legal only if all returned mount commands succeeded.

        Usage:
        >>> client = wildland.client.Client()
        >>> fs_client = client.fs_client
        >>> search = Search(...)
        >>> mount_cmds, patterns = search.get_watch_params()
        >>> try:
        >>>     # mounting under unique paths only is enough, no need to pollute user's forest
        >>>     fs_client.mount_multiple_containers(mount_cmds, unique_path_only=True)
        >>>     for events in fs_client.watch(patterns):
        >>>         ...
        >>> except:
        >>>     ...
        """
        if self.fs_client is None:
            raise WildlandError('get_watch_params requires fs_client')

        mount_cmds = {}
        patterns_for_path = set()
        for final_step in self._resolve_all():
            if final_step.container is None:
                continue
            if self.wlpath.file_path is not None:
                final_step.pattern = self.wlpath.file_path
            for step in final_step.steps_chain():
                if step.pattern is None or step.container is None:
                    continue
                mount_path, mount_params = self._get_params_for_mount_step(step)
                if mount_params:
                    mount_cmds[mount_path] = mount_params
                patterns_for_path.add(
                    mount_path / step.pattern.relative_to(PurePosixPath('/')))

        return list(mount_cmds.values()), patterns_for_path

    def _resolve_all(self) -> Iterable[Step]:
        """
        Resolve all path parts, yield all results that match.
        """

        # deduplicate results
        seen_last = set()
        # deduplicate and cache result of self._resolve_first(); it's here,
        # because _resolve_first() structure does not have a single place for
        # returning results, and is using `yield from`, so deduplicating it
        # there would require quite a bit of boilerplate there
        seen_first = set()
        cache_key = (self.initial_owner, self.wlpath.parts[0])
        if cache_key in self._resolve_cache:
            first_iter = self._resolve_cache[cache_key]
        else:
            first_iter = self._resolve_first()
        for step in first_iter:
            if step in seen_first:
                continue
            seen_first.add(step)
            for last_step in self._resolve_rest(step, 1):
                if last_step not in seen_last:
                    yield last_step
                    seen_last.add(last_step)
        self._resolve_cache[cache_key] = seen_first

    def _resolve_rest(self, step: Step, i: int) -> Iterable[Step]:
        if i == len(self.wlpath.parts):
            yield step
            return

        seen = set()
        cache_key = (step, self.wlpath.parts[i])
        if cache_key in self._resolve_cache:
            next_steps = self._resolve_cache[cache_key]
        else:
            next_steps = self._resolve_next(step, i)
        for next_step in next_steps:
            if next_step in seen:
                continue
            seen.add(next_step)
            yield from self._resolve_rest(next_step, i+1)
        self._resolve_cache[cache_key] = seen

    def _find_storage(self, step: Step) -> Tuple[Storage, StorageBackend]:
        """
        Find a storage for the latest resolved part.

        If self.fs_client is set and the container is mounted,
        returns a local storage backend pointing at mounted FUSE dir.

        Returns (storage, storage_backend).
        """

        assert step.container is not None
        storage = self.client.select_storage(step.container)
        return storage, StorageBackend.from_params(storage.params, deduplicate=True)

    def _resolve_first(self):
        if self.wlpath.hint:
            hint_user = self.client.load_object_from_url(WildlandObject.Type.USER, self.wlpath.hint,
                                                         self.initial_owner, self.initial_owner)

            for step in self._user_step(hint_user, self.initial_owner, self.client, None, None):
                yield from self._resolve_next(step, 0)

        # Try local containers
        yield from self._resolve_local(self.wlpath.parts[0], self.initial_owner, None)

        # Try user's manifests catalog
        for user in self.local_users:
            if user.owner == self.initial_owner:
                for step in self._user_step(user, self.initial_owner, self.client, None, None):
                    yield from self._resolve_next(step, 0)

    def _resolve_local(self, part: PurePosixPath,
                       owner: str,
                       step: Optional[Step]) -> Iterable[Step]:
        """
        Resolve a path part based on locally stored manifests, in the context
        of a given owner.
        """

        for container in self.local_containers:
            if container.owner == owner and (
                    str(part) == '*' or
                    part in container.expanded_paths):

                logger.debug('%s: local container: %s', part,
                            container.local_path)
                yield Step(
                    owner=self.initial_owner,
                    client=self.client,
                    container=container,
                    user=None,
                    bridge=None,
                    previous=step,
                )

        for bridge in self.local_bridges:
            if bridge.owner == owner and (str(part) == '*' or part in bridge.paths):
                logger.debug('%s: local bridge manifest: %s', part,
                            bridge.local_path)
                yield from self._bridge_step(
                    self.client, owner, part, None, None, bridge, step)

    def _resolve_next(self, step: Step, i: int) -> Iterable[Step]:
        """
        Resolve next part by looking up a manifest in the current container.
        """

        if not step.container:
            return

        part = self.wlpath.parts[i]

        # Try local paths first
        yield from self._resolve_local(part, step.owner, step)

        storage, storage_backend = self._find_storage(step)

        try:
            pattern = storage_backend.get_subcontainer_watch_pattern(part)
            step.pattern = pattern
        except NotImplementedError:
            logger.warning('Storage %s does not support watching', storage.params["type"])

        with storage_backend:
            try:
                children_iter = storage_backend.get_children(step.client, part)
            except NotImplementedError:
                logger.warning('Storage %s does not subcontainers - cannot look for %s inside',
                            storage.params["type"], part)
                return

            for manifest_path, subcontainer_data in children_iter:
                try:
                    container_or_bridge = step.client.load_subcontainer_object(
                        step.container, storage, subcontainer_data)
                except ManifestError as me:
                    logger.warning('%s: cannot load subcontainer %s: %s', part, manifest_path, me)
                    continue

                if isinstance(container_or_bridge, Container):
                    if container_or_bridge == step.container:
                        # manifests catalog published into itself
                        container_or_bridge.is_manifests_catalog = True
                    logger.info('%s: container manifest: %s', part, subcontainer_data)
                    yield from self._container_step(
                        step, part, container_or_bridge)
                elif isinstance(container_or_bridge, Bridge):
                    logger.info('%s: bridge manifest: %s', part, subcontainer_data)
                    yield from self._bridge_step(
                        step.client, step.owner,
                        part, manifest_path, storage_backend,
                        container_or_bridge,
                        step)

    # pylint: disable=no-self-use

    def _container_step(self,
                        step: Step,
                        part: PurePosixPath,
                        container: Container) -> Iterable[Step]:

        try:
            self._verify_owner(container, step.owner)
        except WildlandError as e:
            logger.warning('container %s of user %s: %s', container, step.owner, str(e))
            return

        if str(part) != '*' and part not in container.expanded_paths:
            logger.debug('%s: path not found in manifest, skipping', part)
            return

        yield Step(
            owner=step.owner,
            client=step.client,
            container=container,
            user=None,
            bridge=None,
            previous=step,
        )

    def _bridge_step(self,
                     client: wildland.client.Client,
                     owner: str,
                     part: PurePosixPath,
                     manifest_path: Optional[PurePosixPath],
                     storage_backend: Optional[StorageBackend],
                     bridge: Bridge,
                     step: Optional[Step]) -> Iterable[Step]:

        self._verify_owner(bridge, owner)

        if str(part) != '*' and part not in bridge.paths:
            return

        next_client, next_owner = client.sub_client_with_key(bridge.user_pubkey)

        location = deepcopy(bridge.user_location)
        if isinstance(location, str):
            if location.startswith('./') or location.startswith('../'):

                if not (manifest_path and storage_backend):
                    logger.warning(
                        'local bridge manifest with relative location, skipping')
                    return

                # Treat location as relative path
                user_manifest_path = manifest_path.parent / location
                try:
                    with StorageDriver(storage_backend) as driver:
                        user_manifest_content = driver.read_file(user_manifest_path)
                except IOError as e:
                    logger.warning('Could not read local user manifest %s: %s',
                                   user_manifest_path, e)
                    return
                logger.debug('%s: local user manifest: %s',
                             part, user_manifest_path)
            else:
                # Treat location as URL
                try:
                    user_manifest_content = client.read_from_url(location, owner)
                except WildlandError as e:
                    logger.warning('Could not read user manifest %s: %s',
                                   location, e)
                    return
                logger.debug('%s: remote user manifest: %s',
                             part, location)
            try:
                user = next_client.load_object_from_bytes(WildlandObject.Type.USER,
                                                          user_manifest_content)
            except WildlandError as e:
                logger.warning('Could not load user manifest %s: %s',
                               location, e)
                return

        else:
            try:
                user = next_client.load_object_from_dict(WildlandObject.Type.USER, location,
                                                         expected_owner=next_owner)
            except (WildlandError, FileNotFoundError) as ex:
                logger.warning('cannot load bridge to [%s]', bridge.paths[0])
                logger.debug('cannot load linked user manifest: %s. Exception: %s',
                             location, str(ex))
                return
        assert isinstance(user, User)
        next_client.recognize_users_and_bridges([user], [bridge])
        yield from self._user_step(
            user, next_owner, next_client, bridge, step)

    def _user_step(self,
                   user: User,
                   owner: str,
                   client: wildland.client.Client,
                   current_bridge: Optional[Bridge],
                   step: Optional[Step]) -> Iterable[Step]:

        self._verify_owner(user, owner)
        yield Step(
            owner=user.owner,
            client=client,
            container=None,
            user=user,
            bridge=current_bridge,
            previous=step,
        )

        for container in user.load_catalog(warn_about_encrypted_manifests=False):
            if container.owner != user.owner:
                logger.warning('Unexpected owner for %s: %s (expected %s)',
                               container, container.owner, user.owner)
                continue

            logger.info("user's container manifest: %s", container)

            yield Step(
                owner=user.owner,
                client=client,
                container=container,
                user=user,
                bridge=current_bridge,
                previous=step,
            )

    def _verify_owner(self, obj, expected_owner):
        if obj.owner != expected_owner:
            raise PathError(
                'Unexpected owner for manifest: {} (expected {})'.format(
                    obj.owner, expected_owner
                ))

    def _subst_alias(self, alias):
        if not alias[0] == '@':
            return alias

        try:
            return self.aliases[alias[1:]]
        except KeyError as ex:
            raise PathError(f'Unknown alias: {alias}') from ex
