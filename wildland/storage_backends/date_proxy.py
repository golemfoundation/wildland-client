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
Date proxy backend
'''

from typing import Tuple, Optional, Iterable
from pathlib import PurePosixPath
import errno
import datetime

import click

from .base import StorageBackend, File, Attr
from .cached import CachedStorageMixin
from ..manifest.schema import Schema


class DateProxyStorageBackend(CachedStorageMixin, StorageBackend):
    '''
    A proxy storage that re-organizes the files into directories based on their
    modification date.

    All files will have a 'year/month/day' prefix prepended to their path.
    Directory timestamps will be ignored, and empty directories will not be
    taken into account.

    The 'storage' parameter specifies inner storage, either as URL, or as an
    inline manifest. When creating the object instance, the actual inner
    backend needs to be instantiated and passed in params['storage'].
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["storage"],
        "properties": {
            "storage": {
                "oneOf": [
                    {"$ref": "types.json#url"},
                    {"$ref": "storage.schema.json"}
                ],
                "description": "Storage backend to be used, either as URL or as an inlined manifest"
            },
        }
    })
    TYPE = 'date-proxy'

    def __init__(self, *, params, **kwds):
        super().__init__(**kwds)
        self.inner = params['storage']
        self.read_only = True

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--storage-url'], metavar='URL',
                          help='URL for inner storage manifest',
                         required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {'storage': data['storage_url']}

    def mount(self):
        self.inner.mount()

    def unmount(self):
        self.inner.unmount()

    def clear_cache(self):
        self.inner.clear_cache()

    @staticmethod
    def _split_path(path: PurePosixPath) -> Tuple[Optional[str], PurePosixPath]:
        '''
        Extract the prefix part (first 3 parts) from path. For correct
        user requests, the prefix will be a date, but it needs to be verified
        (i.e. compared with the right date).

            >>> _split_path(PurePosixPath('2020/10/10/foo/bar.txt')
            ('2020/10/10', PurePosixPath('foo/bar.txt'))

            >>> _split_path(PurePosixPath('2020/10/foo.txt')
            (None, PurePosixPath('2020/10/foo.txt'))
        '''

        if len(path.parts) <= 3:
            return None, path

        prefix, suffix = path.parts[:3], path.parts[3:]
        date = '/'.join(prefix)
        return date, PurePosixPath(*suffix)

    @staticmethod
    def _date_str(timestamp: int) -> str:
        d = datetime.date.fromtimestamp(timestamp)
        return f'{d.year:04}/{d.month:02}/{d.day:02}'

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        yield from self._info_all_walk(PurePosixPath('.'))

    def _info_all_walk(self, dir_path: PurePosixPath) -> \
        Iterable[Tuple[PurePosixPath, Attr]]:

        for name in self.inner.readdir(dir_path):
            path = dir_path / name
            attr = self.inner.getattr(path)
            if attr.is_dir():
                yield from self._info_all_walk(path)
            else:
                date_str = self._date_str(attr.timestamp)
                yield date_str / path, attr

    def open(self, path: PurePosixPath, flags: int) -> File:
        date_str, inner_path = self._split_path(path)
        if date_str is None:
            raise IOError(errno.ENOENT, str(path))
        attr = self.inner.getattr(inner_path)
        actual_date_str = self._date_str(attr.timestamp)
        if date_str != actual_date_str:
            raise IOError(errno.ENOENT, str(path))

        return self.inner.open(inner_path, flags)