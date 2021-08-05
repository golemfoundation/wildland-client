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
Generated storage - for auto-generated file lists
"""
import os
from itertools import chain
from pathlib import PurePosixPath
import abc
import errno
from typing import Iterable, Callable, Optional, Dict
import stat
import time
import threading

from .base import File, Attr
from ..manifest.manifest import Manifest


class Entry(metaclass=abc.ABCMeta):
    """
    File or directory entry.
    """

    def __init__(self, name: str):
        self.name = name

    @abc.abstractmethod
    def getattr(self) -> Attr:
        """
        File attributes.
        """
        raise NotImplementedError()


class FileEntry(Entry, metaclass=abc.ABCMeta):
    """
    File entry. Can be open, producing a File.
    """

    @abc.abstractmethod
    def open(self, flags: int) -> File:
        """
        Open a file.
        """

        raise NotImplementedError()


class DirEntry(Entry, metaclass=abc.ABCMeta):
    """
    Directory entry. Can be listed.
    """

    @abc.abstractmethod
    def get_entries(self) -> Iterable[Entry]:
        """
        List all entries in this directory.
        """

        raise NotImplementedError()

    def get_entry(self, name: str) -> Entry:
        """
        Get a specific entry by name, or raise KeyError.

        By default, uses get_entries(), but you can override it for a more
        efficient implementation.
        """

        for entry in self.get_entries():
            if entry.name == name:
                return entry
        raise KeyError(name)

    # TODO creating/deleting files inside


class FuncDirEntry(DirEntry):
    """
    Shortcut for creating function-based directories.

    >>> def get_entries():
    ...     yield FuncFileEntry('foo.txt', lambda: b'foo')
    ...     yield FuncFileEntry('bar.txt', lambda: b'bar')
    ...
    >>> d = FuncDirEntry('dir', get_entries)
    """

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
    """
    A version of FuncDirEntry that cached its results.
    """

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
        """
        Invalidate cache.
        """

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
    """
    A read-only file with pre-determined content.
    """

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
    """
    A write-only file that triggers a callback.
    """

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
    """
    Shortcut for creating static files.
    """

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


def cli(*args):
    from ..cli import cli_main
    cmdline = ['--base-dir', os.environ['WL_BASE_DIR'], *args]
    # Convert Path to str
    cmdline = [str(arg) for arg in cmdline]
    try:
        cli_main.main.main(args=cmdline, prog_name='wl')
    except SystemExit as e:
        if e.code not in [None, 0]:
            if hasattr(e, '__context__'):
                assert isinstance(e.__context__, Exception)
                raise e.__context__


class PseudomanifestFile(File):
    """
    File for storing pseudomanifests. Only accepts selected modifications.
    """

    def __init__(self, data: bytes, attr: Attr):
        self.data = data
        self.cache: Optional[bytearray] = bytearray()
        self.cache[:] = data
        self.attr = attr
        self.attr.size = len(data)

    def read(self, length: Optional[int] = None, offset: int = 0) -> bytes:
        if length is None:
            length = self.attr.size - offset

        return bytes(self.cache)[offset:offset+length]

    def release(self, flags):
        pass

    def fgetattr(self):
        return self.attr

    def write(self, data: bytes, offset: int) -> int:
        self.cache[offset:offset + len(data)] = data

        try:
            new = Manifest.from_unsigned_bytes(self.cache)
            new.skip_verification()
            old = Manifest.from_unsigned_bytes(self.data)
            old.skip_verification()
        except Exception as e:
            message = \
                '\n# All following changes to the manifest' \
                '\n# was rejected due to encountered errors:' \
                '\n# ' + data.decode().replace('\n', '\n# ') + \
                '\n# ' + str(e).replace('\n', '\n# ')
            self.data[len(self.data) - 1:] = message.encode()
            raise IOError()
        else:
            error_messages = ""
            # PATHS

            new_paths = new.fields['paths']
            old_paths = old.fields['paths']

            to_add = [path for path in new_paths if path not in old_paths]
            paths = list(chain.from_iterable(('--path', path) for path in to_add))
            if paths:
                try:
                    cli('container', 'modify', 'add-path', 'Container', *paths)
                    old_paths.extend(to_add)
                except Exception as e:
                    error_messages += '\n' + str(e)

            to_remove = [path for path in old_paths if path not in new_paths]
            paths = list(chain.from_iterable(('--path', path) for path in to_remove))
            if paths:
                try:
                    cli('container', 'modify', 'del-path', 'Container', *paths)
                    for path in to_remove:
                        old_paths.remove(path)
                except Exception as e:
                    error_messages += '\n' + str(e)

            # CATS

            new_cat = new.fields['categories']
            old_cat = old.fields['categories']

            to_add = [cat for cat in new_cat if cat not in old_cat]
            categories = list(chain.from_iterable(('--category', cat) for cat in to_add))
            if categories:
                try:
                    cli('container', 'modify', 'add-category', 'Container', *categories)
                    old_cat.extend(to_add)
                except Exception as e:
                    error_messages += '\n' + str(e)

            to_remove = [cat for cat in old_cat if cat not in new_cat]
            categories = list(chain.from_iterable(('--category', cat) for cat in to_remove))
            if categories:
                try:
                    cli('container', 'modify', 'del-category', 'Container', *categories)
                    for path in to_remove:
                        old_cat.remove(path)
                except Exception as e:
                    error_messages += '\n' + str(e)

            # TITLE

            new_title = new.fields.get('title')
            old_title = old.fields.get('title')
            if new_title != old_title:
                if new_title is None:
                    new_title = "'null'"
                try:
                    cli('container', 'modify', 'set-title', 'Container', '--title', new_title)
                    old.fields['title'] = new.fields['title']
                except Exception as e:
                    error_messages += '\n' + str(e)

            new_other_fields = {key: value for key, value in new.fields.items()
                                if key not in ('paths', 'categories', 'title')}
            old_other_fields = {key: value for key, value in old.fields.items()
                                if key not in ('paths', 'categories', 'title')}

            if new_other_fields != old_other_fields:
                error_messages += "Pseudomanifest error: Modifying fields except:" \
                                  "\n 'paths', 'categories', 'title' are not permitted."

            self.data[:] = old.copy_to_unsigned().original_data
            if error_messages:
                message = \
                    '\n# Some changes to the following manifest' \
                    '\n# was rejected due to encountered errors:' \
                    '\n# ' + data.decode().replace('\n', '\n# ') + \
                    '\n# ' + error_messages.replace('\n', '\n# ')
                self.data[len(self.data) - 1:] = message.encode()
                raise IOError()

        return len(data)

    def ftruncate(self, length: int) -> None:
        self.cache = bytearray()


class PseudomanifestFileEntry(FileEntry):
    """
    Shortcut for creating pseudomanifest files.
    """
    def __init__(self,
                 name: str,
                 data: bytes,
                 timestamp: int = 0):
        super().__init__(name)
        self.data = bytearray(data)
        self.attr = Attr(
            size=len(self.data),
            timestamp=timestamp,
            mode=stat.S_IFREG | 0o666
        )

    def getattr(self) -> Attr:
        return self.attr

    def open(self, flags: int) -> File:
        return PseudomanifestFile(self.data, self.attr)


class FuncFileEntry(FileEntry):
    """
    Shortcut for creating function-based files.

    >>> import logging
    >>>
    >>> def read_foo():
    ...     return 'hello from foo'
    ...
    >>> def write_bar(data: bytes):
    ...     logging.info('bar: %s', data)
    ...
    >>> f1 = FileEntry('foo', on_read=read_foo)
    >>> f2 = FileEntry('bar', on_write=write_bar)
    """

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
    """
    A mixin for auto-generated storage.

    A simple usage is to implement callbacks:

    >>> from wildland.storage_backends.base import StorageBackend
    >>> from functools import partial
    >>>
    >>> class MyStorage(GeneratedStorageMixin, StorageBackend):
    ...     def get_root(self):
    ...         return FuncDirEntry('.', self._root)
    ...
    ...     def _root(self):
    ...         for i in range(10):
    ...             yield FuncDirEntry(f'dir-{i}', partial(self._dir, i))
    ...
    ...     def _dir(self, i):
    ...         yield FuncFileEntry('readme.txt', partial(self._readme, i))
    ...         yield FuncFileEntry(f'{i}.txt', partial(self._file, i))
    ...
    ...     def _readme(self, i):
    ...         return f'This is readme.txt for {i}'
    ...
    ...     def _file(self, i):
    ...         return f'This is {i}.txt'
    ...
    """

    # TODO cache

    def get_root(self) -> DirEntry:
        """
        Get the directory root.
        """

        raise NotImplementedError()

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        """
        readdir() for generated storage
        """

        entry = self._find_entry(path)
        if not isinstance(entry, DirEntry):
            raise IOError(errno.ENOTDIR, str(path))
        return (sub_entry.name for sub_entry in entry.get_entries())

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        getattr() for generated storage
        """

        return self._find_entry(path).getattr()

    def open(self, path: PurePosixPath, flags: int) -> File:
        """
        open() for generated storage
        """

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
