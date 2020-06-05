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
import stat

import click

from .cached import CachedStorageBackend, Info
from ..manifest.schema import Schema


class LocalCachedStorageBackend(CachedStorageBackend):
    '''
    A cached storage backed by local files.

    Used mostly to test the caching scheme.
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
    def info(st: os.stat_result) -> Info:
        '''
        Convert stat result to Info.
        '''

        return Info(
            is_dir=stat.S_ISDIR(st.st_mode),
            size=st.st_size,
            timestamp=int(st.st_mtime),
        )

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        '''
        Load information about all files and directories.
        '''

        try:
            st = os.stat(self.base_path)
        except IOError:
            return

        yield PurePosixPath('.'), self.info(st)

        for root_s, dirs, files in os.walk(self.base_path):
            root = Path(root_s)
            rel_root = PurePosixPath(root.relative_to(self.base_path))
            for dir_name in dirs:
                try:
                    st = os.stat(root / dir_name)
                except IOError:
                    continue
                yield rel_root / dir_name, self.info(st)

            for file_name in files:
                try:
                    st = os.stat(root / file_name)
                except IOError:
                    continue
                yield rel_root / file_name, self.info(st)

    def backend_create_file(self, path: PurePosixPath) -> Info:
        with open(self.base_path / path, 'w'):
            pass
        return self.info(os.stat(self.base_path / path))

    def backend_create_dir(self, path: PurePosixPath) -> Info:
        os.mkdir(self.base_path / path)
        return self.info(os.stat(self.base_path / path))

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        with open(self.base_path / path, 'rb') as f:
            return f.read()

    def backend_save_file(self, path: PurePosixPath, data: bytes) -> Info:
        with open(self.base_path / path, 'wb') as f:
            f.write(data)
        return self.info(os.stat(self.base_path / path))

    def backend_delete_file(self, path: PurePosixPath):
        os.unlink(self.base_path / path)

    def backend_delete_dir(self, path: PurePosixPath):
        os.rmdir(self.base_path / path)
