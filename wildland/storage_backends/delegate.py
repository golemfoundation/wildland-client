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
Delegate proxy backend
"""

from typing import Iterable, Optional, Tuple
from pathlib import PurePosixPath

import click

from .base import StorageBackend, File, Attr
from ..cli.cli_base import CliError
from ..exc import WildlandError
from ..manifest.schema import Schema
from ..log import get_logger
from ..wlpath import WildlandPath

logger = get_logger('delegate')


class DelegateProxyStorageBackend(StorageBackend):
    """
    A proxy storage that exposes a subdirectory of another container.

    The 'reference-container' parameter specifies reference container, either as URL,
    or as an inline manifest. When creating the object instance:

    1. First, the storage parameters for the reference container will be resolved
       (see: :meth:`~wildland.client.Client.select_storage`),

    2. Then, the reference storage backend will be instantiated and passed as `params['storage']`
       (see: :meth:`~wildland.storage_backends.base.StorageBackend.from_params`).
    """

    # Consider refactoring this as a mixin, if needed in another backend too

    SCHEMA = Schema({
        "type": "object",
        "required": ["reference-container"],
        "properties": {
            "reference-container": {
                "$ref": "/schemas/types.json#reference-container",
                "description": "Container to be used, either as URL "
                               "or as an inlined manifest",
            },
            "subdirectory": {
                "$ref": "/schemas/types.json#abs-path",
                "description": "Subdirectory of reference-container to be exposed",
            },
        }
    })
    TYPE = 'delegate'
    LOCATION_PARAM = 'subdirectory'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.reference = self.params['storage']
        self.subdirectory = PurePosixPath(self.params.get('subdirectory', '/'))
        if self.subdirectory.anchor != '/':
            raise ValueError(f'subdirectory needs to be an absolute path (given path: '
                             f'{str(self.subdirectory)})')

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'], metavar='URL',
                         help='URL for reference container manifest',
                         required=True),
            click.Option(['--subdirectory'], metavar='SUBDIRECTORY',
                         help='Subdirectory of reference-container to be exposed',
                         required=False),
        ]

    @classmethod
    def cli_create(cls, data):
        if WildlandPath.match(data['reference_container_url']):
            wl_path = WildlandPath.from_str(data['reference_container_url'])
            if not wl_path.has_explicit_or_default_owner():
                raise CliError("reference container URL must contain explicit or default owner")

        opts = {
            'reference-container': data['reference_container_url'],
        }
        if 'subdirectory' in data:
            opts['subdirectory'] = data['subdirectory']
        return opts

    def mount(self):
        self.reference.request_mount()
        # Check if referenced subdirectory actually exists
        try:
            if self.reference.getattr(self._path(PurePosixPath('.'))):
                return
        except FileNotFoundError as err:
            raise WildlandError('delegate container refers to nonexistent location'
                                f' {self.subdirectory} of {self.reference}') from err

    def unmount(self):
        self.reference.request_unmount()

    def clear_cache(self):
        self.reference.clear_cache()

    # TODO: watcher

    def _path(self, path: PurePosixPath) -> PurePosixPath:
        if '..' in path.parts:
            raise ValueError('\'..\' forbidden in path')
        return (self.subdirectory / path).relative_to('/')

    def open(self, path: PurePosixPath, flags: int) -> File:
        return self.reference.open(self._path(path), flags)

    def create(self, path: PurePosixPath, flags: int, mode: int = 0o666):
        return self.reference.create(self._path(path), flags, mode)

    def getattr(self, path: PurePosixPath) -> Attr:
        return self.reference.getattr(self._path(path))

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        return self.reference.readdir(self._path(path))

    def truncate(self, path: PurePosixPath, length: int) -> None:
        self.reference.truncate(self._path(path), length)

    def unlink(self, path: PurePosixPath) -> None:
        self.reference.unlink(self._path(path))

    def mkdir(self, path: PurePosixPath, mode: int = 0o777) -> None:
        self.reference.mkdir(self._path(path), mode)

    def rmdir(self, path: PurePosixPath) -> None:
        self.reference.rmdir(self._path(path))

    def chmod(self, path: PurePosixPath, mode: int) -> None:
        self.reference.chmod(self._path(path), mode)

    def chown(self, path: PurePosixPath, uid: int, gid: int) -> None:
        self.reference.chown(self._path(path), uid, gid)

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        self.reference.rename(self._path(move_from), self._path(move_to))

    def utimens(self, path: PurePosixPath, atime, mtime) -> None:
        self.reference.utimens(self._path(path), atime, mtime)

    def get_file_token(self, path: PurePosixPath) -> Optional[str]:
        return self.reference.get_file_token(self._path(path))

    def get_hash(self, path: PurePosixPath):
        return self.reference.get_hash(self._path(path))

    def store_hash(self, path, hash_cache):
        return self.reference.store_hash(self._path(path), hash_cache)

    def retrieve_hash(self, path):
        return self.reference.retrieve_hash(self._path(path))

    def open_for_safe_replace(self, path: PurePosixPath, flags: int, original_hash: str) -> File:
        return self.reference.open_for_safe_replace(self._path(path), flags, original_hash)

    def walk(self, directory=PurePosixPath('')) -> Iterable[Tuple[PurePosixPath, Attr]]:
        results_with_suffix = self.reference.walk(self._path(directory))
        subdir = self.subdirectory.relative_to('/')
        yield from ((path.relative_to(subdir), attr) for (path, attr) in results_with_suffix)
