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

"""
A cached version of local storage.
"""

from typing import Iterable, Tuple, Optional
from pathlib import Path, PurePosixPath
import os
import errno
import time

import click

from .cached import CachedStorageMixin, DirectoryCachedStorageMixin
from .buffered import FullBufferedFile, PagedFile, File
from .base import StorageBackend, Attr, verify_local_access
from .local import LocalStorageWatcher
from ..manifest.schema import Schema


class LocalCachedFile(FullBufferedFile):
    """
    A fully buffered local file.
    """
    def __init__(self, attr, os_path, local_path, clear_cache_callback, ignore_callback=None):
        super().__init__(attr, clear_cache_callback)
        # we store separately os_path (path on disk, to use when accessing file) and wayland (local)
        # path (path in storage, used for events)
        self.os_path = os_path
        self.local_path = local_path
        self.ignore_callback = ignore_callback

    def read_full(self) -> bytes:
        with open(self.os_path, 'rb') as f:
            return f.read()

    def write_full(self, data: bytes) -> int:
        if self.ignore_callback:
            self.ignore_callback('modify', self.local_path)
        with open(self.os_path, 'wb') as f:
            return f.write(data)


class LocalCachedPagedFile(PagedFile):
    """
    A paged, read-only local file.
    """

    def __init__(self, local_path: Path, attr: Attr):
        super().__init__(attr)
        self.local_path = local_path

    def read_range(self, length, start) -> bytes:
        with open(self.local_path, 'rb') as f:
            f.seek(start)
            return f.read(length)


class BaseCached(StorageBackend):
    """
    A cached storage backed by local files. Used mostly to test the caching
    scheme.

    This backend should emulate "cloud" backends, therefore, we don't keep open
    file handles, but perform read()/write() operations opening the file each
    time.
    """

    SCHEMA = Schema({
        "type": "object",
        "required": ["location"],
        "properties": {
            "location": {
                "$ref": "/schemas/types.json#abs-path",
                "description": "Path in the local filesystem"
            }
        }
    })

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.root = Path(self.params['location'])

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--location'], metavar='PATH',
                         help='path in local filesystem',
                         required=True)
        ]

    @classmethod
    def cli_create(cls, data):
        return {'location': data['location']}

    @staticmethod
    def _stat(st: os.stat_result) -> Attr:
        """
        Convert os.stat_result to Attr.
        """

        return Attr(
            mode=st.st_mode,
            size=st.st_size,
            timestamp=int(st.st_mtime),
        )

    def _local(self, path: PurePosixPath) -> Path:
        return self.root / path

    def mount(self) -> None:
        verify_local_access(self.root, self.params['owner'],
                            self.params.get('is-local-owner', False))

    def open(self, path: PurePosixPath, flags: int) -> File:
        if isinstance(path, str):
            path = PurePosixPath(path)
        attr = self.getattr(path)
        if flags & (os.O_WRONLY | os.O_RDWR):
            if self.ignore_own_events and self.watcher_instance:
                return LocalCachedFile(
                    attr, os_path=self._local(path), local_path=path,
                    clear_cache_callback=self.clear_cache,
                    ignore_callback=self.watcher_instance.ignore_event)
            return LocalCachedFile(attr, os_path=self._local(path), local_path=path,
                                   clear_cache_callback=self.clear_cache)
        return LocalCachedPagedFile(self._local(path), attr)

    def create(self, path: PurePosixPath, flags: int, mode: int = 0o666):
        if isinstance(path, str):
            path = PurePosixPath(path)

        local = self._local(path)
        if local.exists():
            raise IOError(errno.EEXIST, str(path))
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('create', path)

        local.write_bytes(b'')

        self.clear_cache()
        attr = self.getattr(path)

        if self.ignore_own_events and self.watcher_instance:
            return LocalCachedFile(attr, os_path=self._local(path), local_path=path,
                                   clear_cache_callback=self.clear_cache,
                                   ignore_callback=self.watcher_instance.ignore_event)
        return LocalCachedFile(attr, os_path=self._local(path), local_path=path,
                               clear_cache_callback=self.clear_cache)

    def truncate(self, path: PurePosixPath, length: int) -> None:
        os.truncate(self._local(path), length)
        self.clear_cache()

    def unlink(self, path: PurePosixPath):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('delete', path)
        self._local(path).unlink()
        self.clear_cache()

    def mkdir(self, path: PurePosixPath, mode: int = 0o777):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('create', path)
        self._local(path).mkdir(mode)
        self.clear_cache()

    def rmdir(self, path: PurePosixPath):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('delete', path)
        self._local(path).rmdir()
        self.clear_cache()

    def chmod(self, path: PurePosixPath, mode: int):
        os.chmod(self._local(path), mode)
        self.clear_cache()

    def chown(self, path: PurePosixPath, uid: int, gid: int):
        os.chown(self._local(path), uid, gid)
        self.clear_cache()

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('create', move_to)
            self.watcher_instance.ignore_event('delete', move_from)

        os.rename(self._local(move_from), self._local(move_to))
        self.clear_cache()

    def utimens(self, path: str, atime, mtime):
        atime_ns = atime.tv_sec * 1e9 + atime.tv_nsec
        mtime_ns = mtime.tv_sec * 1e9 + mtime.tv_nsec

        os.utime(self._local(path), ns=(atime_ns, mtime_ns))
        self.clear_cache()

    def watcher(self):
        """
        If manifest explicitly specifies a watcher-delay, use default implementation. If not, we can
        use the smarter LocalStorageWatcher.
        """
        default_watcher = super().watcher()
        if not default_watcher:
            return LocalStorageWatcher(self)
        return default_watcher

    def get_file_token(self, path: PurePosixPath) -> Optional[str]:
        try:
            current_timestamp = os.stat(self._local(path)).st_mtime
        except NotADirectoryError:
            # can occur due to extreme file conflicts across storages
            return None
        if abs(time.time() - current_timestamp) < 0.001:
            # due to filesystem lack of resolution, two changes less than 1 millisecond apart
            # can have the same mtime. We assume 1 millisecond, as it's correct for EXT4,
            # but be warned: it can go as high as 2 seconds for FAT16/32
            return None
        return str(int(current_timestamp * 1000))


class LocalCachedStorageBackend(CachedStorageMixin, BaseCached):
    """
    A cached storage that uses info_all().
    """

    TYPE = 'local-cached'

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        Load information about all files and directories.
        """

        try:
            st = os.stat(self.root)
        except IOError:
            return

        yield PurePosixPath('.'), self._stat(st)

        for root_s, dirs, files in os.walk(self.root):
            root = Path(root_s)
            rel_root = PurePosixPath(root.relative_to(self.root))
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
    """
    A cached storage that uses info_dir().
    """

    TYPE = 'local-dir-cached'

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, Attr]]:
        """
        Load information about a single directory.
        """

        for name in os.listdir(self._local(path)):
            attr = self._stat(os.stat(self._local(path) / name))
            yield name, attr
