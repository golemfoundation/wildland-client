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
from typing import List, Dict, Set, Tuple, Optional, Iterable
import re
import dataclasses
import errno

from .storage_backends.base import Attr


@dataclasses.dataclass
class Resolved:
    '''
    A path resolution result.
    '''
    # Storage ID
    ident: int

    # Relative path inside (if inside), or relative path of the mount path
    # (if not inside)
    relpath: PurePosixPath


class MountDir:
    '''
    A prefix tree for storing information about mounted storages.
    '''

    def __init__(self):
        self.storage_ids: Set[int] = set()
        self.children: Dict[str, 'MountDir'] = {}

    def is_empty(self):
        '''
        Is this node ready for deletion (i.e. no storages left)?
        '''

        return len(self.children) == 0 and len(self.storage_ids) == 0

    def mount(self, path: PurePosixPath, storage_id: int):
        '''
        Add a storage under the given path.
        '''

        if not path.parts:
            self.storage_ids.add(storage_id)
            return

        first = path.parts[0]
        rest = path.relative_to(path.parts[0])
        if first not in self.children:
            self.children[first] = MountDir()
        self.children[first].mount(rest, storage_id)

    def unmount(self, path: PurePosixPath, storage_id: int):
        '''
        Remove a storage from a given path.
        '''

        if not path.parts:
            self.storage_ids.remove(storage_id)
            return

        first = path.parts[0]
        rest = path.relative_to(path.parts[0])
        self.children[first].unmount(rest, storage_id)
        if self.children[first].is_empty():
            del self.children[first]

    def is_synthetic(self, path: PurePosixPath) -> bool:
        '''
        Is this a synthetic directory?

        A synthetic directory is one where either more than one storage is
        mounted, or there are storages mounted on the path deeper.
        '''

        if not path.parts:
            if len(self.children) == 0 and len(self.storage_ids) == 1:
                return False
            return True

        first = path.parts[0]
        if first in self.children:
            rest = path.relative_to(first)
            return self.children[first].is_synthetic(rest)
        return False

    def readdir(self, path: PurePosixPath) -> Optional[Iterable[str]]:
        '''
        List synthetic sub-directories under path.
        '''

        if not path.parts:
            return self.children.keys()

        first = path.parts[0]
        if first in self.children:
            rest = path.relative_to(first)
            return self.children[first].readdir(rest)
        return None

    def resolve(self, path: PurePosixPath) -> Iterable[Resolved]:
        '''
        Find all storages that could be responsible for a given path.
        '''

        for storage_id in self.storage_ids:
            yield Resolved(storage_id, path)

        if path.parts:
            first = path.parts[0]
            if first in self.children:
                rest = path.relative_to(first)
                yield from self.children[first].resolve(rest)


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

    def __init__(self):
        self.root: MountDir = MountDir()

    def mount(self, path: PurePosixPath, storage_id: int):
        '''
        Add information about a mounted storage.
        '''

        self.root.mount(path, storage_id)

    def unmount(self, path: PurePosixPath, storage_id: int):
        '''
        Remove information about a mounted storage.
        '''

        self.root.unmount(path, storage_id)

    @abc.abstractmethod
    def storage_getattr(self, ident: int, relpath: PurePosixPath) \
        -> Attr:
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

    def readdir(self, path: PurePosixPath) -> List[str]:
        '''
        List directory.

        Raise IOError if the path cannot be accessed.
        '''

        resolved = list(self.root.resolve(path))
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
                    result.add(self.SUFFIX_FORMAT.format(name, res.ident))
                elif stat.S_ISDIR(st.mode):
                    result.add(name)
                else:
                    result.add(self.SUFFIX_FORMAT.format(name, res.ident))

        return sorted(result)

    def getattr(self, path: PurePosixPath) -> Attr:
        '''
        Get file attributes. Raise FileNotFoundError if necessary.
        '''
        st, _ = self.getattr_extended(path)
        return st

    def getattr_extended(self, path: PurePosixPath) -> \
        Tuple[Attr, Optional[Resolved]]:
        '''
        Resolve the path to the right storage and run getattr() on the right
        storage(s). Raises FileNotFoundError if file cannot be found.

        Returns a tuple (st, res):
          st (Attr): file attributes; possibly overriden to be read-only
          res (Resolved): resolution result (if there is exactly one)
        '''

        if path == PurePosixPath('/'):
            return Attr(
                mode=stat.S_IFDIR | 0o555,
            ), None

        m = re.match(r'^(.*).wl.(\d+)$', path.name)
        suffix: Optional[int]
        if m:
            real_path = path.with_name(m.group(1))
            suffix = int(m.group(2))
        else:
            real_path = path
            suffix = None

        if self.root.is_synthetic(real_path):
            return Attr(
                mode=stat.S_IFDIR | 0o555,
            ), None

        resolved = list(self.root.resolve(real_path))
        if len(resolved) == 0:
            raise FileNotFoundError(errno.ENOENT, '')

        if len(resolved) == 1:
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            # Single storage. Run storage_getattr directly so that all IOErrors
            # can be propagated to caller.

            res = resolved[0]
            st = self.storage_getattr(res.ident, res.relpath)
            return (st, res)

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

        if len(dir_results) == 1:
            # This is a directory in a single storage.
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            return dir_results[0]

        if len(dir_results) > 1:
            # Multiple directories, return a synthetic read-only directory.
            if suffix is not None:
                raise FileNotFoundError(errno.ENOENT, '')

            st = Attr(
                mode=stat.S_IFDIR | 0o555,
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
