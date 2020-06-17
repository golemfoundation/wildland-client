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
Utilities for URL resolving and traversing the path
'''

from pathlib import PurePosixPath
from typing import List, Optional, Tuple
import os
import logging
from dataclasses import dataclass

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

    user: Optional[User]
    container: Container
    container_path: PurePosixPath


class Search:
    '''
    A class for traversing a Wildland path.

    Usage:

        search = Search(client, wlpath)
        search.read_file()
    '''

    def __init__(self, client: Client, wlpath: WildlandPath,
                 default_signer: Optional[str] = None):
        self.client = client
        self.wlpath = wlpath
        self.initial_signer = wlpath.signer or default_signer or client.config.get('default_user')
        self.current_signer = self.initial_signer
        if self.initial_signer is None:
            raise PathError('Could not find default user for path: {wlpath}')

        # Each step correspond to a given part of the WildlandPath.
        self.steps: List[Step] = []

    @property
    def current_part(self) -> PurePosixPath:
        '''
        Current part, after the steps we have already resolved.
        '''

        return self.wlpath.parts[-1]

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
            self._resolve_all()
            return self.steps[-1].container

        if len(self.wlpath.parts) > 1:
            raise PathError(f'Expecting a local path: {self.wlpath}')

        self._resolve_first()
        return self.steps[0].container

    def read_file(self) -> bytes:
        '''
        Read a file under the Wildland path.
        '''

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        self._resolve_all()
        _, storage_backend = self._find_storage()
        return storage_read_file(storage_backend, self.wlpath.file_path.relative_to('/'))

    def write_file(self, data: bytes):
        '''
        Read a file under the Wildland path.
        '''

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        self._resolve_all()
        _, storage_backend = self._find_storage()
        return storage_write_file(data, storage_backend, self.wlpath.file_path.relative_to('/'))

    def _resolve_all(self):
        '''
        Resolve all path parts.
        '''

        assert len(self.steps) == 0
        self._resolve_first()
        while len(self.steps) < len(self.wlpath.parts):
            self._resolve_next()

    def _find_storage(self) -> Tuple[Storage, StorageBackend]:
        '''
        Find a storage for the latest resolved part.

        Returns (storage, storage_backend).
        '''

        assert len(self.steps) > 0
        step = self.steps[-1]
        # TODO: resolve manifest path in the context of the container
        # TODO: accept local storage only as long as the whole chain is local
        storage = self.client.select_storage(step.container)
        return storage, StorageBackend.from_params(storage.params)

    def _resolve_first(self):
        '''
        Resolve the first path part. The first part is special because we are
        looking up the manifest locally.
        '''

        assert len(self.steps) == 0
        container_path = self.wlpath.parts[0]

        for container in self.client.load_containers():
            if (container.signer == self.initial_signer and
                container_path in container.paths):

                logger.info('%s: local container: %s', container_path,
                            container.local_path)
                step = Step(None, container, container_path)
                self.steps.append(step)
                return

        raise PathError(f'Container not found for path: {container_path}')

    def _resolve_next(self):
        '''
        Resolve next part by looking up a manifest in the current container.
        '''

        assert 0 < len(self.steps) < len(self.wlpath.parts)
        storage, storage_backend = self._find_storage()
        part = self.wlpath.parts[len(self.steps)]
        manifest_path = part.relative_to('/').with_suffix('.yaml')

        trusted_signer = None
        if storage.trusted:
            trusted_signer = storage.signer

        try:
            manifest_content = storage_read_file(storage_backend, manifest_path)
        except FileNotFoundError:
            raise PathError(f'Could not find manifest: {manifest_path}')
        container_or_user = self.client.session.load_container_or_user(
            manifest_content, trusted_signer=trusted_signer)

        if isinstance(container_or_user, Container):
            logger.info('%s: container manifest: %s', part, manifest_path)
            self._container_step(part, manifest_path, container_or_user)
        else:
            logger.info('%s: user manifest: %s', part, manifest_path)
            self._user_step(part, manifest_path, container_or_user)

    def _container_step(self, part: PurePosixPath, manifest_path: PurePosixPath,
                        container: Container):
        if container.signer != self.current_signer:
            raise PathError(
                'Unexpected signer for {}: {} (expected {})'.format(
                    manifest_path, container.signer, self.current_signer
                ))
        if part not in container.paths:
            logger.warning('%s: path not found in manifest: %s',
                           part, manifest_path)

        step = Step(None, container, part)
        self.steps.append(step)

    def _user_step(self, part: PurePosixPath, manifest_path: PurePosixPath, user: User):
        found_container: Optional[Container] = None
        found_container_url: Optional[str] = None

        self.client = self.client.sub_client_with_key(user.pubkey)
        self.current_signer = user.signer

        for container_url in user.containers:
            try:
                manifest_content = self.client.read_from_url(container_url, user.signer)
            except WildlandError:
                logger.warning('cannot load container: %s', container_url)
                continue
            container = self.client.session.load_container(manifest_content)
            if part in container.paths:
                found_container = container
                found_container_url = container_url
                break

        if not found_container:
            raise PathError(
                'Cannot find container with path: {} for user: {}'.format(
                    part, manifest_path
                ))
        if found_container.signer != user.signer:
            raise PathError(
                'Unexpected signer for {}: {} (expected {})'.format(
                    found_container_url, found_container.signer, user.signer
                ))
        step = Step(user, found_container, part)
        self.steps.append(step)


def storage_read_file(storage, relpath) -> bytes:
    '''
    Read a file from StorageBackend, using FUSE commands.
    '''

    storage.mount()
    obj = storage.open(relpath, os.O_RDONLY)
    try:
        st = storage.fgetattr(relpath, obj)
        return storage.read(relpath, st.st_size, 0, obj)
    finally:
        storage.release(relpath, 0, obj)


def storage_write_file(data, storage, relpath):
    '''
    Write a file to StorageBackend, using FUSE commands.
    '''

    storage.mount()
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
