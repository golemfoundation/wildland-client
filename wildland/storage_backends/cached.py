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

import abc
import errno
import threading
import time
from pathlib import PurePosixPath
from typing import Dict, Iterable, Optional, Set, Tuple

from .base import Attr
from ..log import get_logger

logger = get_logger('storage-cached')


class BaseCachedStorageMixin(metaclass=abc.ABCMeta):
    """
    Base class for caching mixins.
    """

    DEFAULT_CACHE_TIMEOUT = 3.

    def __init__(self, *_args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(**kwargs)  # type: ignore
        self.getattr_cache: Dict[PurePosixPath, Attr] = {}
        self.readdir_cache: Dict[PurePosixPath, Set[str]] = {}
        self.cache_lock = threading.Lock()
        self._cache_timeout = self.DEFAULT_CACHE_TIMEOUT

    @property
    def cache_timeout(self) -> float:
        """
        Cache timeout.
        """
        return self._cache_timeout

    @cache_timeout.setter
    def cache_timeout(self, value: float) -> None:
        assert value >= 0.
        self._cache_timeout = value

    def _update_cache(self, path: PurePosixPath, attr: Optional[Attr]) -> None:
        if attr is None:
            self.getattr_cache.pop(path, None)
            self.readdir_cache.pop(path, None)
            return

        self.getattr_cache[path] = attr

        if attr.is_dir():
            self.readdir_cache.setdefault(path, set())

    def update_cache(self, path: PurePosixPath, attr: Optional[Attr]) -> None:
        """
        Update item in the cache instead of invalidating cache as a whole. This method does _not_
        invalidate children of given ``path`` if it refers to a directory, thus you need to call
        ``update_cache`` on children separately if applicable.
        """

        with self.cache_lock:
            self._update_cache(path, attr)

    @abc.abstractmethod
    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        """
        Cached implementation of ``readdir()``.
        """

        raise NotImplementedError()

    @abc.abstractmethod
    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Cached implementation of ``getattr()``. If ``path`` is not in ``self.getattr_cache`` but is
        in ``self.readdir_cache`` then ``Attr.dir()`` should be returned as an directory's attribute
        (indicates a synthetic directory).
        """

        raise NotImplementedError()

    @abc.abstractmethod
    def clear_cache(self) -> None:
        """
        Invalidate the cache.
        """

        raise NotImplementedError()


class CachedStorageMixin(BaseCachedStorageMixin):
    """
    A mixin for caching file information.

    You need to implement ``info_all()``, and invalidate cache (by calling ``clear_cache()`` or
    ``update_cache()``) in all operations that might change the result.
    """

    def __init__(self, *args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(*args, **kwargs)  # type: ignore
        self.expiry = 0.

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        Retrieve information about all files in the storage.
        """

        raise NotImplementedError()

    def refresh(self) -> None:
        """
        Refresh cache.
        """

        with self.cache_lock:
            self._refresh()

    def _refresh(self) -> None:
        logger.debug('refresh')
        self.getattr_cache.clear()
        self.readdir_cache.clear()
        self.readdir_cache[PurePosixPath('.')] = set()

        info: Iterable[Tuple[PurePosixPath, Attr]] = self.info_all()
        for path, attr in info:
            self._update_cache(path, attr)

        self.expiry = time.time() + self.cache_timeout

    def update_cache(self, path: PurePosixPath, attr: Optional[Attr]) -> None:
        """
        Update item in the cache instead of invalidating all of the items.
        """

        with self.cache_lock:
            self._update_cache(path, attr)

    def _update_cache(self, path: PurePosixPath, attr: Optional[Attr]) -> None:
        super()._update_cache(path, attr)

        # Add all intermediate directories, in case ``info_all()`` didn't include them
        for i in range(len(path.parts)):
            self.readdir_cache.setdefault(
                PurePosixPath(*path.parts[:i]),
                set()
            ).add(path.parts[i])

    def _update(self) -> None:
        if self.expiry < time.time():
            self._refresh()

    def clear_cache(self) -> None:
        """
        Invalidate cache.
        """

        with self.cache_lock:
            self.getattr_cache.clear()
            self.readdir_cache.clear()
            self.expiry = 0.

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Cached implementation of ``getattr()``.
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

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        """
        Cached implementation of ``readdir()``.
        """

        if isinstance(path, str):
            path = PurePosixPath(path)

        with self.cache_lock:
            self._update()

            if path not in self.readdir_cache:
                raise FileNotFoundError(errno.ENOENT, str(path))

            return sorted(self.readdir_cache[path])


class DirectoryCachedStorageMixin(BaseCachedStorageMixin):
    """
    A mixin for caching file information about a specific directory.

    You need to implement ``info_dir()``, and invalidate the cache (by calling ``clear_cache()`` or
    ``update_cache()``) in all operations that might change the result.
    """

    def __init__(self, *args, **kwargs):
        # Silence mypy: https://github.com/python/mypy/issues/5887
        super().__init__(*args, **kwargs)  # type: ignore

        self.dir_expiry: Dict[PurePosixPath, float] = {}

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        Retrieve information about files in a directory (``readdir`` + ``getattr``).
        """

        raise NotImplementedError()

    def _update_dir(self, path: PurePosixPath) -> None:
        if self.dir_expiry.get(path, 0) >= time.time():
            return

        if path in self.dir_expiry:
            self._clear_dir(path)

        self._refresh_dir(path)

    def _clear_dir(self, path: PurePosixPath) -> None:
        del self.dir_expiry[path]

        if path in self.readdir_cache:
            del self.readdir_cache[path]

        for getattr_path in list(self.getattr_cache.keys()):
            if getattr_path.parent == path:
                del self.getattr_cache[getattr_path]

    def _refresh_dir(self, path: PurePosixPath) -> None:
        names: Set[str] = set()
        try:
            for file_path, attr in self.info_dir(path):
                name = file_path.name
                names.add(name)
                self.getattr_cache[path / name] = attr
        except PermissionError as e:
            raise e
        except OSError as e:
            # Don't store anything in readdir_cache, we will assume that the
            # directory does not exist.
            logger.exception(e)
        else:
            self.readdir_cache[path] = names

        self.dir_expiry[path] = time.time() + self.cache_timeout

    def clear_cache(self) -> None:
        """
        Invalidate the cache.
        """

        with self.cache_lock:
            self.getattr_cache.clear()
            self.readdir_cache.clear()
            self.dir_expiry.clear()

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Cached implementation of ``getattr()``.
        """

        if isinstance(path, str):
            path = PurePosixPath(path)

        # We don't retrieve any information about the root directory's attributes
        if path == PurePosixPath('.'):
            return Attr.dir()

        with self.cache_lock:
            self._update_dir(path.parent)

            if path not in self.getattr_cache:
                raise FileNotFoundError(errno.ENOENT, str(path))

            return self.getattr_cache[path]

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        """
        Cached implementation of ``readdir()``.
        """

        if isinstance(path, str):
            path = PurePosixPath(path)

        with self.cache_lock:
            self._update_dir(path)

            if path not in self.readdir_cache:
                raise FileNotFoundError(errno.ENOENT, str(path))

            return sorted(self.readdir_cache[path])
