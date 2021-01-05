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

'''
Utilities for URL resolving and traversing the path
'''

import errno
import logging
import os
import re
import types
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional, Tuple, Iterable, Mapping

from .user import User
from .client import Client
from .container import Container
from .bridge import Bridge
from .storage import Storage
from .storage_backends.base import StorageBackend
from .manifest.manifest import ManifestError
from .wlpath import WildlandPath, PathError
from .exc import WildlandError


logger = logging.getLogger('search')


@dataclass
class Step:
    '''
    A single step of a resolved path.
    '''

    # Owner of the current manifest
    owner: str

    # Client with the current key loaded
    client: Client

    # Container
    container: Container

    # User, if we're changing users at this step
    user: Optional[User]



class Search:
    '''
    A class for traversing a Wildland path.

    Usage:

    .. code-block:: python

        search = Search(client, wlpath, client.config.aliases)
        search.read_file()
    '''

    def __init__(self,
            client: Client,
            wlpath: WildlandPath,
            aliases: Mapping[str, str] = types.MappingProxyType({})):
        self.client = client
        self.wlpath = wlpath
        self.aliases = aliases
        self.initial_owner = self._subst_alias(wlpath.owner or '@default')

        self.local_containers = list(self.client.load_containers())
        self.local_users = list(self.client.load_users())
        self.local_bridges = list(self.client.load_bridges())

    def read_container(self) -> Iterable[Container]:
        '''
        Yield all containers matching the given WL path.
        '''
        if self.wlpath.file_path is not None:
            raise PathError(f'Expecting a container path, not a file path: {self.wlpath}')

        for step in self._resolve_all():
            yield step.container

    def read_file(self) -> bytes:
        '''
        Read a file under the Wildland path.
        '''

        # If there are multiple containers, this method uses the first
        # one. Perhaps it should try them all until it finds a container where
        # the file exists.

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        for step in self._resolve_all():
            try:
                _, storage_backend = self._find_storage(step)
            except ManifestError:
                continue
            with storage_backend:
                try:
                    return storage_read_file(storage_backend,
                                             self.wlpath.file_path.relative_to('/'))
                except FileNotFoundError:
                    continue

        raise FileNotFoundError

    def write_file(self, data: bytes):
        '''
        Read a file under the Wildland path.
        '''

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        for step in self._resolve_all():
            try:
                _, storage_backend = self._find_storage(step)
            except ManifestError:
                continue
            try:
                with StorageDriver(storage_backend) as driver:
                    return driver.write_file(self.wlpath.file_path.relative_to('/'), data)
            except FileNotFoundError:
                continue

    def _resolve_all(self) -> Iterable[Step]:
        '''
        Resolve all path parts, yield all results that match.
        '''

        for step in self._resolve_first():
            for last_step in self._resolve_rest(step, 1):
                yield last_step
        raise PathError(f'Container not found for path: {self.wlpath}')

    def _resolve_rest(self, step: Step, i: int) -> Iterable[Step]:
        if i == len(self.wlpath.parts):
            yield step
            return

        for next_step in self._resolve_next(step, i):
            yield from self._resolve_rest(next_step, i+1)

    def _find_storage(self, step: Step) -> Tuple[Storage, StorageBackend]:
        '''
        Find a storage for the latest resolved part.

        Returns (storage, storage_backend).
        '''

        storage = self.client.select_storage(step.container)
        return storage, StorageBackend.from_params(storage.params)

    def _resolve_first(self):
        # Try local containers
        yield from self._resolve_local(self.wlpath.parts[0], self.initial_owner)

        # Try user's infrastructure containers
        for user in self.local_users:
            if user.owner == self.initial_owner:
                for step in self._user_step(user, self.initial_owner, self.client):
                    yield from self._resolve_next(step, 0)

    def _resolve_local(self, part: PurePosixPath, owner: str) -> Iterable[Step]:
        '''
        Resolve a path part based on locally stored manifests, in the context
        of a given owner.
        '''

        for container in self.local_containers:
            if (container.owner == owner and
                    part in container.expanded_paths):

                logger.debug('%s: local container: %s', part,
                            container.local_path)
                yield Step(
                    owner=self.initial_owner,
                    client=self.client,
                    container=container,
                    user=None
                )

        for bridge in self.local_bridges:
            if bridge.owner == owner and part in bridge.paths:
                logger.debug('%s: local bridge manifest: %s', part,
                            bridge.local_path)
                yield from self._bridge_step(
                    self.client, owner, part, None, None, bridge)

    def _resolve_next(self, step: Step, i: int) -> Iterable[Step]:
        '''
        Resolve next part by looking up a manifest in the current container.
        '''

        part = self.wlpath.parts[i]

        # Try local paths first
        yield from self._resolve_local(part, step.owner)

        storage, storage_backend = self._find_storage(step)
        manifest_pattern = storage.manifest_pattern or storage.DEFAULT_MANIFEST_PATTERN
        with storage_backend:
            for manifest_path in storage_find_manifests(
                    storage_backend, manifest_pattern, part):
                trusted_owner = None
                if storage.trusted:
                    trusted_owner = storage.owner

                try:
                    manifest_content = storage_read_file(storage_backend, manifest_path)
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
                        container_or_bridge)

    # pylint: disable=no-self-use

    def _container_step(self,
                        step: Step,
                        part: PurePosixPath,
                        container: Container) -> Iterable[Step]:

        self._verify_owner(container, step.owner)

        if part not in container.expanded_paths:
            logger.debug('%s: path not found in manifest, skipping', part)
            return

        yield Step(
            owner=step.owner,
            client=step.client,
            container=container,
            user=None,
        )

    def _bridge_step(self,
                     client: Client,
                     owner: str,
                     part: PurePosixPath,
                     manifest_path: Optional[PurePosixPath],
                     storage_backend: Optional[StorageBackend],
                     bridge: Bridge) -> Iterable[Step]:

        self._verify_owner(bridge, owner)

        if part not in bridge.paths:
            return

        next_client, next_owner = client.sub_client_with_key(bridge.user_pubkey)

        location = bridge.user_location
        if (location.startswith('./') or location.startswith('../')):

            if not (manifest_path and storage_backend):
                logger.warning(
                    'local bridge manifest with relative location, skipping')
                return

            # Treat location as relative path
            user_manifest_path = manifest_path.parent / location
            try:
                user_manifest_content = storage_read_file(
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

        user = next_client.session.load_user(user_manifest_content)

        yield from self._user_step(
            user, next_owner, next_client)

    def _user_step(self,
                   user: User,
                   owner: str,
                   client: Client) -> Iterable[Step]:

        self._verify_owner(user, owner)

        for container_spec in user.containers:
            if isinstance(container_spec, str):
                # Container URL
                try:
                    manifest_content = client.read_from_url(container_spec, user.owner)
                except WildlandError:
                    logger.warning('cannot load container: %s', container_spec)
                    continue

                container = client.session.load_container(manifest_content)
                container_desc = container_spec

            else:
                # Inline container
                logger.debug('loading inline container for user')
                container = client.load_container_from_dict(container_spec, user.owner)
                container_desc = '(inline)'

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


def storage_read_file(storage, relpath) -> bytes:
    '''
    Read a file from StorageBackend, using FUSE commands.
    '''

    obj = storage.open(relpath, os.O_RDONLY)
    try:
        st = storage.fgetattr(relpath, obj)
        return storage.read(relpath, st.size, 0, obj)
    finally:
        storage.release(relpath, 0, obj)


def storage_find_manifests(
        storage: StorageBackend,
        manifest_pattern: dict,
        query_path: PurePosixPath) -> Iterable[PurePosixPath]:
    '''
    Find all files satisfying a manifest_pattern. The following manifest_pattern
    values are supported:

    - {'type': 'glob', 'path': path} where path is an absolute path that can
      contain '*' and '{path}'

    Yields all files found in the storage, but without guarantee that you will
    be able to open or read them.
    '''

    mp_type = manifest_pattern['type']
    if mp_type == 'glob':
        glob_path = manifest_pattern['path'].replace(
            '{path}', str(query_path.relative_to('/')))
        return storage_glob(storage, glob_path)
    raise WildlandError(f'Unknown manifest_pattern: {mp_type}')


def storage_glob(storage, glob_path: str) \
    -> Iterable[PurePosixPath]:
    '''
    Find all files satisfying a pattern with possible wildcards (*).

    Yields all files found in the storage, but without guarantee that you will
    be able to open or read them.
    '''

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
    '''
    A contraption to directly manipulate
    :py:type:`wildland.storage_backends.base.StorageBackend`
    '''
    def __init__(self, storage_backend: StorageBackend):
        self.storage_backend = storage_backend
    @classmethod
    def from_storage(cls, storage: Storage) -> 'StorageDriver':
        '''
        Create :py:type:`StorageDriver` from
        :py:class:`wildland.storage.Storage`
        '''
        return cls(StorageBackend.from_params(storage.params))

    def __enter__(self):
        self.storage_backend.mount()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.storage_backend.unmount()

    def write_file(self, relpath, data):
        '''
        Write a file to StorageBackend, using FUSE commands.
        '''

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
        finally:
            self.storage_backend.release(relpath, 0, obj)

    def makedirs(self, relpath, mode=0o755):
        '''
        Make directory, and it's parents if needed. Does not work across
        containers.
        '''
        for path in reversed((relpath, *relpath.parents)):
            try:
                attr = self.storage_backend.getattr(path)
            except FileNotFoundError:
                self.storage_backend.mkdir(path, mode)
            else:
                if not attr.is_dir():
                    raise NotADirectoryError(errno.ENOTDIR, path)
