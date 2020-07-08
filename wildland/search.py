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

from pathlib import PurePosixPath
from typing import Optional, Tuple, Iterable
import os
import logging
from dataclasses import dataclass
import re

from .user import User
from .client import Client
from .container import Container
from .storage import Storage
from .storage_backends.base import StorageBackend
from .wlpath import WildlandPath, PathError
from .exc import WildlandError


logger = logging.getLogger('search')


@dataclass
class Step:
    '''
    A single step of a resolved path.
    '''

    # Signer for the current manifest
    signer: str

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

        search = Search(client, wlpath)
        search.read_file()
    '''

    def __init__(self, client: Client, wlpath: WildlandPath,
                 default_user: Optional[str] = None):
        self.client = client
        self.wlpath = wlpath

        if wlpath.signer is None:
            self.initial_signer = client.config.get('@default')
        elif wlpath.signer.startswith('@'):
            if wlpath.signer in ['@default', '@default-signer']:
                self.initial_signer = client.config.get(wlpath.signer)
            else:
                raise PathError(f'Unknown alias: {wlpath.signer}')

        if self.initial_signer is None:
            if default_user:
                self.initial_signer = default_user
            else:
                raise PathError(f'Could not find default user for path: {wlpath}')

    def read_container(self, remote: bool) -> Container:
        '''
        Read a container manifest represented by the path. Returns
        ``(container, manifest_path)``.

        If 'remote' is true, we are allowed to traverse the Wildland path
        further. If we do, the manifest path will be null.
        '''
        if self.wlpath.file_path is not None:
            raise PathError(f'Expecting a container path, not a file path: {self.wlpath}')

        if remote:
            step = self._resolve_all()
            return step.container

        if len(self.wlpath.parts) > 1:
            raise PathError(f'Expecting a local path: {self.wlpath}')

        for step in self._resolve_first():
            return step.container

        raise PathError(f'Container not found for path: {self.wlpath.parts[0]}')

    def read_file(self) -> bytes:
        '''
        Read a file under the Wildland path.
        '''

        # If there are multiple containers, this method uses the first
        # one. Perhaps it should try them all until it finds a container where
        # the file exists.

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        step = self._resolve_all()
        _, storage_backend = self._find_storage(step)
        storage_backend.mount()
        try:
            return storage_read_file(storage_backend, self.wlpath.file_path.relative_to('/'))
        finally:
            storage_backend.unmount()

    def write_file(self, data: bytes):
        '''
        Read a file under the Wildland path.
        '''

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        step = self._resolve_all()
        _, storage_backend = self._find_storage(step)
        storage_backend.mount()
        try:
            return storage_write_file(data, storage_backend, self.wlpath.file_path.relative_to('/'))
        finally:
            storage_backend.unmount()

    def _resolve_all(self) -> Step:
        '''
        Resolve all path parts, return the first result that matches.
        '''

        for step in self._resolve_first():
            for last_step in self._resolve_rest(step, 1):
                return last_step
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

        # TODO: resolve manifest path in the context of the container
        storage = self.client.select_storage(step.container)
        return storage, StorageBackend.from_params(storage.params)

    def _resolve_first(self) -> Iterable[Step]:
        '''
        Resolve the first path part. The first part is special because we are
        looking up the manifest locally.
        '''

        container_path = self.wlpath.parts[0]

        for container in self.client.load_containers():
            if (container.signer == self.initial_signer and
                container_path in container.paths):

                logger.info('%s: local container: %s', container_path,
                            container.local_path)
                yield Step(
                    signer=self.initial_signer,
                    client=self.client,
                    container=container,
                    user=None
                )

    def _resolve_next(self, step: Step, i: int) -> Iterable[Step]:
        '''
        Resolve next part by looking up a manifest in the current container.
        '''

        assert 0 < i < len(self.wlpath.parts)
        storage, storage_backend = self._find_storage(step)
        query_path = self.wlpath.parts[i]

        manifest_pattern = storage.manifest_pattern or storage.DEFAULT_MANIFEST_PATTERN
        storage_backend.mount()
        try:
            for manifest_path in storage_find_manifests(
                    storage_backend, manifest_pattern, query_path):
                trusted_signer = None
                if storage.trusted:
                    trusted_signer = storage.signer

                try:
                    manifest_content = storage_read_file(storage_backend, manifest_path)
                except IOError as e:
                    logger.warning('Could not read %s: %s', manifest_path, e)
                    continue

                container_or_user = self.client.session.load_container_or_user(
                    manifest_content, trusted_signer=trusted_signer)

                if isinstance(container_or_user, Container):
                    logger.info('%s: container manifest: %s', query_path, manifest_path)
                    yield from self._container_step(
                        step, query_path, manifest_path, container_or_user)
                else:
                    logger.info('%s: user manifest: %s', query_path, manifest_path)
                    yield from self._user_step(
                        step, query_path, manifest_path, container_or_user)
        finally:
            storage_backend.unmount()


    @staticmethod
    def _container_step(step: Step,
                        part: PurePosixPath,
                        manifest_path: PurePosixPath,
                        container: Container) -> Iterable[Step]:

        if container.signer != step.signer:
            raise PathError(
                'Unexpected signer for {}: {} (expected {})'.format(
                    manifest_path, container.signer, step.signer
                ))
        if part not in container.paths:
            logger.debug('%s: path not found in manifest: %s, skipping',
                         part, manifest_path)
            return

        yield Step(
            signer=step.signer,
            client=step.client,
            container=container,
            user=None,
        )

    @staticmethod
    def _user_step(step: Step,
                   part: PurePosixPath,
                   manifest_path: PurePosixPath,
                   user: User) -> Iterable[Step]:

        found_container: Optional[Container] = None
        found_container_url: Optional[str] = None

        client = step.client.sub_client_with_key(user.pubkey)

        for container_url in user.containers:
            try:
                manifest_content = client.read_from_url(container_url, user.signer)
            except WildlandError:
                logger.warning('cannot load container: %s', container_url)
                continue
            container = client.session.load_container(manifest_content)
            if part in container.paths:
                found_container = container
                found_container_url = container_url
                break

        if not found_container:
            logger.debug('Cannot find container with path: %s for user: %s',
                         part, manifest_path)
            return

        if found_container.signer != user.signer:
            logger.warning('Unexpected signer for %s: %s (expected %s)',
                           found_container_url, found_container.signer, user.signer)
            return

        yield Step(
            signer=user.signer,
            client=client,
            container=container,
            user=user,
        )


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


def storage_write_file(data, storage, relpath):
    '''
    Write a file to StorageBackend, using FUSE commands.
    '''

    try:
        storage.getattr(relpath)
    except FileNotFoundError:
        exists = False
    else:
        exists = True

    if exists:
        obj = storage.open(relpath, os.O_WRONLY)
        storage.ftruncate(relpath, 0, obj)
    else:
        obj = storage.create(relpath, os.O_CREAT | os.O_WRONLY, 0o644)

    try:
        storage.write(relpath, data, 0, obj)
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
        glob_path = manifest_pattern['path'].replace('{path}', str(query_path))
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
