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

from .cached2 import CachedStorageBackend
from .base import StorageBackend
from ..manifest.schema import Schema


class LocalCachedStorageBackend(StorageBackend):
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
                "$ref": "types.json#abs_path",
                "description": "Path in the local filesystem"
            }
        }
    })
    TYPE = 'local-cached'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.base_path = Path(self.params['path'])

    @classmethod
    def add_wrappers(cls, backend):
        return CachedStorageBackend(backend)

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

    def _stat(self, st: os.stat_result) -> fuse.Stat:
        '''
        Convert os.stat_result to fuse.Stat.
        '''

        mode = st.st_mode
        if self.read_only:
            mode &= ~0o222

        return fuse.Stat(
            st_mode=mode,
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

    def extra_info_all(self) -> Iterable[Tuple[PurePosixPath, fuse.Stat]]:
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

    def create(self, path: PurePosixPath, _flags: int, _mode: int):
        if self.read_only:
            raise IOError(errno.EROFS, str(path))
        local = self._local(path)
        if local.exists():
            raise IOError(errno.EEXIST, str(path))
        local.write_bytes(b'')
        return object()

    def read(self, path: PurePosixPath, length: int, offset: int, _obj) -> bytes:
        with open(self._local(path), 'rb') as f:
            f.seek(offset)
            return f.read(length)

    def write(self, path: PurePosixPath, data: bytes, offset: int, _obj) -> int:
        if self.read_only:
            raise IOError(errno.EROFS, str(path))
        with open(self._local(path), 'wb') as f:
            f.seek(offset)
            return f.write(data)

    def truncate(self, path: PurePosixPath, length: int) -> None:
        if self.read_only:
            raise IOError(errno.EROFS, str(path))
        os.truncate(self._local(path), length)

    def unlink(self, path: PurePosixPath):
        if self.read_only:
            raise IOError(errno.EROFS, str(path))
        self._local(path).unlink()

    def mkdir(self, path: PurePosixPath, mode: int):
        if self.read_only:
            raise IOError(errno.EROFS, str(path))
        self._local(path).mkdir(mode)

    def rmdir(self, path: PurePosixPath):
        if self.read_only:
            raise IOError(errno.EROFS, str(path))
        self._local(path).rmdir()

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        return self._stat(os.stat(self._local(path)))
