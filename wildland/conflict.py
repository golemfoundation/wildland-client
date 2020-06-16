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
Conflict resolution
'''

import abc
import stat
from pathlib import PurePosixPath
from typing import List, Dict, Set, Tuple, Optional
import re
import dataclasses
import errno

import fuse


@dataclasses.dataclass
class Resolved:
    '''
    A path resolution result.
    '''
    # Storage ID
    ident: int

    # Whether we're inside (not just on a mount path)
    is_inside: bool

    # Relative path inside (if inside), or relative path of the mount path
    # (if not inside)
    relpath: PurePosixPath


class ConflictResolver(metaclass=abc.ABCMeta):
    '''
    Helper class for object resolution. To use, subclass and override the
    abstract methods.

    The storage_getattr() and storage_listdir() methods will not be called
    until it is necessary for conflict resolution. However, it is assumed that
    subsequent calls are cheap (it's local filesystem, or results are cached).

    The conflict resolution rules are as follows:
    - If there are multiple directories with the same name, create a synthetic
      directory with this name. The directory is read only (i.e. the list of
      files cannot be modified, but the files themselves can).
    - If there are multiple files with the same name, or a single file with the
      same name as directory, add a '.wl.<storage>' suffix to the name.

    For examples, look at tests/test_conflict.py.
    '''

    SUFFIX_FORMAT = '{}.wl.{}'
    SUFFIX_RE = re.compile(r'^(.*).wl.(\d+)$')

    @abc.abstractmethod
    def get_storage_paths(self) -> Dict[int, List[PurePosixPath]]:
        '''
        Get list of mounted storages along with their mount paths.
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def storage_getattr(self, ident: int, relpath: PurePosixPath) \
        -> fuse.Stat:
        '''
        Execute getattr() on a path in storage.
        Raise an IOError if the file cannot be accessed.

        If the path is None, return the right
        '''

        raise NotImplementedError()

    @abc.abstractmethod
    def storage_readdir(self, ident: int, relpath: PurePosixPath) \
        -> List[str]:
        '''
        Execute readdir() on a path in storage.
        Raise IOError if the path cannot be accessed.
        '''

        raise NotImplementedError()

    def _resolve(self, path: PurePosixPath) -> \
        List[Resolved]:
        result = []
        for ident, mount_paths in self.get_storage_paths().items():
            for mount_path in mount_paths:
                if mount_path == path or mount_path in path.parents:
                    result.append(Resolved(ident, True, path.relative_to(mount_path)))
                elif path in mount_path.parents:
                    result.append(Resolved(ident, False, mount_path.relative_to(path)))
        return result

    def _storage_readdir(self, res: Resolved):
        if res.is_inside:
            return self.storage_readdir(res.ident, res.relpath)
        return [res.relpath.parts[0]]

    def _storage_getattr(self, res: Resolved):
        if res.is_inside:
            return self.storage_getattr(res.ident, res.relpath)
        return fuse.Stat(
            st_mode=stat.S_IFDIR | 0o555,
            st_nlink=1,
            st_uid=None,
            st_gid=None,
        )

    def readdir(self, path: PurePosixPath) -> List[str]:
        '''
        List directory.

        Raise IOError if the path cannot be accessed.
        '''
        resolved = self._resolve(path)
        if len(resolved) == 0:
            raise FileNotFoundError(errno.ENOENT, '')

        if len(resolved) == 1:
            return sorted(self._storage_readdir(resolved[0]))

        res_dirs = []
        res_files = []
        for res in resolved:
            st = handle_io_error(self._storage_getattr, res)
            if st is None:
                continue
            if stat.S_ISDIR(st.st_mode):
                res_dirs.append(res)
            else:
                res_files.append(res)

        if len(res_dirs) == 0:
            if len(res_files) == 0:
                # Nothing found
                raise FileNotFoundError(errno.ENOENT, '')
            if len(res_files) == 1:
                # This is a file
                raise NotADirectoryError(errno.ENOTDIR, '')
            # There are multiple files with that name, they will be renamed
            raise FileNotFoundError(errno.ENOENT, '')

        if len(res_dirs) == 1:
            return sorted(self._storage_readdir(res_dirs[0]))

        seen: Dict[str, List[Resolved]] = {}
        for res in res_dirs:
            names = handle_io_error(self._storage_readdir, res) or []
            for name in names:
                seen.setdefault(name, []).append(res)

        result: Set[str] = set()
        for name, resolved in seen.items():
            if len(resolved) == 1:
                result.add(name)
                continue
            for res in resolved:
                if res.is_inside:
                    st = handle_io_error(self.storage_getattr, res.ident, res.relpath / name)
                    if st is None:
                        # Treat inaccessible files as files, not directories.
                        result.add(self.SUFFIX_FORMAT.format(name, res.ident))
                    elif stat.S_ISDIR(st.st_mode):
                        result.add(name)
                    else:
                        result.add(self.SUFFIX_FORMAT.format(name, res.ident))
                else:
                    # This is a subdirectory under a synthetic path.
                    result.add(res.relpath.parts[0])

        return sorted(result)

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        '''
        Get file attributes. Raise FileNotFoundError if necessary.
        '''
        st, _ = self.getattr_extended(path)
        return st

    def getattr_extended(self, path: PurePosixPath) -> \
        Tuple[fuse.Stat, Optional[Resolved]]:
        '''
        Resolve the path to the right storage and run getattr() on the right
        storage(s). Raises FileNotFoundError if file cannot be found.

        Returns a tuple (st, res):
          st (fuse.Stat): file attributes; possibly overriden to be read-only
          res (Resolved): resolution result (if there is exactly one)
        '''

        m = re.match(r'^(.*).wl.(\d+)$', path.name)
        suffix: Optional[int]
        if m:
            real_path = path.with_name(m.group(1))
            suffix = int(m.group(2))
        else:
            real_path = path
            suffix = None

        resolved = self._resolve(real_path)
        if len(resolved) == 0:
            raise FileNotFoundError(errno.ENOENT, '')

        if len(resolved) == 1:
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            # Single storage. Run storage_getattr directly so that all IOErrors
            # can be propagated to caller.

            res = resolved[0]
            st = self._storage_getattr(res)
            return (st, res)

        file_results: List[Tuple[fuse.Stat, Resolved]] = []
        dir_results: List[Tuple[fuse.Stat, Resolved]] = []
        for res in resolved:
            st = handle_io_error(self._storage_getattr, res)
            if st is None:
                continue
            if stat.S_ISDIR(st.st_mode):
                dir_results.append((st, res))
            else:
                file_results.append((st, res))

        if len(dir_results) == 1:
            # This is a directory in a single storage.
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            return dir_results[0]

        if len(dir_results) > 1:
            # Multiple directories, return a synthetic read-only directory.
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            st = fuse.Stat(
                st_mode=stat.S_IFDIR | 0o555,
                st_nlink=1,
                st_uid=None,
                st_gid=None,
            )
            return (st, None)

        if len(file_results) == 1:
            # This is a single file, not conflicting with anything.
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            return file_results[0]

        if len(file_results) > 1:
            # There are multiple files, so expect an added suffix.
            if suffix is None:
                raise FileNotFoundError(errno.ENOENT, '')
            for st, res in file_results:
                if res.ident == suffix:
                    return (st, res)
            raise FileNotFoundError(errno.ENOENT, '')

        # Nothing found.
        assert len(file_results) == len(dir_results) == 0
        raise FileNotFoundError(errno.ENOENT, '')


def handle_io_error(func, *args):
    '''
    Run a function, suppressing IOErrors and returning None instead.
    '''

    try:
        return func(*args)
    except IOError:
        return None
