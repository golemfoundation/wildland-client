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
# You should have received a copy of the GNU General Public LicenUnkse
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Utilities for URL resolving and traversing the path
"""

from __future__ import annotations

import errno
import logging
import os
import re
import types
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional, Tuple, Iterable, Mapping, List, Set
from typing import TYPE_CHECKING

from .fs_client import WildlandFSClient
from .user import User
from .container import Container
from .bridge import Bridge
from .storage import Storage
from .storage_backends.base import StorageBackend
from .manifest.manifest import ManifestError
from .wlpath import WildlandPath, PathError
from .exc import WildlandError

if TYPE_CHECKING:
    from .client import Client # pylint: disable=cyclic-import

logger = logging.getLogger('search')


@dataclass
class Step:
    """
    A single step of a resolved path.
    """

    # Owner of the current manifest
    owner: str

    # Client with the current key loaded
    client: Client

    # Container
    container: Optional[Container]

    # Bridge, if bridge is used at this step
    bridge: Optional[Bridge]

    # User, if we're changing users at this step
    user: Optional[User]

    # Previous step, if any
    previous: Optional['Step']

    # file pattern used to lookup the next step (if any)
    pattern: Optional[str] = None

    def steps_chain(self):
        """Iterate over all steps leading to this resolved path"""
        step: Optional[Step] = self
        while step is not None:
            yield step
            step = step.previous


class Search:
    """
    A class for traversing a Wildland path.

    Usage:

    .. code-block:: python

        search = Search(client, wlpath, client.config.aliases)
        search.read_file()
    """

    def __init__(self,
            client: Client,
            wlpath: WildlandPath,
            aliases: Mapping[str, str] = types.MappingProxyType({}),
            fs_client: Optional[WildlandFSClient] = None):
        self.client = client
        self.wlpath = wlpath
        self.aliases = aliases
        self.initial_owner = self._subst_alias(wlpath.owner or '@default')
        self.fs_client = fs_client

        self.local_containers = list(self.client.load_containers())
        self.local_users = list(self.client.load_users())
        self.local_bridges = list(self.client.load_bridges())

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
            with storage_backend:
                try:
                    return self.client.storage_read_file(storage_backend,
                                             self.wlpath.file_path.relative_to('/'))
                except FileNotFoundError:
                    continue

        raise FileNotFoundError

    def write_file(self, data: bytes):
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
                    return driver.write_file(self.wlpath.file_path.relative_to('/'), data)
            except FileNotFoundError:
                continue

        raise PathError(f'Container not found for path: {self.wlpath}')

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
        >>> client = Client()
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
                final_step.pattern = str(self.wlpath.file_path)
            for step in final_step.steps_chain():
                if step.pattern is None or step.container is None:
                    continue
                mount_path, mount_params = self._get_params_for_mount_step(step)
                if mount_params:
                    mount_cmds[mount_path] = mount_params
                patterns_for_path.add(
                    mount_path / step.pattern.lstrip('/'))

        return list(mount_cmds.values()), patterns_for_path

    def _resolve_all(self) -> Iterable[Step]:
        """
        Resolve all path parts, yield all results that match.
        """

        for step in self._resolve_first():
            for last_step in self._resolve_rest(step, 1):
                yield last_step

    def _resolve_rest(self, step: Step, i: int) -> Iterable[Step]:
        if i == len(self.wlpath.parts):
            yield step
            return

        for next_step in self._resolve_next(step, i):
            yield from self._resolve_rest(next_step, i+1)

    def _find_storage(self, step: Step) -> Tuple[Storage, StorageBackend]:
        """
        Find a storage for the latest resolved part.

        If self.fs_client is set and the container is mounted,
        returns a local storage backend pointing at mounted FUSE dir.

        Returns (storage, storage_backend).
        """

        assert step.container is not None
        storage = self.client.select_storage(step.container)
        if self.fs_client is not None:
            fuse_path = self.fs_client.get_primary_unique_mount_path(step.container, storage)
            mounted_path = self.fs_client.mount_dir / fuse_path.relative_to('/')
            if mounted_path.exists():
                local_storage = StorageBackend.from_params({
                    'type': 'local',
                    'backend-id': storage.backend_id,
                    'location': mounted_path,
                    'owner': step.container.owner,
                    'is-local-owner': True,
                })
                return storage, local_storage
        return storage, StorageBackend.from_params(storage.params)

    def _resolve_first(self):
        if self.wlpath.hint:
            hint_user = self.client.load_user_from_url(self.wlpath.hint,
                                                       self.initial_owner, self.initial_owner)

            for step in self._user_step(hint_user, self.initial_owner, self.client, None, None):
                yield from self._resolve_next(step, 0)

        # Try local containers
        yield from self._resolve_local(self.wlpath.parts[0], self.initial_owner, None)

        # Try user's infrastructure containers
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
            if (container.owner == owner and
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
            if bridge.owner == owner and part in bridge.paths:
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
        manifest_pattern = storage.manifest_pattern or storage.DEFAULT_MANIFEST_PATTERN
        pattern = get_file_pattern(manifest_pattern, part)
        step.pattern = pattern
        with storage_backend:
            for manifest_path in storage_glob(storage_backend, pattern):
                trusted_owner = None
                if storage.trusted:
                    trusted_owner = storage.owner

                try:
                    manifest_content = self.client.storage_read_file(storage_backend, manifest_path)
                except IOError as e:
                    logger.warning('Could not read %s: %s', manifest_path, e)
                    continue

                container_or_bridge = step.client.session.load_container_or_bridge(
                    manifest_content, trusted_owner=trusted_owner)

                if isinstance(container_or_bridge, Container):
                    logger.info('%s: container manifest: %s', part, manifest_path)
                    yield from self._container_step(
                        step, part, container_or_bridge)
                else:
                    logger.info('%s: bridge manifest: %s', part, manifest_path)
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
                     client: Client,
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

        location = bridge.user_location
        if isinstance(location, str):
            if location.startswith('./') or location.startswith('../'):

                if not (manifest_path and storage_backend):
                    logger.warning(
                        'local bridge manifest with relative location, skipping')
                    return

                # Treat location as relative path
                user_manifest_path = manifest_path.parent / location
                try:
                    user_manifest_content = self.client.storage_read_file(
                        storage_backend, user_manifest_path)
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
                user = next_client.session.load_user(user_manifest_content)
            except WildlandError as e:
                logger.warning('Could not load user manifest %s: %s',
                               location, e)
                return

        else:
            try:
                user = self.client.load_user_from_dict(location, owner)
            except (WildlandError, FileNotFoundError) as ex:
                logger.warning('cannot load linked user manifest: %s. Exception: %s',
                               location, str(ex))
                return

        yield from self._user_step(
            user, next_owner, next_client, bridge, step)

    def _user_step(self,
                   user: User,
                   owner: str,
                   client: Client,
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

        for container_spec in user.containers:
            if isinstance(container_spec, dict):
                if container_spec['object'] == 'container':
                    container_desc = '(inline)'
                else:
                    container_desc = '(linked)'
                try:
                    container = self.client.load_container_from_dict(container_spec, user.owner)
                except (WildlandError, FileNotFoundError) as ex:
                    logger.warning('cannot load user %s infrastructure: %s. Exception: %s',
                                   user.owner, container_spec, str(ex))
                    continue
            else:
                try:
                    manifest_content = client.read_from_url(container_spec, user.owner)
                except (WildlandError, FileNotFoundError) as ex:
                    logger.warning('cannot load user %s infrastructure: %s. Exception: %s',
                                   user.owner, container_spec, str(ex))
                    continue

                try:
                    container = client.session.load_container(manifest_content)
                    container_desc = container_spec
                except WildlandError as ex:
                    logger.warning('failed to load user %s infrastructure: %s: Exception: %s',
                                   user.owner, container_spec, str(ex))
                    continue

            if container.owner != user.owner:
                logger.warning('Unexpected owner for %s: %s (expected %s)',
                               container_desc, container.owner, user.owner)
                continue

            logger.info("user's container manifest: %s", container_desc)

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


def get_file_pattern(
        manifest_pattern: dict,
        query_path: PurePosixPath) -> str:
    """
    Return a file glob to find all files satisfying a manifest_pattern.
    The following manifest_pattern values are supported:

    - {'type': 'glob', 'path': path} where path is an absolute path that can
      contain '*' and '{path}'
    """

    mp_type = manifest_pattern['type']
    if mp_type == 'glob':
        if str(query_path) == '*':
            # iterate over manifests saved under /.uuid/ path, to try to avoid loading the
            # same manifests multiple times
            glob_path = manifest_pattern['path'].replace(
                '{path}', '.uuid/*')
        else:
            glob_path = manifest_pattern['path'].replace(
                '{path}', str(query_path.relative_to('/')))
        return glob_path
    raise WildlandError(f'Unknown manifest_pattern: {mp_type}')


def storage_glob(storage, glob_path: str) \
    -> Iterable[PurePosixPath]:
    """
    Find all files satisfying a pattern with possible wildcards (*).

    Yields all files found in the storage, but without guarantee that you will
    be able to open or read them.
    """

    path = PurePosixPath(glob_path)
    if path.parts[0] != '/':
        raise WildlandError(f'manifest_path should be absolute: {path}')
    return _find(storage, PurePosixPath('.'), path.relative_to(PurePosixPath('/')))


def _find(storage: StorageBackend, prefix: PurePosixPath, path: PurePosixPath) \
    -> Iterable[PurePosixPath]:

    assert len(path.parts) > 0, 'empty path'

    part = path.parts[0]
    sub_path = path.relative_to(part)

    if '*' in part:
        # This is a glob part, use readdir()
        try:
            names = list(storage.readdir(prefix))
        except IOError:
            return
        regex = re.compile('^' + part.replace('.', r'\.').replace('*', '.*') + '$')
        for name in names:
            if regex.match(name):
                sub_prefix = prefix / name
                if sub_path.parts:
                    yield from _find(storage, sub_prefix, sub_path)
                else:
                    yield sub_prefix
    elif sub_path.parts:
        # This is a normal part, recurse deeper
        sub_prefix = prefix / part
        yield from _find(storage, sub_prefix, sub_path)
    else:
        # End of a normal path, check using getattr()
        full_path = prefix / part
        try:
            storage.getattr(full_path)
        except IOError:
            return
        yield full_path


class StorageDriver:
    """
    A contraption to directly manipulate
    :py:type:`wildland.storage_backends.base.StorageBackend`
    """

    def __init__(self, storage_backend: StorageBackend, storage=None):
        self.storage_backend = storage_backend
        self.storage = storage

    @classmethod
    def from_storage(cls, storage: Storage) -> 'StorageDriver':
        """
        Create :py:type:`StorageDriver` from
        :py:class:`wildland.storage.Storage`
        """
        return cls(StorageBackend.from_params(storage.params), storage=storage)

    def __enter__(self):
        self.storage_backend.mount()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.storage_backend.unmount()

    def write_file(self, relpath, data):
        """
        Write a file to StorageBackend, using FUSE commands. Returns ``(StorageBackend, relpath)``.
        """

        try:
            self.storage_backend.getattr(relpath)
        except FileNotFoundError:
            exists = False
        else:
            exists = True

        if exists:
            obj = self.storage_backend.open(relpath, os.O_WRONLY)
            self.storage_backend.ftruncate(relpath, 0, obj)
        else:
            obj = self.storage_backend.create(relpath, os.O_CREAT | os.O_WRONLY,
                0o644)

        try:
            self.storage_backend.write(relpath, data, 0, obj)
            return relpath
        finally:
            self.storage_backend.release(relpath, 0, obj)

    def remove_file(self, relpath):
        """
        Remove a file.
        """
        self.storage_backend.unlink(relpath)

    def makedirs(self, relpath, mode=0o755):
        """
        Make directory, and it's parents if needed. Does not work across
        containers.
        """
        for path in reversed((relpath, *relpath.parents)):
            try:
                attr = self.storage_backend.getattr(path)
            except FileNotFoundError:
                self.storage_backend.mkdir(path, mode)
            else:
                if not attr.is_dir():
                    raise NotADirectoryError(errno.ENOTDIR, path)

    def read_file(self, relpath) -> bytes:
        '''
        Read a file from StorageBackend, using FUSE commands.
        '''

        obj = self.storage_backend.open(relpath, os.O_RDONLY)
        try:
            st = self.storage_backend.fgetattr(relpath, obj)
            return self.storage_backend.read(relpath, st.size, 0, obj)
        finally:
            self.storage_backend.release(relpath, 0, obj)
