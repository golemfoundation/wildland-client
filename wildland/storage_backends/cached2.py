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
Cached storage
'''

from typing import Dict, List, Tuple
import time
from pathlib import PurePosixPath
import errno
import logging

import fuse

from .base import StorageBackend, StorageBackendWrapper


logger = logging.getLogger('storage-cached')


def _clear_proxy(method_name):
    def method(self, *args, **kwargs):
        self._clear()
        return getattr(self.inner, method_name)(*args, **kwargs)

    method.__name__ = method_name
    return method


class CachedStorageBackend(StorageBackendWrapper):
    '''
    A storage backend that caches results about files.

    The inner backend must implement extra_info_all().
    '''

    CACHE_TIMEOUT = 3.

    def __init__(self, inner: StorageBackend):
        super().__init__(inner)
        self.info: List[Tuple[PurePosixPath, fuse.Stat]] = []
        self.getattr_cache: Dict[PurePosixPath, fuse.Stat] = {}
        self.readdir_cache: Dict[PurePosixPath, List[str]] = {}
        self.expiry = 0.

    def refresh(self):
        logger.info('refresh')

        self.inner.refresh()
        self.getattr_cache.clear()
        self.readdir_cache.clear()

        self.info = list(self.inner.extra_info_all())
        for path, attr in self.info:
            self.getattr_cache[path] = attr
            if path != PurePosixPath('.'):
                self.readdir_cache.setdefault(path.parent, []).append(path.name)

        logger.info(self.getattr_cache)

        self.expiry = time.time() + self.CACHE_TIMEOUT

    def _update(self):
        if self.expiry < time.time():
            self.refresh()

    def _clear(self):
        self.getattr_cache.clear()
        self.readdir_cache.clear()
        self.expiry = 0.

    def extra_info_all(self):
        self._update()
        return self.info

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        self._update()

        if path not in self.getattr_cache:
            raise FileNotFoundError(errno.ENOENT, str(path))

        return self.getattr_cache[path]

    def readdir(self, path: PurePosixPath) -> List[str]:
        self._update()
        if path not in self.readdir_cache:
            raise FileNotFoundError(errno.ENOENT, str(path))

        return sorted(self.readdir_cache[path])

    create = _clear_proxy('create')
    release = _clear_proxy('release')
    truncate = _clear_proxy('truncate')
    unlink = _clear_proxy('unlink')
    mkdir = _clear_proxy('mkdir')
    rmdir = _clear_proxy('rmdir')
