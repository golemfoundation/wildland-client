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

from .util import simple_dir_stat


logger = logging.getLogger('storage-cached')


class CachedStorageMixin:
    '''
    A mixin for caching file information.

    You need to implement info_all(), and invalidate cache (by calling
    clear_cache()) in all operations that might change the result.
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

    def clear_cache(self):
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


class DirectoryCachedStorageMixin:
    '''
    A mixin for caching file information about a specific directory.

    You need to implement info_dir(), and invalidate cache (by calling
    clear_cache()) in all operations that might change the result.
    '''

    CACHE_TIMEOUT = 3.

    def __init__(self, *args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(*args, **kwargs) # type: ignore

        self.getattr_cache: Dict[PurePosixPath, fuse.Stat] = {}
        self.readdir_cache: Dict[PurePosixPath, List[str]] = {}
        self.dir_expiry: Dict[PurePosixPath, float] = {}

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, fuse.Stat]]:
        '''
        Retrieve information about files in a directory (readdir + getattr).
        '''

        raise NotImplementedError()

    def _clear_dir(self, path: PurePosixPath):
        del self.dir_expiry[path]
        if path in self.readdir_cache:
            del self.readdir_cache[path]
        for getattr_path in list(self.getattr_cache.keys()):
            if getattr_path.parent == path:
                del self.getattr_cache[getattr_path]

    def _refresh_dir(self, path: PurePosixPath):
        names = []
        try:
            for name, attr in self.info_dir(path):
                names.append(name)
                self.getattr_cache[path / name] = attr
        except IOError as e:
            # Don't store anything in readdir_cache, we will assume that the
            # directory does not exist.
            logger.exception(e)
        else:
            self.readdir_cache[path] = names

        self.dir_expiry[path] = time.time() + self.CACHE_TIMEOUT

    def _update_dir(self, path: PurePosixPath):
        if self.dir_expiry.get(path, 0) >= time.time():
            return

        if path in self.dir_expiry:
            self._clear_dir(path)

        self._refresh_dir(path)

    def clear_cache(self):
        '''
        Invalidate cache.
        '''

        self.getattr_cache.clear()
        self.readdir_cache.clear()
        self.dir_expiry.clear()

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        '''
        Cached implementation of getattr().
        '''

        # We don't retrieve any information about the root directory's
        # attributes.
        if path == PurePosixPath('.'):
            return simple_dir_stat()

        self._update_dir(path.parent)

        if path not in self.getattr_cache:
            raise FileNotFoundError(errno.ENOENT, str(path))

        return self.getattr_cache[path]

    def readdir(self, path: PurePosixPath) -> List[str]:
        '''
        Cached implementation of readdir().
        '''

        self._update_dir(path)

        if path not in self.readdir_cache:
            raise FileNotFoundError(errno.ENOENT, str(path))

        return sorted(self.readdir_cache[path])
