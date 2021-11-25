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
Conflict resolution
"""

import abc
import functools
import stat
from pathlib import PurePosixPath
from typing import List, Dict, Set, Tuple, Optional, Iterable
import re
import dataclasses
import errno

from .storage_backends.base import Attr
from .log import get_logger

logger = get_logger('conflict')

@dataclasses.dataclass
class Resolved:
    """
    A path resolution result.
    """

    # Storage ID
    ident: int

    # Relative path inside (if inside), or relative path of the mount path (if not inside)
    relpath: PurePosixPath


class MountDir:
    """
    A prefix tree for storing information about mounted storages.
    """

    def __init__(self):
        self.storage_ids: Set[int] = set()
        self.children: Dict[str, 'MountDir'] = {}

    def is_empty(self):
        """
        Is this node ready for deletion (i.e. no storages left)?
        """

        return len(self.children) == 0 and len(self.storage_ids) == 0

    def mount(self, path: PurePosixPath, storage_id: int):
        """
        Add a storage under the given path.
        """

        mount_dir = self

        while path.parts:
            first = path.parts[0]
            if first not in mount_dir.children:
                mount_dir.children[first] = MountDir()
            mount_dir = mount_dir.children[first]
            path = path.relative_to(first)

        assert str(path) == '.' or str(path) == ''
        mount_dir.storage_ids.add(storage_id)

    def unmount(self, path: PurePosixPath, storage_id: int):
        """
        Remove a storage from the given path.
        """

        if not path.parts:
            self.storage_ids.remove(storage_id)
            return

        first = path.parts[0]
        rest = path.relative_to(first)
        assert first in self.children
        self.children[first].unmount(rest, storage_id)
        if self.children[first].is_empty():
            del self.children[first]

    def is_synthetic(self, path: PurePosixPath) -> bool:
        """
        Is this a synthetic directory?

        A synthetic directory is one where either more than one storage is mounted, or there are
        storages mounted on the path deeper. For example: if there are storages mounted in
        ``/foo/bar`` and ``/foo/bar/baz``, then ``/``, ``/foo``, ``/foo/bar`` are synthetic
        directories and ``/foo/bar/baz`` is not.

        Returns ``False`` for paths not present in the prefix tree.
        """

        mount_dir = self

        while path.parts:
            first = path.parts[0]
            if first not in mount_dir.children:
                return False
            mount_dir = mount_dir.children[first]
            path = path.relative_to(first)

        return len(mount_dir.children) != 0 or len(mount_dir.storage_ids) != 1

    def readdir(self, path: PurePosixPath) -> Optional[Iterable[str]]:
        """
        List sub-directories under given path. Returns ``None`` if the given path is not present in
        the prefix tree.
        """

        mount_dir = self

        while path.parts:
            first = path.parts[0]
            if first not in mount_dir.children:
                return None
            mount_dir = mount_dir.children[first]
            path = path.relative_to(first)

        return mount_dir.children.keys()

    def resolve(self, path: PurePosixPath) -> Iterable[Resolved]:
        """
        Find all storages that could be responsible for the given path. Effectively returns all
        storage IDs from all of the ``MountDir`` nodes that are on the given ``path`` together with
        their corresponding paths.
        """

        for storage_id in self.storage_ids:
            yield Resolved(storage_id, path)

        if path.parts:
            first = path.parts[0]
            if first in self.children:
                rest = path.relative_to(first)
                yield from self.children[first].resolve(rest)

    def relative_storage_ids(self) -> Iterable[int]:
        """
        Return storage ids relative to itself.
        """

        for storage_id in self.storage_ids:
            yield storage_id

        for _, child in self.children.items():
            if isinstance(child, MountDir):
                for storage_id in child.relative_storage_ids():
                    yield storage_id


class ConflictResolver(metaclass=abc.ABCMeta):
    """
    Helper class for object resolution. To use, subclass and override the abstract methods.

    The :meth:`~wildland.conflict.ConflictResolver.storage_getattr` and
    :meth:`~wildland.conflict.ConflictResolver.storage_listdir` methods will not be called until it
    is necessary for conflict resolution. However, it is assumed that subsequent calls are cheap
    (it's local filesystem, or results are cached).

    The conflict resolution rules are as follows:
    - If there are multiple directories with the same name, create a synthetic directory with this
      name. If more that one backing storage is writable, the directory is forced to be read only
      (i.e. the list of files cannot be modified, but the files themselves can).
    - If there are multiple files with the same name, or a single file with the same name as
      directory, the file name is changed to '{name.stem}.wl_{storage}.{name.suffix}' (with stem and
      suffix being PurePosixPath semantic).

    For examples, look at tests/test_conflict.py.
    """

    CONFLICT_FORMAT = r'{}.wl_{}{}'  # name.stem, id, name.suffix
    CONFLICT_RE = r'^(.*).wl_(\d+)(.*)$'

    def __init__(self):
        self.root: MountDir = MountDir()

    def mount(self, path: PurePosixPath, storage_id: int):
        """
        Add information about a mounted storage.
        """

        self.root.mount(path, storage_id)
        self._resolve.cache_clear()

    def unmount(self, path: PurePosixPath, storage_id: int):
        """
        Remove information about a mounted storage.
        """

        self.root.unmount(path, storage_id)
        self._resolve.cache_clear()

    @abc.abstractmethod
    def storage_getattr(self, ident: int, relpath: PurePosixPath) -> Attr:
        """
        Execute getattr() on a path in storage.
        Raise an IOError if the file cannot be accessed.

        If the path is None, return the right
        """

        raise NotImplementedError()

    @abc.abstractmethod
    def storage_readdir(self, ident: int, relpath: PurePosixPath) -> List[str]:
        """
        Execute readdir() on a path in storage.
        Raise IOError if the path cannot be accessed.
        """

        raise NotImplementedError()

    def readdir(self, path: PurePosixPath) -> List[str]:
        """
        List directory.

        Raise IOError if the path cannot be accessed.
        """

        resolved = self._resolve(path)
        synthetic = self.root.readdir(path)

        if len(resolved) == 0 and synthetic is None:
            if path == PurePosixPath('/'):
                return []
            raise FileNotFoundError(errno.ENOENT, '')

        result: Set[str] = set()
        if synthetic is not None:
            result.update(synthetic)

        # Only one storage to list, and no synthetic storages.
        # Note that this is the only case where we do NOT call
        # handle_io_error(), but allow the error to fall through.
        if len(resolved) == 1 and not result:
            names = self.storage_readdir(resolved[0].ident, resolved[0].relpath)
            result.update(names or [])
            return sorted(result)

        res_dirs = []
        res_files = []
        for res in resolved:
            st = handle_io_error(self.storage_getattr, res.ident, res.relpath)
            if st is None:
                continue
            if stat.S_ISDIR(st.mode):
                res_dirs.append(res)
            else:
                res_files.append(res)

        if len(res_dirs) == 0 and not result:
            if len(res_files) == 0:
                # Nothing found
                raise FileNotFoundError(errno.ENOENT, '')
            if len(res_files) == 1:
                # This is a file
                raise NotADirectoryError(errno.ENOTDIR, '')
            # There are multiple files with that name, they will be renamed
            raise FileNotFoundError(errno.ENOENT, '')

        # Only one directory storage to list, no need to disambiguate files
        if len(res_dirs) == 1:
            names = handle_io_error(self.storage_readdir, res_dirs[0].ident, res_dirs[0].relpath)
            result.update(names or [])
            return sorted(result)

        seen: Dict[str, List[Resolved]] = {}
        for res in res_dirs:
            names = handle_io_error(self.storage_readdir, res.ident, res.relpath) or []
            for name in names:
                seen.setdefault(name, []).append(res)

        for name, resolved in seen.items():
            # No conflict, just add the name without changing.
            if len(resolved) == 1 and name not in result:
                result.add(name)
                continue

            for res in resolved:
                st = handle_io_error(self.storage_getattr, res.ident, res.relpath / name)
                if st is None:
                    # Treat inaccessible files as files, not directories.
                    pname = PurePosixPath(name)
                    result.add(self.CONFLICT_FORMAT.format(pname.stem, res.ident, pname.suffix))
                elif stat.S_ISDIR(st.mode):
                    result.add(name)
                else:
                    pname = PurePosixPath(name)
                    result.add(self.CONFLICT_FORMAT.format(pname.stem, res.ident, pname.suffix))

        return sorted(result)

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Get file attributes. Raise ``FileNotFoundError`` if necessary.
        """
        st, _ = self.getattr_extended(path)
        return st

    def getattr_extended(self, path: PurePosixPath) -> Tuple[Attr, Optional[Resolved]]:
        """
        Resolve the path to the right storage and run ``getattr()`` on the right storage(s). Raises
        ``FileNotFoundError`` if file cannot be found.

        Returns a tuple (st, res):
          st (Attr): file attributes; possibly overridden to be read-only
          res (Resolved): resolution result (if there is exactly one)
        """


        m = re.match(self.CONFLICT_RE, path.name)
        ident: Optional[int]
        if m:
            real_path = path.with_name(m.group(1) + m.group(3))
            ident = int(m.group(2))
        else:
            real_path = path
            ident = None

        resolved = self._resolve(real_path)
        file_results: List[Tuple[Attr, Resolved]] = []
        dir_results: List[Tuple[Attr, Resolved]] = []

        for res in resolved:
            st = handle_io_error(self.storage_getattr, res.ident, res.relpath)
            if st is None:
                continue
            if stat.S_ISDIR(st.mode):
                dir_results.append((st, res))
            else:
                file_results.append((st, res))

        if self.root.is_synthetic(real_path):
            writable_dirs = [res for res in dir_results
                             if res[0].mode & 0o200]
            if len(writable_dirs) == 1:
                # there is exactly one writable storage,
                # so we know where to put new files - return that
                return writable_dirs[0]
            return Attr(
                mode=stat.S_IFDIR | 0o555,
            ), None

        if len(resolved) == 0:
            if path == PurePosixPath('/'):
                return Attr(
                    mode=stat.S_IFDIR | 0o555,
                ), None
            raise FileNotFoundError(errno.ENOENT, '')

        if len(resolved) == 1:
            if ident is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            # Single storage. Run storage_getattr directly so that all IOErrors
            # can be propagated to caller.

            res = resolved[0]
            st = self.storage_getattr(res.ident, res.relpath)
            return (st, res)

        if len(dir_results) == 1:
            # This is a directory in a single storage.
            if ident is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            return dir_results[0]

        if len(dir_results) > 1:
            # Multiple directories, return a synthetic read-only directory if writable storage
            # cannot be unambiguously found.
            if ident is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            writable_dirs = [res for res in dir_results
                             if res[0].mode & 0o200]
            if len(writable_dirs) != 1:
                st = Attr(
                    mode=stat.S_IFDIR | 0o555,
                )
                return (st, None)
            return writable_dirs[0]

        if len(file_results) == 1:
            # This is a single file, not conflicting with anything.
            if ident is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            return file_results[0]

        if len(file_results) > 1:
            # There are multiple files, so expect an added id.
            if ident is None:
                raise FileNotFoundError(errno.ENOENT, '')
            for st, res in file_results:
                if res.ident == ident:
                    return (st, res)
            raise FileNotFoundError(errno.ENOENT, '')

        # Nothing found.
        assert len(file_results) == len(dir_results) == 0
        raise FileNotFoundError(errno.ENOENT, '')

    def find_storage_ids(self, path):
        """
        Return a list of storage ids that claim the given path.
        """
        start_from = self.root
        real_storages = []

        # Try to resolve a physical (real) storages that claim this path
        resolved = self._resolve(PurePosixPath(path))
        for res in resolved:
            st = handle_io_error(self.storage_getattr, res.ident, res.relpath)
            if st and stat.S_ISDIR(st.mode):
                real_storages.append(res.ident)

        for part in path.parts:
            if part in start_from.children:
                if not isinstance(start_from.children[part], MountDir):
                    # we've hit an actual, physical directory but we haven't traversed through
                    # all parts
                    return real_storages

                # Move one level down in the mounted directories tree
                start_from = start_from.children[part]
            else:
                # We couldn't reach end of path, returning possible physical storages only
                return real_storages

        # We've reached end of path and didn't hit the actual storage
        # That means we were resolving a mounted path (container path)
        # and return possible real storages discovered earlier
        return real_storages + list(start_from.relative_storage_ids())

    @functools.lru_cache(500)
    def _resolve(self, real_path):
        return list(self.root.resolve(real_path))


def handle_io_error(func, *args):
    """
    Run a function, suppressing IOErrors and returning None instead.
    """

    try:
        return func(*args)
    except IOError:
        return None
