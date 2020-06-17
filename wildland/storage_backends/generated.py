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
from typing import Iterable, Callable, Optional
import stat

import fuse

from .base import File
from .util import simple_dir_stat, simple_file_stat


class Entry(metaclass=abc.ABCMeta):
    '''
    File or directory entry.
    '''

    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def getattr(self) -> fuse.Stat:
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
                 get_entry_func: Optional[Callable[[str], Entry]] = None,
                 timestamp: int = 0):
        super().__init__(name)
        self.get_entries_func = get_entries_func
        self.get_entry_func = get_entry_func
        self.timestamp = timestamp

    def get_entries(self) -> Iterable[Entry]:
        return self.get_entries_func()

    def get_entry(self, name: str) -> Entry:
        if self.get_entry_func:
            return self.get_entry_func(name)
        return super().get_entry(name)

    def getattr(self) -> fuse.Stat:
        return simple_dir_stat(timestamp=self.timestamp)


class StaticFile(File):
    '''
    A read-only file with pre-determined content.
    '''

    def __init__(self, data: bytes, attr: fuse.Stat):
        self.data = data
        self.attr = attr
        self.attr.st_size = len(data)

    def read(self, length, offset):
        return self.data[offset:offset+length]

    def release(self, flags):
        pass


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
        super().__init__(name)
        self.on_read = on_read
        self.on_write = on_write
        assert self.on_read or self.on_write
        self.timestamp = timestamp

    def getattr(self) -> fuse.Stat:
        attr = simple_file_stat(size=0, timestamp=self.timestamp)
        attr.st_mode = stat.S_IFREG
        if self.on_read:
            attr.st_mode |= 0o444
        if self.on_write:
            attr.st_mode |= 0o200
        return attr

    def open(self, flags: int) -> File:
        if self.on_write:
            raise NotImplementedError()
        assert self.on_read
        data = self.on_read()
        attr = self.getattr()
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

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
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
            except KeyError:
                raise IOError(errno.ENOENT, str(path))

        return entry
