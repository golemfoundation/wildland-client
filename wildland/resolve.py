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

from pathlib import Path
from typing import List, Optional, Tuple
import os
import re

from .manifest.loader import ManifestLoader
from .exc import WildlandError
from .container import Container
from .storage.base import AbstractStorage


class PathError(WildlandError):
    '''
    Error in parsing or resolving a Wildland path.
    '''


def read_file(loader: ManifestLoader, wlpath: 'WildlandPath',
             default_signer: Optional[str]) -> bytes:
    '''
    Resolve the path and load a file under a given path.
    '''

    assert len(wlpath.parts) == 1, 'Only 1-part paths are supported for now'

    signer = wlpath.signer or default_signer
    if signer is None:
        raise PathError('Could not find default user for path')

    storage, relpath = resolve_local(loader, wlpath.parts[0], signer)
    return storage_read_file(storage, relpath)


def write_file(data: bytes, loader: ManifestLoader, wlpath: 'WildlandPath',
             default_signer: Optional[str]) -> bytes:
    '''
    Resolve the path and save a file under a given path.
    '''

    assert len(wlpath.parts) == 1, 'Only 1-part paths are supported for now'

    signer = wlpath.signer or default_signer
    if signer is None:
        raise PathError('Could not find default user for path')

    storage, relpath = resolve_local(loader, wlpath.parts[0], signer)
    return storage_write_file(data, storage, relpath)


def resolve_local(loader: ManifestLoader, path: Path, signer: str) \
    -> Tuple[AbstractStorage, Path]:
    '''
    Find a local container and storage for a given path.
    Return a Storage and relative path.
    '''

    best_container = None
    best_relpath = None
    containers = [
        Container(manifest)
        for mpath, manifest in loader.load_manifests('container')
    ]
    for container in containers:
        if container.signer != signer:
            continue

        for container_path in container.paths:
            try:
                relpath = path.relative_to(container_path)
            except ValueError:
                continue
            if best_container is None or len(best_relpath.parts) > len(relpath.parts):
                best_container = container
                best_relpath = relpath

    if best_container is None:
        raise PathError(f'Container not found for path: {path}')

    storage_manifest = best_container.select_storage(loader)
    storage = AbstractStorage.from_manifest(storage_manifest, uid=0, gid=0)

    assert best_relpath
    return storage, best_relpath


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
    '''

    ABSPATH_RE = re.compile(r'^/.*$')
    FINGERPRINT_RE = re.compile('^0x[0-9a-f]+$')


    def __init__(self, signer: Optional[str], parts: List[Path]):
        assert len(parts) > 0
        self.signer = signer
        self.parts = parts

    @classmethod
    def from_str(cls, s: str) -> 'WildlandPath':
        '''
        Construct a Path from a string.
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
        for part in split[1:]:
            if not cls.ABSPATH_RE.match(part):
                raise PathError('Unrecognized absolute path: {!r}'.format(part))
            parts.append(Path(part))
        return cls(signer, parts)

    def __str__(self):
        return ':'.join(
            [self.signer or ''] + [str(p) for p in self.parts])
