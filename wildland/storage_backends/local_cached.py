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
A cached version of local storage.
'''

from typing import Iterable, Tuple
from pathlib import Path, PurePosixPath
import os
import errno

import fuse
import click

from .cached import CachedStorageMixin, DirectoryCachedStorageMixin
from .buffered import FullBufferedFile, PagedFile, File
from .base import StorageBackend
from ..manifest.schema import Schema


class LocalCachedFile(FullBufferedFile):
    '''
    A fully buffered local file.
    '''

    def __init__(self, local_path: Path, attr: fuse.Stat):
        super().__init__(attr)
        self.local_path = local_path

    def read_full(self) -> bytes:
        with open(self.local_path, 'rb') as f:
            return f.read()

    def write_full(self, data: bytes) -> int:
        with open(self.local_path, 'wb') as f:
            return f.write(data)


class LocalCachedPagedFile(PagedFile):
    '''
    A paged, read-only local file.
    '''

    def __init__(self, local_path: Path, attr: fuse.Stat, page_size: int, max_pages: int):
        super().__init__(attr, page_size, max_pages)
        self.local_path = local_path

    def read_range(self, length, start) -> bytes:
        with open(self.local_path, 'rb') as f:
            f.seek(start)
            return f.read(length)


class BaseCached(StorageBackend):
    '''
    A cached storage backed by local files. Used mostly to test the caching
    scheme.

    This backend should emulate "cloud" backends, therefore, we don't keep open
    file handles, but perform read()/write() operations opening the file each
    time.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs-path",
                "description": "Path in the local filesystem"
            }
        }
    })

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.base_path = Path(self.params['path'])

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--path'], metavar='PATH',
                         help='local path',
                         required=True)
        ]

    @classmethod
    def cli_create(cls, data):
        return {'path': data['path']}

    @staticmethod
    def _stat(st: os.stat_result) -> fuse.Stat:
        '''
        Convert os.stat_result to fuse.Stat.
        '''

        return fuse.Stat(
            st_mode=st.st_mode,
            st_ino=st.st_ino,
            st_dev=st.st_dev,
            st_nlink=st.st_nlink,
            st_uid=st.st_uid,
            st_gid=st.st_gid,
            st_size=st.st_size,
            st_atime=st.st_atime,
            st_mtime=st.st_mtime,
            st_ctime=st.st_ctime,
        )

    def _local(self, path: PurePosixPath) -> Path:
        return self.base_path / path

    def open(self, path: PurePosixPath, flags: int) -> File:
        attr = self.getattr(path)
        if flags & (os.O_WRONLY | os.O_RDWR):
            return LocalCachedFile(self._local(path), attr)
        page_size = 4
        max_pages = 4
        return LocalCachedPagedFile(self._local(path), attr, page_size, max_pages)

    def create(self, path: PurePosixPath, _flags: int, _mode: int):
        local = self._local(path)
        if local.exists():
            raise IOError(errno.EEXIST, str(path))
        local.write_bytes(b'')

        self.clear_cache()
        attr = self.getattr(path)
        return LocalCachedFile(self._local(path), attr)

    def truncate(self, path: PurePosixPath, length: int) -> None:
        os.truncate(self._local(path), length)
        self.clear_cache()

    def unlink(self, path: PurePosixPath):
        self._local(path).unlink()
        self.clear_cache()

    def mkdir(self, path: PurePosixPath, mode: int):
        self._local(path).mkdir(mode)
        self.clear_cache()

    def rmdir(self, path: PurePosixPath):
        self._local(path).rmdir()
        self.clear_cache()


class LocalCachedStorageBackend(CachedStorageMixin, BaseCached):
    '''
    A cached storage that uses info_all().
    '''

    TYPE = 'local-cached'

    def info_all(self) -> Iterable[Tuple[PurePosixPath, fuse.Stat]]:
        '''
        Load information about all files and directories.
        '''

        try:
            st = os.stat(self.base_path)
        except IOError:
            return

        yield PurePosixPath('.'), self._stat(st)

        for root_s, dirs, files in os.walk(self.base_path):
            root = Path(root_s)
            rel_root = PurePosixPath(root.relative_to(self.base_path))
            for dir_name in dirs:
                try:
                    st = os.stat(root / dir_name)
                except IOError:
                    continue
                yield rel_root / dir_name, self._stat(st)

            for file_name in files:
                try:
                    st = os.stat(root / file_name)
                except IOError:
                    continue
                yield rel_root / file_name, self._stat(st)


class LocalDirectoryCachedStorageBackend(DirectoryCachedStorageMixin, BaseCached):
    '''
    A cached storage that uses info_dir().
    '''

    TYPE = 'local-dir-cached'

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, fuse.Stat]]:
        '''
        Load information about a single directory.
        '''

        for name in os.listdir(self._local(path)):
            attr = self._stat(os.stat(self._local(path) / name))
            yield name, attr
