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

"""
File buffering classes
"""

import logging
import abc
from typing import Dict, Tuple, Iterable, List, Optional, Callable
import heapq
import threading

from .base import File, Attr


logger = logging.getLogger('storage-buffered')


class Buffer:
    """
    A buffer class for caching parts of a file.
    """

    def __init__(self, size: int, page_size: int, max_pages: int):
        self.pages: Dict[int, bytearray] = {}
        self.size = size
        self.page_size = page_size
        self.max_pages = max_pages
        self.last_used: Dict[int, int] = {}
        self.counter = 0

    def _page_range(self, length, start) -> Iterable[int]:
        start_page = start // self.page_size
        end_page = (start + length + self.page_size - 1) // self.page_size
        return range(start_page, end_page)

    def _trim(self):
        """
        Remove least recently used pages to maintain at most max_pages pages.
        """

        too_many = len(self.pages) - self.max_pages
        if too_many <= 0:
            return

        smallest = heapq.nsmallest(
            too_many, self.last_used.keys(),
            key=lambda page_num: self.last_used[page_num])

        for page_num in smallest:
            logger.debug('deleting page %s', page_num)
            del self.pages[page_num]
            del self.last_used[page_num]

    def set_read(self, data: bytes, length: int, start: int) -> None:
        """
        Set retrieved parts of a file (after calling get_needed_range() and
        retrieving the data.).
        """

        assert start % self.page_size == 0

        for page_num in self._page_range(length, start):
            if page_num in self.pages:
                logger.warning('page %d already loaded, discarding', page_num)
                continue

            page = bytearray(self.page_size)
            page_data = data[
                page_num * self.page_size - start:
                (page_num+1) * self.page_size - start
            ]
            page[:len(page_data)] = page_data
            self.pages[page_num] = page
            self.last_used[page_num] = self.counter
            self.counter += 1

    def get_needed_range(self,
                         length: Optional[int] = None,
                         start: int = 0
        ) -> Optional[Tuple[int, int]]:
        """
        Returns a range (length, start) necessary to load before reading
        or writing to a file, or None if everything is loaded already.
        """

        if length is None or start + length > self.size:
            length = self.size - start

        if length == 0:
            return None

        pages: List[int] = []
        for page_num in self._page_range(length, start):
            if page_num not in self.pages:
                pages.append(page_num)

        if not pages:
            return None

        start = pages[0] * self.page_size
        end = (pages[-1] + 1) * self.page_size
        return end-start, start

    def read(self, length: Optional[int] = None, start: int = 0) -> bytes:
        """
        Read data from buffer. The necessary pages must be loaded first.
        """

        if length is None or start + length > self.size:
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

            self.last_used[page_num] = self.counter
            self.counter += 1

        # Trim here, so that we never delete pages before reading.
        self._trim()

        return bytes(result)


class PagedFile(File, metaclass=abc.ABCMeta):
    """
    A read-only file class that stores parts of file in memory. Assumes that
    you are able to read a range of bytes from a file.

    TODO: This currently performs only 1 concurrent read. A better
    implementation would allow parallel reads, but would need to ensure that a
    given part is read only once.
    """

    page_size = 8 * 1024 * 1024
    max_pages = 8

    def __init__(self, attr: Attr):
        self.attr = attr
        self.buf = Buffer(attr.size, self.page_size, self.max_pages)
        self.buf_lock = threading.Lock()

    @abc.abstractmethod
    def read_range(self, length: int, start: int) -> bytes:
        """
        Read a range from a file. This is essentially read(), but renamed here
        so that read() proper can use the buffer.
        """

        raise NotImplementedError()

    def read(self, length: Optional[int] = None, offset: int = 0) -> bytes:
        with self.buf_lock:
            needed_range = self.buf.get_needed_range(length, offset)

            if needed_range:
                range_length, range_start = needed_range
                logger.debug('loading range: %s, %s', range_length, range_start)
                data = self.read_range(range_length, range_start)

                self.buf.set_read(data, range_length, range_start)

            return self.buf.read(length, offset)

    def fgetattr(self) -> Attr:
        return self.attr

    def release(self, flags):
        pass


class FullBufferedFile(File, metaclass=abc.ABCMeta):
    """
    A file class that buffers reads and writes. Stores the full file content
    in memory.

    Requires you to implement read_full() and write_full().
    """

    def __init__(self, attr: Attr, clear_cache_callback: Optional[Callable] = None):
        self.attr = attr
        self.buf = bytearray()
        self.loaded = self.attr.size == 0
        self.dirty = False
        self.buf_lock = threading.Lock()
        self.clear_cache = clear_cache_callback

    @abc.abstractmethod
    def read_full(self) -> bytes:
        """
        Read the full file.
        """

        raise NotImplementedError()

    @abc.abstractmethod
    def write_full(self, data: bytes) -> int:
        """
        Replace the current file content.
        """

        raise NotImplementedError()

    def release(self, _flags: int):
        """
        Save pending changes on release. If overriding, make sure to call
        super().release() first.
        """

        with self.buf_lock:
            if self.dirty:
                self.write_full(bytes(self.buf))
                if self.clear_cache:
                    self.clear_cache()

    def _load(self) -> None:
        if not self.loaded:
            self.buf = bytearray(self.read_full())
            self.loaded = True

    def read(self, length: Optional[int] = None, offset: int = 0) -> bytes:
        with self.buf_lock:
            self._load()

            if length is None:
                length = len(self.buf) - offset

            return bytes(self.buf[offset:offset+length])

    def write(self, data: bytes, offset: int) -> int:
        with self.buf_lock:
            self._load()
            self.buf[offset:offset+len(data)] = data
            self.dirty = True
        return len(data)

    def fgetattr(self) -> Attr:
        with self.buf_lock:
            self.attr.size = len(self.buf)
        return self.attr

    def ftruncate(self, length: int) -> None:
        with self.buf_lock:
            if length > 0:
                self._load()
            else:
                self.loaded = True

            if length < len(self.buf):
                self.buf = self.buf[:length]
                self.dirty = True

    def flush(self) -> None:
        with self.buf_lock:
            if self.dirty:
                self.write_full(bytes(self.buf))
                if self.clear_cache:
                    self.clear_cache()
                self.dirty = False
