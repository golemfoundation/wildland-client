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
Convenience module to directly access storage data.
"""

import errno
import os
from pathlib import PurePosixPath


class StorageDriver:
    """
    A contraption to directly manipulate
    :class:`wildland.storage_backends.base.StorageBackend`
    """

    def __init__(self, storage_backend, storage=None, bulk_writing=False):
        self.storage_backend = storage_backend
        self.storage = storage
        self.bulk_writing: bool = bulk_writing

    @classmethod
    def from_storage(cls, storage, bulk_writing: bool = False) -> 'StorageDriver':
        """
        Create :class:`StorageDriver` from :class:`wildland.storage.Storage`

        @param storage: :class:`wildland.storage.Storage`
        @param bulk_writing: if True, writing can be cached so reading what we are writing/updating
        is undefined (files can be updated or not). Reading untouched files works as usual.
        """
        # This is to avoid circular imports
        # pylint: disable=import-outside-toplevel,cyclic-import
        from wildland.storage_backends.base import StorageBackend
        return cls(StorageBackend.from_params(storage.params, deduplicate=True),
                   storage=storage,
                   bulk_writing=bulk_writing)

    def __enter__(self):
        self.storage_backend.request_mount()
        if self.bulk_writing:
            self.storage_backend.start_bulk_writing()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if self.bulk_writing:
            self.storage_backend.stop_bulk_writing()
        self.storage_backend.request_unmount()

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        array_repr = [
            f"backend={self.storage_backend}",
        ]
        if self.storage:
            array_repr += [
                f"storage={self.storage.to_str(include_sensitive)}"
            ]
        str_repr = "storage_driver(" + ", ".join(array_repr) + ")"
        return str_repr

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
            obj = self.storage_backend.create(relpath, os.O_CREAT | os.O_WRONLY, 0o644)

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
        """
        Read a file from StorageBackend, using FUSE commands.
        """

        obj = self.storage_backend.open(relpath, os.O_RDONLY)
        try:
            st = self.storage_backend.fgetattr(relpath, obj)
            return self.storage_backend.read(relpath, st.size, 0, obj)
        finally:
            self.storage_backend.release(relpath, 0, obj)

    def file_exists(self, relpath: PurePosixPath) -> bool:
        """
        Check if file exists.
        """
        try:
            self.storage_backend.getattr(relpath)
        except FileNotFoundError:
            return False
        else:
            return True
