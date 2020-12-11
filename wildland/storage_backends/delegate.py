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
Delegate proxy backend
'''

from typing import Tuple, Iterable
from pathlib import PurePosixPath

import click

from .base import StorageBackend, File, Attr
from ..manifest.schema import Schema


class DelegateProxyStorageBackend(StorageBackend):
    """
    A proxy storage that exposes a subdirectory of another container.

    The 'inner-container' parameter specifies inner container, either as URL,
    or as an inline manifest. When creating the object instance:

    1. First, the storage parameters for the inner container will be resolved
    (see Client.select_storage()),

    2. Then, the inner storage backend will be instantiated and passed as
    params['storage'] (see StorageBackend.from_params()).
    """

    # Consider refactoring this as a mixin, if needed in another backend too

    SCHEMA = Schema({
        "type": "object",
        "required": ["inner-container"],
        "properties": {
            "inner-container": {
                "oneOf": [
                    {"$ref": "types.json#url"},
                    {"$ref": "container.schema.json"}
                ],
                "description": ("Container to be used, either as URL "
                                "or as an inlined manifest"),
            },
            "subdirectory": {
                "$ref": "types.json#abs-path",
                "description": ("Subdirectory of inner-container to be exposed"),
            },
        }
    })
    TYPE = 'delegate'

    def __init__(self, *, params, **kwds):
        super().__init__(**kwds)
        self.inner = params['storage']
        self.subdirectory = PurePosixPath(params.get('subdirectory', '/'))

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--inner-container-url'], metavar='URL',
                          help='URL for inner container manifest',
                         required=True),
            click.Option(['--subdirectory'], metavar='SUBDIRECTORY',
                          help='Subdirectory of inner-container to be exposed',
                         required=False),
        ]

    @classmethod
    def cli_create(cls, data):
        opts = {
            'inner-container': data['inner_container_url'],
        }
        if 'subdirectory' in data:
            opts['subdirectory'] = data['subdirectory']
        return opts

    def mount(self):
        self.inner.mount()

    def unmount(self):
        self.inner.unmount()

    def clear_cache(self):
        self.inner.clear_cache()

    # TODO: watcher

    def _path(self, path: PurePosixPath) -> PurePosixPath:
        if '..' in path.parts:
            raise ValueError('\'..\' forbidden in path')
        return (self.subdirectory / path).relative_to('/')

    def open(self, path: PurePosixPath, flags: int) -> File:
        return self.inner.open(self._path(path), flags)

    def create(self, path: PurePosixPath, flags: int, mode: int = 0o666):
        return self.inner.create(self._path(path), flags, mode)

    def getattr(self, path: PurePosixPath) -> Attr:
        return self.inner.getattr(self._path(path))

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        return self.inner.readdir(self._path(path))

    def truncate(self, path: PurePosixPath, length: int) -> None:
        self.inner.truncate(self._path(path), length)

    def unlink(self, path: PurePosixPath) -> None:
        self.inner.unlink(self._path(path))

    def mkdir(self, path: PurePosixPath, mode: int = 0o777) -> None:
        self.inner.mkdir(self._path(path), mode)

    def rmdir(self, path: PurePosixPath) -> None:
        self.inner.rmdir(self._path(path))

    def get_file_token(self, path: PurePosixPath) -> int:
        return self.inner.get_file_token(self._path(path))

    def get_hash(self, path: PurePosixPath):
        return self.inner.get_hash(self._path(path))

    def store_hash(self, path, hash_cache):
        return self.inner.store_hash(self._path(path), hash_cache)

    def retrieve_hash(self, path):
        return self.inner.retrieve_hash(self._path(path))

    def open_for_safe_replace(self, path: PurePosixPath, flags: int, original_hash: str) -> File:
        return self.inner.open_for_safe_replace(self._path(path), flags, original_hash)

    def walk(self, directory=PurePosixPath('')) -> Iterable[Tuple[PurePosixPath, Attr]]:
        return self.inner.walk(self._path(directory))
