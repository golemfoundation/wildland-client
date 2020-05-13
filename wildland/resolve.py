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

from pathlib import PurePosixPath, Path
from typing import List, Optional, Tuple
import os
import re
import logging
from dataclasses import dataclass

from .manifest.manifest import Manifest
from .manifest.loader import ManifestLoader
from .exc import WildlandError
from .container import Container
from .storage.base import AbstractStorage


logger = logging.getLogger('resolve')


class PathError(WildlandError):
    '''
    Error in parsing or resolving a Wildland path.
    '''


@dataclass
class Step:
    '''
    A single step of a resolved path.
    '''

    container: Container
    manifest_path: Optional[Path]
    container_path: PurePosixPath


class Search:
    '''
    A class for traversing a Wildland path.

    Usage:

        search = Search(loader, wlpath)
        search.read_file()
    '''

    def __init__(self, loader: ManifestLoader, wlpath: 'WildlandPath',
                 default_signer: Optional[str] = None):
        self.loader = loader
        self.wlpath = wlpath
        self.signer = wlpath.signer or default_signer or loader.config.get('default_user')
        if self.signer is None:
            raise PathError('Could not find default user for path: {wlpath}')

        # Each step correspond to a given part of the WildlandPath.
        self.steps: List[Step] = []

    @property
    def current_part(self) -> PurePosixPath:
        '''
        Current part, after the steps we have already resolved.
        '''

        return self.wlpath.parts[-1]

    def read_container(self, remote: bool) -> Tuple[Container, Optional[Path]]:
        '''
        Read a container manifest represented by the path. Returns
        ``(container, manifest_path)``.

        If 'remote' is true, we are allowed to traverse the Wildland path
        further. If we do, the manifest path will be null.
        '''
        if self.wlpath.file_path is not None:
            raise PathError(f'Expecting a container path, not a file path: {self.wlpath}')

        if remote:
            self.resolve_all()
            return self.steps[-1].container, self.steps[-1].manifest_path

        if len(self.wlpath.parts) > 1:
            raise PathError(f'Expecting a local path: {self.wlpath}')

        self.resolve_first()
        return self.steps[0].container, self.steps[0].manifest_path

    def read_file(self) -> bytes:
        '''
        Read a file under the Wildland path.
        '''

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        self.resolve_all()
        storage = self.find_storage()
        return storage_read_file(storage, self.wlpath.file_path.relative_to('/'))

    def write_file(self, data: bytes):
        '''
        Read a file under the Wildland path.
        '''

        if self.wlpath.file_path is None:
            raise PathError(f'Expecting a file path, not a container path: {self.wlpath}')

        self.resolve_all()
        storage = self.find_storage()
        return storage_write_file(data, storage, self.wlpath.file_path.relative_to('/'))

    def resolve_all(self):
        '''
        Resolve all path parts.
        '''

        assert len(self.steps) == 0
        self.resolve_first()
        while len(self.steps) < len(self.wlpath.parts):
            self.resolve_next()

    def find_storage(self):
        '''
        Find a storage for the latest resolved part.
        '''

        assert len(self.steps) > 0
        step = self.steps[-1]
        # TODO: resolve manifest path in the context of the container
        # TODO: accept local storage only as long as the whole chain is local
        storage_manifest = step.container.select_storage(self.loader)
        return AbstractStorage.from_manifest(storage_manifest, uid=0, gid=0)

    def resolve_first(self):
        '''
        Resolve the first path part. The first part is special because we are
        looking up the manifest locally.
        '''

        assert len(self.steps) == 0
        container_path = self.wlpath.parts[0]

        for manifest_path, manifest in self.loader.load_manifests('container'):
            container = Container(manifest)
            if (container.signer == self.signer and
                container_path in container.paths):

                logger.info('%s: local container: %s', container_path,
                            manifest_path)
                step = Step(container, manifest_path, container_path)
                self.steps.append(step)
                return

        raise PathError(f'Container not found for path: {container_path}')

    def resolve_next(self):
        '''
        Resolve next part by looking up a manifest in the current container.
        '''

        assert 0 < len(self.steps) < len(self.wlpath.parts)
        storage = self.find_storage()
        part = self.wlpath.parts[len(self.steps)]
        manifest_path = part.relative_to('/').with_suffix('.yaml')

        try:
            manifest_content = storage_read_file(storage, manifest_path)
        except FileNotFoundError:
            raise PathError(f'Could not find manifest: {manifest_path}')
        logger.info('%s: container manifest: %s', part, manifest_path)

        manifest = Manifest.from_bytes(manifest_content, self.loader.sig,
                                       schema=Container.SCHEMA)
        if manifest.fields['signer'] != self.signer:
            raise PathError(
                'Unexpected signer for {}: {} (expected {})'.format(
                    manifest_path, manifest.fields['signer'], self.signer
                ))
        container = Container(manifest)
        if part not in container.paths:
            logger.warning('%s: path not found in manifest: %s',
                           part, manifest_path)
        step = Step(container, None, part)
        self.steps.append(step)


def storage_read_file(storage, relpath) -> bytes:
    '''
    Read a file from Storage, using FUSE commands.
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
    Write a file to Storage, using FUSE commands.
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


class WildlandPath:
    '''
    A path in Wildland namespace.

    The path has the following form:

        [signer]:(part:)+:[file_path]

    - signer (optional): signer determining the first container's namespace
    - parts: intermediate parts, identifying containers on the path
    - file_path (optional): path to file in the last container
    '''

    ABSPATH_RE = re.compile(r'^/.*$')
    FINGERPRINT_RE = re.compile(r'^0x[0-9a-f]+$')
    WLPATH_RE = re.compile(r'^(0x[0-9a-f]+)?:')

    def __init__(
        self,
        signer: Optional[str],
        parts: List[PurePosixPath],
        file_path: Optional[PurePosixPath]
    ):
        assert len(parts) > 0
        self.signer = signer
        self.parts = parts
        self.file_path = file_path

    @classmethod
    def match(cls, s: str) -> bool:
        '''
        Check if a string should be recognized as a Wildland path.

        To be used when distinguishing Wildland paths from other identifiers
        (local paths, URLs).

        Note that this doesn't guarantee that the WildlandPath.from_str() will
        succeed in parsing the path.
        '''

        return cls.WLPATH_RE.match(s) is not None

    @classmethod
    def from_str(cls, s: str) -> 'WildlandPath':
        '''
        Construct a WildlandPath from a string.
        '''
        if ':' not in s:
            raise PathError('The path has to start with signer and ":"')

        split = s.split(':')
        if split[0] == '':
            signer = None
        elif cls.FINGERPRINT_RE.match(split[0]):
            signer = split[0]
        else:
            raise PathError('Unrecognized signer field: {!r}'.format(split[0]))

        parts = []
        for part in split[1:-1]:
            if not cls.ABSPATH_RE.match(part):
                raise PathError('Unrecognized absolute path: {!r}'.format(part))
            parts.append(PurePosixPath(part))

        if split[-1] == '':
            file_path = None
        else:
            if not cls.ABSPATH_RE.match(split[-1]):
                raise PathError('Unrecognized absolute path: {!r}'.format(split[-1]))
            file_path = PurePosixPath(split[-1])

        if not parts:
            raise PathError('Path has no containers: {!r}. Did you forget a ":" at the end?')

        return cls(signer, parts, file_path)

    def __str__(self):
        s = ''
        if self.signer is not None:
            s += self.signer
        s += ':' + ':'.join(str(p) for p in self.parts) + ':'
        if self.file_path is not None:
            s += str(self.file_path)
        return s
