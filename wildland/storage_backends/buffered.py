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
File buffering classes
'''

import logging
import abc

import fuse

from .base import File


logger = logging.getLogger('storage-buffered')


class FullBufferedFile(File, metaclass=abc.ABCMeta):
    '''
    A file class that buffers reads and writes. Stores the full file content
    in memory.

    Requires you to implement read_full() and write_full().
    '''

    def __init__(self, attr: fuse.Stat):
        self.attr = attr
        self.buf = bytearray()
        self.loaded = self.attr.st_size == 0
        self.dirty = False

    @abc.abstractmethod
    def read_full(self) -> bytes:
        '''
        Read the full file.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def write_full(self, data: bytes) -> int:
        '''
        Replace the current file content.
        '''

        raise NotImplementedError()

    def release(self, _flags: int):
        '''
        Save pending changes on release. If overriding, make sure to call
        super().release() first.
        '''

        if self.dirty:
            self.write_full(bytes(self.buf))

    def _load(self) -> None:
        if not self.loaded:
            self.buf = bytearray(self.read_full())
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
