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
from typing import Dict, Set, Tuple, Iterable, List

import fuse

from .base import File


logger = logging.getLogger('storage-buffered')


class Buffer:
    '''
    A buffer class for caching parts of a file.
    '''

    def __init__(self, size: int, page_size: int):
        self.pages: Dict[int, bytearray] = {}
        self.dirty: Set[int] = set()
        self.size = size
        self.page_size = page_size

    def _page_range(self, length, start) -> Iterable[int]:
        start_page = start // self.page_size
        end_page = (start + length + self.page_size - 1) // self.page_size
        return range(start_page, end_page)

    def set_read(self, data: bytes, length: int, start: int) -> None:
        '''
        Set retrieved parts of a file (after calling get_needed_ranges() and
        retrieving the data.).
        '''

        assert start % self.page_size == 0

        for page_num in self._page_range(length, start):
            page = bytearray(self.page_size)
            page_data = data[
                page_num * self.page_size - start:
                (page_num+1) * self.page_size - start
            ]
            page[:len(page_data)] = page_data
            self.pages[page_num] = page

    def write(self, data: bytes, start: int) -> None:
        '''
        Write new data to buffer. The necessary pages must be loaded first.
        '''

        for page_num in self._page_range(len(data), start):
            page_start = page_num * self.page_size
            page_end = (page_num + 1) * self.page_size

            part_start = max(page_start, start)
            part_end = min(page_end, start + len(data))

            if page_num not in self.pages:
                assert part_start >= self.size, 'writing to a page that is not loaded'
                self.pages[page_num] = bytearray(self.page_size)

            page = self.pages[page_num]
            page_data = data[
                part_start-start:
                part_end-start
            ]
            page[
                part_start-page_start:
                part_end-page_start
            ] = page_data

            self.dirty.add(page_num)

        self.size = max(self.size, start + len(data))

    def get_needed_ranges(self, length: int, start: int) -> List[Tuple[int, int]]:
        '''
        Returns a list of ranges (length, start) necessary to load before reading
        or writing to a file.
        '''

        if start + length > self.size:
            length = self.size - start

        if length == 0:
            return []

        ranges: List[Tuple[int, int]] = []
        for page_num in self._page_range(length, start):
            if page_num not in self.pages:
                page_start = page_num * self.page_size
                page_end = (page_num + 1) * self.page_size
                ranges.append((page_end - page_start, page_start))
        return ranges

    def get_dirty_data(self) -> List[Tuple[bytes, int]]:
        '''
        Returns a list of data chunks (data, start) that need to be saved back
        to the file.
        '''

        result: List[Tuple[bytes, int]] = []
        for page_num in sorted(self.dirty):
            assert page_num in self.pages

            part_start = page_start = page_num * self.page_size
            page_end = (page_num + 1) * self.page_size
            part_end = min(page_end, self.size)

            page = self.pages[page_num]
            page_data = page[
                part_start-page_start:
                part_end-page_start
            ]
            result.append((bytes(page_data), part_start))
        return result

    def read(self, length: int, start: int) -> bytes:
        '''
        Read data from buffer. The necessary pages must be loaded first.
        '''

        if start + length > self.size:
            length = self.size - start

        result = bytearray(length)
        for page_num in self._page_range(length, start):
            page_start = page_num * self.page_size
            page_end = (page_num + 1) * self.page_size

            part_start = max(page_start, start)
            part_end = min(page_end, start + length)

            assert page_num in self.pages, 'reading from a page that is not loaded'
            page = self.pages[page_num]
            page_data = page[
                part_start-page_start:
                part_end-page_start
            ]
            result[
                part_start-start:
                part_end-start
            ] = page_data

        return bytes(result)

    def truncate(self, new_size: int) -> None:
        '''
        Truncate the buffer to a smaller size, throwing away unnecessary data.
        '''

        if self.size <= new_size:
            return

        end_page = (self.size + self.page_size - 1) // self.page_size
        new_end_page = (new_size + self.page_size - 1) // self.page_size
        for page_num in range(new_end_page, end_page):
            if page_num in self.pages:
                del self.pages[page_num]
            if page_num in self.dirty:
                self.dirty.remove(page_num)

        self.size = new_size


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
