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
Generated storage - for auto-generated file lists
'''

from pathlib import PurePosixPath
import abc
import errno
from typing import Iterable, Callable, Optional, Dict
import stat
import time
import threading

from .base import File, Attr


class Entry(metaclass=abc.ABCMeta):
    '''
    File or directory entry.
    '''

    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def getattr(self) -> Attr:
        '''
        File attributes.
        '''
        raise NotImplementedError()


class FileEntry(Entry, metaclass=abc.ABCMeta):
    '''
    File entry. Can be open, producing a File.
    '''

    @abc.abstractmethod
    def open(self, flags: int) -> File:
        '''
        Open a file.
        '''

        raise NotImplementedError()


class DirEntry(Entry, metaclass=abc.ABCMeta):
    '''
    Directory entry. Can be listed.
    '''

    @abc.abstractmethod
    def get_entries(self) -> Iterable[Entry]:
        '''
        List all entries in this directory.
        '''

        raise NotImplementedError()

    def get_entry(self, name: str) -> Entry:
        '''
        Get a specific entry by name, or raise KeyError.

        By default, uses get_entries(), but you can override it for a more
        efficient implementation.
        '''

        for entry in self.get_entries():
            if entry.name == name:
                return entry
        raise KeyError(name)

    # TODO creating/deleting files inside


class FuncDirEntry(DirEntry):
    '''
    Shortcut for creating function-based directories.

        def get_entries():
            yield FuncFileEntry('foo.txt', lambda: b'foo')
            yield FuncFileEntry('bar.txt', lambda: b'bar')

    d = DirEntry('dir', get_entries)
    '''

    def __init__(self, name: str,
                 get_entries_func: Callable[[], Iterable[Entry]],
                 timestamp: int = 0):
        super().__init__(name)
        self.get_entries_func = get_entries_func
        self.timestamp = timestamp

    def get_entries(self) -> Iterable[Entry]:
        return self.get_entries_func()

    def getattr(self) -> Attr:
        return Attr.dir(timestamp=self.timestamp)


class CachedDirEntry(FuncDirEntry):
    '''
    A version of FuncDirEntry that cached its results.
    '''

    def __init__(self, name: str,
                 get_entries_func: Callable[[], Iterable[Entry]],
                 timestamp: int = 0,
                 timeout_seconds: float = 3):
        super().__init__(name, get_entries_func, timestamp)
        self.entries: Dict[str, Entry] = {}
        self.expiry: float = 0
        self.timeout_seconds = timeout_seconds
        self.cache_lock = threading.Lock()

    def clear_cache(self):
        '''
        Invalidate cache.
        '''

        with self.cache_lock:
            self.expiry = 0

    def _update(self):
        if time.time() > self.expiry:
            self._refresh()
            self.expiry = time.time() + self.timeout_seconds

    def _refresh(self):
        self.entries = {entry.name: entry
                        for entry in self.get_entries_func()}

    def get_entries(self) -> Iterable[Entry]:
        with self.cache_lock:
            self._update()
            return self.entries.values()

    def get_entry(self, name: str) -> Entry:
        with self.cache_lock:
            self._update()
            return self.entries[name]


class StaticFile(File):
    '''
    A read-only file with pre-determined content.
    '''

    def __init__(self, data: bytes, attr: Attr):
        self.data = data
        self.attr = attr
        self.attr.size = len(data)

    def read(self, length: Optional[int] = None, offset: int = 0) -> bytes:
        if length is None:
            length = self.attr.size - offset

        return self.data[offset:offset+length]

    def release(self, flags):
        pass

    def fgetattr(self):
        return self.attr


class CommandFile(File):
    '''
    A write-only file that triggers a callback.
    '''

    def __init__(self,
                 on_write: Callable[[bytes], None],
                 attr: Attr):
        self.on_write = on_write
        self.attr = attr

    def write(self, data: bytes, _offset):
        self.on_write(data)
        return len(data)

    def release(self, flags):
        pass

    def fgetattr(self):
        return self.attr

    def ftruncate(self, length):
        pass


class StaticFileEntry(FileEntry):
    '''
    Shortcut for creating static files.
    '''

    def __init__(self,
                 name: str,
                 data: bytes,
                 timestamp: int = 0):
        super().__init__(name)
        self.data = data
        self.attr = Attr(
            size=len(self.data),
            timestamp=timestamp,
            mode=stat.S_IFREG | 0o444
        )

    def getattr(self) -> Attr:
        return self.attr

    def open(self, flags: int) -> File:
        return StaticFile(self.data, self.attr)


class FuncFileEntry(FileEntry):
    '''
    Shortcut for creating function-based files.

        def read_foo():
            return 'hello from foo'

        def write_bar(data: bytes):
            logging.info('bar: %s', data)

        f1 = FileEntry('foo', on_read=read_foo)
        f2 = FileEntry('bar', on_write=write_bar)
    '''

    def __init__(self, name: str,
                 on_read: Optional[Callable[[], bytes]] = None,
                 on_write: Optional[Callable[[bytes], None]] = None,
                 timestamp: int = 0):
        assert bool(on_read) + bool(on_write) == 1, \
            'exactly one of on_read or on_write expected'

        super().__init__(name)
        self.on_read = on_read
        self.on_write = on_write
        self.timestamp = timestamp

    def getattr(self) -> Attr:
        attr = Attr.file(size=0, timestamp=self.timestamp)
        attr.mode = stat.S_IFREG
        if self.on_read:
            attr.mode |= 0o444
        if self.on_write:
            attr.mode |= 0o200
        return attr

    def open(self, flags: int) -> File:
        attr = self.getattr()
        if self.on_write:
            return CommandFile(self.on_write, attr)
        assert self.on_read
        data = self.on_read()
        return StaticFile(data, attr)


class GeneratedStorageMixin:
    '''
    A mixin for auto-generated storage.

    A simple usage is to implement callbacks:

        class MyStorage(GeneratedStorageMixin, StorageBackend):
            def get_root(self):
                return FuncDirEntry('.', self._root)

            def _root(self):
                for i in range(10):
                    yield FuncDirEntry(f'dir-{i}', partial(self._dir, i))

            def _dir(self, i):
                yield FuncFileEntry('readme.txt', partial(self._readme, i))
                yield FuncFileEntry(f'{i}.txt', partial(self._file, i))

            def _readme(self, i):
                return f'This is readme.txt for {i}'

            def _file(self, i):
                return f'This is {i}.txt'
    '''

    # TODO cache

    def get_root(self) -> DirEntry:
        '''
        Get the directory root.
        '''

        raise NotImplementedError()

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        '''
        readdir() for generated storage
        '''

        entry = self._find_entry(path)
        if not isinstance(entry, DirEntry):
            raise IOError(errno.ENOTDIR, str(path))
        return (sub_entry.name for sub_entry in entry.get_entries())

    def getattr(self, path: PurePosixPath) -> Attr:
        '''
        getattr() for generated storage
        '''

        return self._find_entry(path).getattr()

    def open(self, path: PurePosixPath, flags: int) -> File:
        '''
        open() for generated storage
        '''

        entry = self._find_entry(path)
        if not isinstance(entry, FileEntry):
            raise IOError(errno.EISDIR, str(path))
        return entry.open(flags)

    def _find_entry(self, path: PurePosixPath) -> Entry:
        entry: Entry = self.get_root()
        for part in path.parts:
            if not isinstance(entry, DirEntry):
                raise IOError(errno.ENOENT, str(path))

            try:
                entry = entry.get_entry(part)
            except KeyError as ke:
                raise IOError(errno.ENOENT, str(path)) from ke

        return entry
