# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Cached storage
"""

from typing import Dict, List, Tuple, Iterable, Set, Optional
import time
from pathlib import PurePosixPath
import errno
import threading

from .base import Attr
from ..log import get_logger

logger = get_logger('storage-cached')


class CachedStorageMixin:
    """
    A mixin for caching file information.

    You need to implement info_all(), and invalidate cache (by calling
    clear_cache()) in all operations that might change the result.
    """

    CACHE_TIMEOUT = 3.

    def __init__(self, *args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(*args, **kwargs)  # type: ignore

        self.info: List[Tuple[PurePosixPath, Attr]] = []
        self.getattr_cache: Dict[PurePosixPath, Attr] = {}
        self.readdir_cache: Dict[PurePosixPath, Set[str]] = {}
        self.expiry = 0.
        self.cache_lock = threading.Lock()

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        Retrieve information about all files in the storage.
        """

        raise NotImplementedError()

    def refresh(self):
        """
        Refresh cache.
        """

        with self.cache_lock:
            self._refresh()

    def _refresh(self):
        logger.info('refresh')

        self.getattr_cache.clear()
        self.readdir_cache.clear()
        self.readdir_cache[PurePosixPath('.')] = set()

        self.info = list(self.info_all())
        for path, attr in self.info:
            self._update_cache(path, attr)

        self.expiry = time.time() + self.CACHE_TIMEOUT

    def _update_cache(self, path: PurePosixPath, attr: Optional[Attr]) -> None:
        if attr is None:
            self.getattr_cache.pop(path, None)
            self.readdir_cache.pop(path, None)
            return

        self.getattr_cache[path] = attr

        if attr.is_dir():
            self.readdir_cache.setdefault(path, set())

        # Add all intermediate directories, in case info_all()
        # didn't include them.
        for i in range(len(path.parts)):
            self.readdir_cache.setdefault(
                PurePosixPath(*path.parts[:i]), set()).add(
                path.parts[i])

    def _update(self):
        if self.expiry < time.time():
            self._refresh()

    def clear_cache(self):
        """
        Invalidate cache.
        """

        with self.cache_lock:
            self.getattr_cache.clear()
            self.readdir_cache.clear()
            self.expiry = 0.

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Cached implementation of getattr().
        """
        if isinstance(path, str):
            path = PurePosixPath(path)
        with self.cache_lock:
            self._update()

            if path not in self.getattr_cache:
                # Synthetic directory
                if path in self.readdir_cache:
                    return Attr.dir()

                raise FileNotFoundError(errno.ENOENT, str(path))

            return self.getattr_cache[path]

    def readdir(self, path: PurePosixPath) -> List[str]:
        """
        Cached implementation of readdir().
        """
        if isinstance(path, str):
            path = PurePosixPath(path)

        with self.cache_lock:
            self._update()
            if path not in self.readdir_cache:
                raise FileNotFoundError(errno.ENOENT, str(path))

            return sorted(self.readdir_cache[path])


class DirectoryCachedStorageMixin:
    """
    A mixin for caching file information about a specific directory.

    You need to implement info_dir(), and invalidate cache (by calling
    clear_cache()) in all operations that might change the result.
    """

    CACHE_TIMEOUT = 3.

    def __init__(self, *args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(*args, **kwargs)  # type: ignore

        self.getattr_cache: Dict[PurePosixPath, Attr] = {}
        self.readdir_cache: Dict[PurePosixPath, List[str]] = {}
        self.dir_expiry: Dict[PurePosixPath, float] = {}
        self.cache_lock = threading.Lock()

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        Retrieve information about files in a directory (readdir + getattr).
        """

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
            for filePath, attr in self.info_dir(path):
                names.append(filePath.name)
                self.getattr_cache[filePath] = attr
        except PermissionError as e:
            raise e
        except OSError as e:
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
        """
        Invalidate cache.
        """

        with self.cache_lock:
            self.getattr_cache.clear()
            self.readdir_cache.clear()
            self.dir_expiry.clear()

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Cached implementation of getattr().
        """
        if isinstance(path, str):
            path = PurePosixPath(path)
        # We don't retrieve any information about the root directory's
        # attributes.
        if path == PurePosixPath('.'):
            return Attr.dir()

        with self.cache_lock:
            self._update_dir(path.parent)

            if path not in self.getattr_cache:
                raise FileNotFoundError(errno.ENOENT, str(path))

            return self.getattr_cache[path]

    def readdir(self, path: PurePosixPath) -> List[str]:
        """
        Cached implementation of readdir().
        """
        if isinstance(path, str):
            path = PurePosixPath(path)
        with self.cache_lock:
            self._update_dir(path)

            if path not in self.readdir_cache:
                raise FileNotFoundError(errno.ENOENT, str(path))

            return sorted(self.readdir_cache[path])
