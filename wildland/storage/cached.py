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
Cache layer for storages
'''

import abc
import stat
from io import BytesIO
import errno
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple, Set
from pathlib import Path
import logging

import fuse

from .base import AbstractStorage


@dataclass
class Info:
    '''
    Common file attributes supported by the backends.
    '''

    is_dir: bool
    size: int = 0
    timestamp: int = 0

    def as_fuse_stat(self, uid, gid) -> fuse.Stat:
        '''
        Convert to a fuse.Stat object.
        '''

        if self.is_dir:
            st_mode = stat.S_IFDIR | 0o755
        else:
            st_mode = stat.S_IFREG | 0o644

        return fuse.Stat(
            st_mode=st_mode,
            st_nlink=1,
            st_uid=uid,
            st_gid=gid,
            st_size=self.size,
            st_atime=self.timestamp,
            st_mtime=self.timestamp,
            st_ctime=self.timestamp,
        )


@dataclass
class FileHandle:
    '''
    File handle object. Right now doesn't contain any useful information, we
    keep it only to pass a unique (pointer) value to FUSE.
    '''

    path: Path


class CachedStorage(AbstractStorage):
    '''
    A Storage that adds a caching layer.

    To use, subclass it and implement backend_* methods.
    '''


    def __init__(self, *, uid, gid, **kwds):
        super().__init__(**kwds)
        self.uid = uid
        self.gid = gid

        # Currently known files and directories
        self.files: Dict[Path, Info] = {}
        self.dirs: Dict[Path, Info] = {}

        # Currently open files
        self.handle_count: Dict[Path, int] = {}

        # Loaded data, and dirty flag. For currently open files only.
        self.buffers: Dict[Path, BytesIO] = {}
        self.modified: Set[Path] = set()

    ## Backend operations - to override

    @abc.abstractmethod
    def backend_info_all(self) -> Iterable[Tuple[Path, Info]]:
        '''
        Load information about all files and directories.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_create_file(self, _path: Path) -> Info:
        '''
        Create a new, empty file. Return Info object for that file.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_create_dir(self, _path: Path) -> Info:
        '''
        Create a new directory. Return Info object for that directory.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_load_file(self, _path: Path) -> bytes:
        '''
        Load file content as bytes.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_save_file(self, _path: Path, _data: bytes) -> Info:
        '''
        Save file content from bytes.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_delete_file(self, _path: Path):
        '''
        Delete a file.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_delete_dir(self, _path: Path):
        '''
        Delete a directory.
        '''

        raise NotImplementedError()

    ## Cache management

    def mount(self):
        self.refresh()

    def refresh(self):
        '''
        Refresh cached information (self.files, self.dirs).
        '''

        self.files.clear()
        self.dirs.clear()

        # TODO: Handle open files that disappeared
        for path, info in self.backend_info_all():
            if info.is_dir:
                self.dirs[path] = info
            else:
                self.files[path] = info

        logging.info('%s', self.files)
        logging.info('%s', self.dirs)

    def load(self, path: Path) -> BytesIO:
        '''
        Load a currently open file into memory.
        '''

        assert path in self.handle_count, path

        if path not in self.buffers:
            self.buffers[path] = BytesIO(self.backend_load_file(path))
        return self.buffers[path]

    def save_direct(self, path: Path, buf: BytesIO):
        '''
        Save a file directly to backend. Use if the file is not open, otherwise
        call flush().
        '''

        assert path not in self.handle_count
        info = self.backend_save_file(path, buf.getvalue())
        self.files[path] = info

    def save(self, path: Path):
        '''
        Save modifications to backend, if the file was modified.
        '''

        assert path in self.handle_count
        if path in self.modified:
            self.modified.remove(path)
            info = self.backend_save_file(path, self.buffers[path].getvalue())
            self.files[path] = info

    ## Filesystem operations

    # pylint: disable=missing-docstring

    def open(self, path, flags):
        path = Path(path)
        if path not in self.files:
            return -errno.ENOENT

        if path in self.handle_count:
            self.handle_count[path] += 1
        else:
            self.handle_count[path] = 1

        handle = FileHandle(path)
        return handle

    def create(self, path, flags, _mode):
        path = Path(path)
        if path in self.files or path in self.dirs:
            return -errno.EEXIST

        info = self.backend_create_file(path)
        self.files[path] = info
        self.buffers[path] = BytesIO()

        return self.open(path, flags)

    def release(self, path, _flags, _handle):
        self.save(path)
        self.handle_count[path] -= 1
        if self.handle_count[path] == 0:
            del self.handle_count[path]
            if path in self.buffers:
                del self.buffers[path]

    def getattr(self, path):
        path = Path(path)
        if path in self.dirs:
            return self.dirs[path].as_fuse_stat(self.uid, self.gid)
        if path in self.files:
            return self.files[path].as_fuse_stat(self.uid, self.gid)
        raise FileNotFoundError(str(path))

    def fgetattr(self, path, _handle):
        path = Path(path)
        return self.files[path].as_fuse_stat(self.uid, self.gid)

    def readdir(self, path):
        path = Path(path)
        if path not in self.dirs:
            raise FileNotFoundError(str(path))

        for file_path in self.files:
            if file_path.parent == path:
                yield file_path.name
        for dir_path in self.dirs:
            if dir_path != path and dir_path.parent == path:
                yield dir_path.name

    def read(self, path, length, offset, _handle):
        path = Path(path)
        buf = self.load(path)

        buf.seek(offset)
        return buf.read(length)

    def write(self, path, data, offset, _handle):
        path = Path(path)
        buf = self.load(path)
        self.modified.add(path)

        buf.seek(offset)
        return buf.write(data)

    def ftruncate(self, path, length, _handle):
        path = Path(path)
        if length == 0:
            self.buffers[path] = BytesIO()
        else:
            buf = self.load(path)
            buf.truncate(length)
        self.modified.add(path)

    def truncate(self, path, length):
        path = Path(path)
        if path in self.handle_count:
            self.ftruncate(path, length, None)
            self.save(path)
        elif length == 0:
            self.save_direct(path, BytesIO())
        else:
            buf = BytesIO(self.backend_load_file(path))
            buf.truncate(length)
            self.save_direct(path, buf)

    def unlink(self, path):
        if path in self.handle_count:
            return -errno.EACCES
        if path not in self.files:
            return -errno.ENOENT
        result = self.backend_delete_file(path)
        if not result:
            del self.files[path]
        return result

    def mkdir(self, path, _mode):
        path = Path(path)
        if path in self.files or path in self.dirs:
            return -errno.EEXIST
        info = self.backend_create_dir(path)
        self.dirs[path] = info
        return None

    def rmdir(self, path):
        path = Path(path)
        if path not in self.dirs:
            return -errno.ENOENT
        # TODO: check for open files
        result = self.backend_delete_dir(path)
        if not result:
            del self.dirs[path]
        return result
