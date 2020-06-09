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
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple, Set
from pathlib import PurePosixPath
import logging
import time
import errno
import os

import fuse

from .base import StorageBackend


@dataclass
class Info:
    '''
    Common file attributes supported by the backends.
    '''

    is_dir: bool
    size: int = 0
    timestamp: int = 0

    def as_fuse_stat(self, uid, gid, read_only) -> fuse.Stat:
        '''
        Convert to a fuse.Stat object.
        '''

        if self.is_dir:
            st_mode = stat.S_IFDIR | 0o755
        else:
            st_mode = stat.S_IFREG | 0o644

        if read_only:
            st_mode &= ~0o222

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

    path: PurePosixPath


class CachedStorageBackend(StorageBackend):
    '''
    A StorageBackend that adds a caching layer.

    To use, subclass it and implement backend_* methods.
    '''

    REFRESH_TIMEOUT_SECONDS = 3

    def __init__(self, *, uid, gid, **kwds):
        super().__init__(**kwds)
        self.uid = uid
        self.gid = gid

        # Currently known files and directories
        self.files: Dict[PurePosixPath, Info] = {}
        self.dirs: Dict[PurePosixPath, Info] = {}

        # Currently open files
        self.handle_count: Dict[PurePosixPath, int] = {}

        # Loaded data, and dirty flag. For currently open files only.
        self.buffers: Dict[PurePosixPath, BytesIO] = {}
        self.modified: Set[PurePosixPath] = set()

        self.last_refresh = 0.

    ## Backend operations - to override

    @abc.abstractmethod
    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        '''
        Load information about all files and directories.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_create_file(self, _path: PurePosixPath) -> Info:
        '''
        Create a new, empty file. Return Info object for that file.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_create_dir(self, _path: PurePosixPath) -> Info:
        '''
        Create a new directory. Return Info object for that directory.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_load_file(self, _path: PurePosixPath) -> bytes:
        '''
        Load file content as bytes.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_save_file(self, _path: PurePosixPath, _data: bytes) -> Info:
        '''
        Save file content from bytes.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_delete_file(self, _path: PurePosixPath):
        '''
        Delete a file.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def backend_delete_dir(self, _path: PurePosixPath):
        '''
        Delete a directory.
        '''

        raise NotImplementedError()

    ## Cache management

    def mount(self):
        self.refresh()

    def check(self):
        '''
        Refresh cache if necessary.
        '''

        if time.time() - self.last_refresh > self.REFRESH_TIMEOUT_SECONDS:
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

        self.last_refresh = time.time()

        logging.debug('files: %s', self.files)
        logging.debug('dirs: %s', self.dirs)

    def load(self, path: PurePosixPath) -> BytesIO:
        '''
        Load a currently open file into memory.
        '''

        assert path in self.handle_count, path

        if path not in self.buffers:
            self.buffers[path] = BytesIO(self.backend_load_file(path))
        return self.buffers[path]

    def save_direct(self, path: PurePosixPath, buf: BytesIO):
        '''
        Save a file directly to backend. Use if the file is not open, otherwise
        call flush().
        '''

        assert path not in self.handle_count
        info = self.backend_save_file(path, buf.getvalue())
        self.files[path] = info

    def save(self, path: PurePosixPath):
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
        path = PurePosixPath(path)

        if path not in self.files:
            raise FileNotFoundError(errno.ENOENT, str(path))

        if self.read_only and (flags & (os.O_RDWR | os.O_WRONLY)):
            raise PermissionError(errno.EROFS, str(path))

        if path in self.handle_count:
            self.handle_count[path] += 1
        else:
            self.handle_count[path] = 1

        handle = FileHandle(path)
        return handle

    def create(self, path, flags, _mode):
        path = PurePosixPath(path)

        if path in self.files or path in self.dirs:
            raise FileExistsError(str(path))

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

        info = self.backend_create_file(path)
        self.files[path] = info
        self.buffers[path] = BytesIO()

        return self.open(path, flags)

    def release(self, path, _flags, _handle):
        path = PurePosixPath(path)

        self.update_size(path)
        self.save(path)
        self.handle_count[path] -= 1
        if self.handle_count[path] == 0:
            del self.handle_count[path]
            if path in self.buffers:
                del self.buffers[path]

    def update_size(self, path):
        '''
        Update the current known file size, if the file is open.

        This needs to be done if the file is open, or if the file size is not
        yet known (backend_info_all() did not return a size).
        '''

        assert path in self.files

        st = self.files[path]
        if path in self.buffers:
            st.size = self.buffers[path].getbuffer().nbytes

    def getattr(self, path):
        self.check()
        path = PurePosixPath(path)

        if path in self.dirs:
            return self.dirs[path].as_fuse_stat(self.uid, self.gid, self.read_only)
        if path in self.files:
            self.update_size(path)
            return self.files[path].as_fuse_stat(self.uid, self.gid, self.read_only)
        raise FileNotFoundError(errno.ENOENT, str(path))

    def fgetattr(self, path, _handle):
        path = PurePosixPath(path)

        self.update_size(path)
        return self.files[path].as_fuse_stat(self.uid, self.gid, self.read_only)

    def readdir(self, path):
        self.check()
        path = PurePosixPath(path)

        if path not in self.dirs:
            raise FileNotFoundError(str(path))

        for file_path in self.files:
            if file_path.parent == path:
                yield file_path.name
        for dir_path in self.dirs:
            if dir_path != path and dir_path.parent == path:
                yield dir_path.name

    def read(self, path, length, offset, _handle):
        path = PurePosixPath(path)

        buf = self.load(path)

        buf.seek(offset)
        return buf.read(length)

    def write(self, path, data, offset, _handle):
        path = PurePosixPath(path)

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

        buf = self.load(path)
        self.modified.add(path)

        buf.seek(offset)
        return buf.write(data)

    def ftruncate(self, path, length, _handle):
        path = PurePosixPath(path)

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

        if length == 0:
            self.buffers[path] = BytesIO()
        else:
            buf = self.load(path)
            buf.truncate(length)
        self.modified.add(path)

    def truncate(self, path, length):
        path = PurePosixPath(path)

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

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
        path = PurePosixPath(path)

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

        if path in self.handle_count:
            raise PermissionError(errno.EPERM, str(path))
        if path not in self.files:
            raise FileNotFoundError(errno.ENOENT, str(path))
        result = self.backend_delete_file(path)
        if not result:
            del self.files[path]
        return result

    def mkdir(self, path, _mode):
        path = PurePosixPath(path)

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

        if path in self.files or path in self.dirs:
            raise FileExistsError(str(path))
        info = self.backend_create_dir(path)
        self.dirs[path] = info

    def rmdir(self, path):
        path = PurePosixPath(path)

        if self.read_only:
            raise PermissionError(errno.EROFS, str(path))

        if path not in self.dirs:
            raise FileNotFoundError(errno.ENOENT, str(path))
        # TODO: check for open files
        result = self.backend_delete_dir(path)
        if not result:
            del self.dirs[path]
        return result


class ReadOnlyCachedStorageBackend(CachedStorageBackend):
    '''
    A read-only version of CachedStorageBackend.

    Only backed_info_all() and backend_load_file() need to be implemented.
    '''

    # Stop Pylint from complaining about this class being abstract, see:
    # https://stackoverflow.com/questions/39256350/pylint-cannot-handle-abstract-subclasses-of-abstract-base-classes

    # pylint: disable=abstract-method

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.read_only = True

    def backend_create_file(self, path: PurePosixPath) -> Info:
        raise PermissionError(errno.EROFS, str(path))

    def backend_create_dir(self, path: PurePosixPath) -> Info:
        raise PermissionError(errno.EROFS, str(path))

    def backend_save_file(self, path: PurePosixPath, _data: bytes) -> Info:
        raise PermissionError(errno.EROFS, str(path))

    def backend_delete_file(self, path: PurePosixPath):
        raise PermissionError(errno.EROFS, str(path))

    def backend_delete_dir(self, path: PurePosixPath):
        raise PermissionError(errno.EROFS, str(path))
