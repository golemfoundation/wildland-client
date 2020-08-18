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
A ZIP file storage.
'''

from typing import Iterable, Tuple, Iterator, List
import zipfile
from pathlib import Path, PurePosixPath
from datetime import datetime
import errno
import threading
import logging

import click

from ..manifest.schema import Schema
from .cached import CachedStorageMixin
from .buffered import FullBufferedFile
from .base import StorageBackend, Attr, FileEvent


logger = logging.getLogger('zip-archive')


class ZipArchiveFile(FullBufferedFile):
    '''
    A file inside a ZIP archive.
    '''

    def __init__(self, zip_path: Path, path: PurePosixPath, attr):
        super().__init__(attr)
        self.zip_path = zip_path
        self.path = path

    def read_full(self) -> bytes:
        with zipfile.ZipFile(self.zip_path) as zf:
            return zf.read(str(self.path))

    def write_full(self, data):
        raise IOError(errno.EROFS, str(self.path))


class ZipArchiveStorageBackend(CachedStorageMixin, StorageBackend):
    '''
    ZIP archive storage. Read-only for now.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs-path",
                "description": "Path to the ZIP file",
            },
        }
    })
    TYPE = 'zip-archive'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.zip_path = Path(self.params['path'])
        self.read_only = True

        self.last_mtime = 0.
        self.last_size = -1

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--path'], metavar='PATH',
                         help='Path to the ZIP file',
                         required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'path': data['path'],
        }

    def _update(self):
        # Update when the ZIP file changes.
        st = self.zip_path.stat()
        if self.last_mtime != st.st_mtime or self.last_size != st.st_size:
            self._refresh()
            self.last_mtime = st.st_mtime
            self.last_size = st.st_size

    def clear_cache(self):
        super().clear_cache()
        with self.cache_lock:
            self.last_mtime = 0.
            self.last_size = -1

    def watch(self, stop: threading.Event) -> Iterator[List[FileEvent]]:
        current_stat = self._file_stat()
        current_info = self._file_info()
        while not stop.is_set():
            new_stat = self._file_stat()
            if new_stat != current_stat:
                logger.debug('file changed')
                new_info = self._file_info()
                self.clear_cache()
                yield list(self._compare_info(current_info, new_info))
                current_stat, current_info = new_stat, new_info
            stop.wait(1)

    @staticmethod
    def _compare_info(current_info, new_info):
        current_paths = set(current_info)
        new_paths = set(new_info)
        for path in current_paths - new_paths:
            yield FileEvent('delete', path)
        for path in new_paths - current_paths:
            yield FileEvent('create', path)
        for path in current_paths & new_paths:
            if current_info[path] != new_info[path]:
                yield FileEvent('modify', path)

    def _file_stat(self):
        try:
            st = self.zip_path.stat()
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime)

    def _file_info(self):
        try:
            return dict(self.info_all())
        except FileNotFoundError:
            return {}

    @staticmethod
    def _attr(zinfo: zipfile.ZipInfo) -> Attr:
        timestamp = int(datetime(*zinfo.date_time).timestamp())
        size = zinfo.file_size
        if zinfo.is_dir():
            return Attr.dir(size, timestamp)
        return Attr.file(size, timestamp)

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        with zipfile.ZipFile(self.zip_path) as zf:
            for zinfo in zf.infolist():
                path = PurePosixPath(zinfo.filename)
                yield path, self._attr(zinfo)

    def open(self, path: PurePosixPath, _mode: int) -> ZipArchiveFile:
        with zipfile.ZipFile(self.zip_path) as zf:
            try:
                zinfo = zf.getinfo(str(path))
            except KeyError:
                raise IOError(errno.ENOENT, str(path))

            if zinfo.is_dir():
                raise IOError(errno.EISDIR, str(path))

            attr = self._attr(zinfo)

        return ZipArchiveFile(self.zip_path, path, attr)
