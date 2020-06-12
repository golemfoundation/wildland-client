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
BufferedStorageBackend wrapper
'''

from pathlib import PurePosixPath
import logging

import fuse

from .base import File, FileProxyMixin, StorageBackend, StorageBackendWrapper


logger = logging.getLogger('storage-buffered')


class BufferedFile(File):
    '''
    A file class that buffers reads and writes.

    TODO: The current implementation does not evict pages from cache, and
    saves everything at the end.
    '''

    def __init__(self,
                 inner: StorageBackend,
                 path: PurePosixPath,
                 handle,
                 attr: fuse.Stat):
        self.inner = inner
        self.path = path
        self.handle = handle

        self.attr = attr
        self.buf = bytearray()
        self.loaded = self.attr.st_size == 0
        self.dirty = False

    def release(self, _flags: int):
        if self.dirty:
            self.inner.extra_write_full(self.path, bytes(self.buf), self.handle)
        self.inner.release(self.path, 0, self.handle)

    def _load(self) -> None:
        if not self.loaded:
            self.buf = bytearray(self.inner.extra_read_full(self.path, self.handle))
            self.loaded = True

    def read(self, length: int, offset: int) -> bytes:
        self._load()
        return bytes(self.buf[offset:offset+length])

    def write(self, data: bytes, offset: int) -> int:
        self._load()
        self.buf[offset:offset+len(data)] = data
        self.dirty = True
        return len(data)

    def fgetattr(self) -> fuse.Stat:
        self.attr.size = len(self.buf)
        return self.attr

    def ftruncate(self, length: int) -> None:
        if length < len(self.buf):
            self.buf = self.buf[:length]
            self.dirty = True

    def extra_read_full(self) -> bytes:
        return bytes(self.buf)

    def extra_write_full(self, data: bytes) -> int:
        self.buf = bytearray(data)
        self.dirty = True
        return len(data)


class BufferedStorageBackend(FileProxyMixin, StorageBackendWrapper):
    '''
    A wrapper that adds simple file buffering to a StorageBackend.

    The inner backend must implement extra_read_full() and extra_write_full().
    '''

    PAGE_SIZE = 128 * 1024 * 1024

    def __init__(self, inner: StorageBackend, page_size: int = PAGE_SIZE):
        super().__init__(inner)
        self.page_size = page_size

    # If possible, call getattr() before opening the file, so that we do not
    # invalidate the cache.

    def open(self, path: PurePosixPath, mode: int) -> BufferedFile:
        attr = self.inner.getattr(path)
        handle = self.inner.open(path, mode)
        return BufferedFile(self.inner, path, handle, attr)

    def create(self, path: PurePosixPath, flags: int, mode: int) -> BufferedFile:
        handle = self.inner.create(path, flags, mode)
        attr = self.inner.getattr(path)
        return BufferedFile(self.inner, path, handle, attr)
