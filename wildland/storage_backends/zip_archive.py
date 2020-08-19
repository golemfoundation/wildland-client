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

from typing import Iterable, Tuple, List, Optional
import zipfile
from pathlib import Path, PurePosixPath
from datetime import datetime
import errno
import logging

import click

from ..manifest.schema import Schema
from .cached import CachedStorageMixin
from .buffered import FullBufferedFile
from .base import StorageBackend, Attr
from .watch import StorageWatcher, FileEvent


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


class ZipArchiveWatcher(StorageWatcher):
    '''
    A watcher for the ZIP file.
    '''

    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.zip_path = self.backend.zip_path

        self.stat = None
        self.info = None

    def init(self):
        self.stat = self._get_stat()
        self.info = self._get_info()

    def wait(self) -> Optional[List[FileEvent]]:
        self.stop_event.wait(1)
        new_stat = self._get_stat()
        if new_stat != self.stat:
            logger.debug('file changed')
            new_info = self._get_info()
            result = list(self._compare_info(self.info, new_info))

            self.stat = new_stat
            self.info = new_info
            if result:
                self.backend.clear_cache()
                return result
            return None
        return None

    def shutdown(self):
        pass

    def _get_stat(self):
        try:
            st = self.zip_path.stat()
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime)

    def _get_info(self):
        try:
            return dict(self.backend.info_all())
        except FileNotFoundError:
            return {}

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

    def watcher(self):
        return ZipArchiveWatcher(self)

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
