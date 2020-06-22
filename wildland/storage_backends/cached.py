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

from typing import Dict, List, Tuple, Iterable
import time
from pathlib import PurePosixPath
import errno
import logging

import fuse


logger = logging.getLogger('storage-cached')


class CachedStorageMixin:
    '''
    A mixin for caching file information.

    You need to implement info_all(), and invalidate cache (by calling clear())
    in all operations that might change the result
    '''

    CACHE_TIMEOUT = 3.

    def __init__(self, *args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(*args, **kwargs) # type: ignore

        self.info: List[Tuple[PurePosixPath, fuse.Stat]] = []
        self.getattr_cache: Dict[PurePosixPath, fuse.Stat] = {}
        self.readdir_cache: Dict[PurePosixPath, List[str]] = {}
        self.expiry = 0.

    def info_all(self) -> Iterable[Tuple[PurePosixPath, fuse.Stat]]:
        '''
        Retrieve information about all files in the storage.
        '''

        raise NotImplementedError()

    def refresh(self):
        '''
        Refresh cache.
        '''

        logger.info('refresh')

        self.getattr_cache.clear()
        self.readdir_cache.clear()

        self.info = list(self.info_all())
        for path, attr in self.info:
            self.getattr_cache[path] = attr
            if path != PurePosixPath('.'):
                self.readdir_cache.setdefault(path.parent, []).append(path.name)

        self.expiry = time.time() + self.CACHE_TIMEOUT

    def _update(self):
        if self.expiry < time.time():
            self.refresh()

    def clear(self):
        '''
        Invalidate cache.
        '''

        self.getattr_cache.clear()
        self.readdir_cache.clear()
        self.expiry = 0.

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        '''
        Cached implementation of getattr().
        '''

        self._update()

        if path not in self.getattr_cache:
            raise FileNotFoundError(errno.ENOENT, str(path))

        return self.getattr_cache[path]

    def readdir(self, path: PurePosixPath) -> List[str]:
        '''
        Cached implementation of readdir().
        '''

        self._update()
        if path not in self.readdir_cache:
            raise FileNotFoundError(errno.ENOENT, str(path))

        return sorted(self.readdir_cache[path])
