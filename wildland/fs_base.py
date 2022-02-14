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
Wildland Filesystem
"""

import errno
import os
import stat

import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Dict, Iterable, Optional, Union, Any

from .conflict import ConflictResolver, Resolved
from .fs_watchers import FileWatchers, ChildrenWatchers
from .storage_backends.base import Attr, File, StorageBackend
from .storage_backends.watch import FileEventType
from .exc import WildlandError
from .control_server import ControlServer, ControlHandler, control_command
from .manifest.schema import Schema
from .log import get_logger
from .tests.profiling.profilers import profile

logger = get_logger('fs')


@dataclass
class Timespec:
    """
    fuse-free version of Fuse.Timespec
    """
    name: str
    tv_sec: int
    tv_nsec: int


class WildlandFSBase:
    """
    A base class for Wildland implementations.
    """

    # pylint: disable=no-self-use,too-many-public-methods,unused-argument

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)  # type: ignore
        # Mount information
        self.storages = LazyStorageDict()
        self.storage_extra: Dict[int, Dict] = {}
        self.storage_paths: Dict[int, List[PurePosixPath]] = {}
        self.main_paths: Dict[PurePosixPath, int] = {}
        self.storage_counter = 1

        self.mount_lock = threading.Lock()

        self.file_watchers = FileWatchers(self)
        self.children_watchers = ChildrenWatchers(self)

        self.uid = None
        self.gid = None

        self.resolver = WildlandFSConflictResolver(self)
        self.control_server = ControlServer()
        self.control_server.register_commands(self)
        self.default_user = None

        command_schemas = Schema.load_dict('fs-commands.json', 'args')
        self.control_server.register_validators({
            cmd: schema.validate for cmd, schema in command_schemas.items()
        })

    def _mount_storage(
            self,
            paths: List[PurePosixPath],
            storage: StorageBackend,
            extra: Optional[Dict] = None,
            remount: bool = False,
            lazy: bool = True
    ) -> None:
        """
        Mount a storage under a set of paths.
        """

        with self.mount_lock:

            logger.debug('Mounting storage (backend-id=%s) under paths: %s',
                         storage.backend_id, [str(p) for p in paths])

            main_path = paths[0]
            current_ident = self.main_paths.get(main_path)
            if current_ident is not None:
                if remount:
                    logger.debug('Unmounting current storage: %s, for main path: %s',
                                 current_ident, main_path)
                    self._unmount_storage(current_ident)
                else:
                    raise WildlandError(f'Storage already mounted under main path: {main_path}')

            ident = self.storage_counter
            self.storage_counter += 1

            self.storages[ident] = storage
            self.storage_extra[ident] = extra or {}
            self.storage_paths[ident] = paths
            self.main_paths[main_path] = ident
            for path in paths:
                self.resolver.mount(path, ident)

        if not lazy or storage.MOUNT_REFERENCE_CONTAINER:
            # request mount of storage backends
            self.storages.get(ident)

    def _unmount_storage(self, storage_id: int) -> None:
        """Unmount a storage"""

        assert self.mount_lock.locked()

        self.file_watchers.remove_watches(storage_id)
        self.children_watchers.remove_watches(storage_id)

        assert storage_id in self.storages
        assert storage_id in self.storage_paths
        paths = self.storage_paths[storage_id]

        # TODO check open files?
        del self.storages[storage_id]
        del self.storage_paths[storage_id]
        del self.main_paths[paths[0]]
        for path in paths:
            self.resolver.unmount(path, storage_id)

    # pylint: disable=missing-docstring

    #
    # .control API
    #

    @control_command('mount')
    @profile()
    def control_mount(self, _handler, items, lazy: bool = True):
        collected_errors = list()
        for params in items:
            paths = [PurePosixPath(p) for p in params['paths']]
            assert len(paths) > 0
            storage_params = params['storage']
            read_only = storage_params.get('read-only', False)
            extra_params = params.get('extra')
            remount = params.get('remount')
            storage = StorageBackend.from_params(storage_params, read_only, deduplicate=True)
            try:
                self._mount_storage(paths, storage, extra_params, remount, lazy)
            except Exception as e:
                logger.error(
                    'backend %s not mounted due to exception', params['storage']['backend-id'])
                collected_errors.append(e)

        if collected_errors:
            raise WildlandError(collected_errors)

    @control_command('unmount')
    def control_unmount(self, _handler, storage_id: int):
        if storage_id not in self.storages:
            raise WildlandError(f'storage not found: {storage_id}')
        with self.mount_lock:
            self._unmount_storage(storage_id)

    @control_command('clear-cache')
    def control_clear_cache(self, _handler, storage_id=None):
        with self.mount_lock:
            if storage_id is None:
                for ident in self.storages:
                    logger.debug('clearing cache for storage: %s', ident)
                    self.storages.clear_cache(ident)
                return

            if storage_id not in self.storages:
                raise WildlandError(f'storage not found: {storage_id}')
            logger.debug('clearing cache for storage: %s', storage_id)
            self.storages.clear_cache(storage_id)

    @control_command('paths')
    def control_paths(self, _handler):
        """
        Mounted storages by path, for example::

            {"/foo": [0], "/bar/baz": [0, 1]}
        """

        result: Dict[str, List[int]] = {}
        with self.mount_lock:
            for ident, paths in self.storage_paths.items():
                for path in paths:
                    result.setdefault(str(path), []).append(ident)
        return result

    @control_command('info')
    def control_info(self, _handler) -> Dict[str, Dict]:
        """
        Storage info by main path, for example::

            {
                "/foo": {
                    "paths": ["/foo", "/bar/baz"],
                    "type": "local",
                    "trusted_owner": null,
                    "extra": {}
                }
            }
        """

        result: Dict[str, Dict] = {}
        with self.mount_lock:
            for ident in self.storages:
                result[str(ident)] = {
                    "paths": [str(path) for path in self.storage_paths[ident]],
                    "type": self.storages.get_type(ident),
                    "extra": self.storage_extra[ident],
                }
        return result

    @control_command('status')
    def control_status(self, _handler):
        """
        Status of the control client, returns a dict with parameters; currently only
        supports default (default_user).
        """
        result = dict()
        if self.default_user:
            result['default-user'] = self.default_user
        return result

    @control_command('dirinfo')
    def control_dirinfo(self, _handler, path: str):
        result = []

        for storage_id in self.resolver.find_storage_ids(PurePosixPath(path)):
            storage_params = self.storages.get_params(storage_id)

            result.append({
                'storage': {
                    'container-path': storage_params['container-path'],
                    'backend-id': storage_params['backend-id'],
                    'owner': storage_params['owner'],
                    'read-only': self.storages.is_read_only(storage_id),
                    'hash': self.storages.get_hash(storage_id),
                    'id': storage_id
                }
            })

        return result

    @control_command('fileinfo')
    def control_fileinfo(self, _handler, path: str):
        try:
            st, resolved = self.resolver.getattr_extended(PurePosixPath(path))
        except FileNotFoundError:
            return {}

        if not resolved:
            return {}

        if stat.S_ISDIR(st.mode):
            return {}

        storage = self.storages[resolved.ident]

        try:
            file_token = storage.get_file_token(resolved.relpath)
        except Exception:
            file_token = None

        return {
            'storage': {
                'container-path': storage.params['container-path'],
                'backend-id': storage.backend_id,
                'owner': storage.params['owner'],
                'read-only': storage.read_only,
                'hash': storage.hash,
                'id': resolved.ident
            },
            'token': file_token
        }

    @control_command('add-watch')
    def control_add_watch(self, handler: ControlHandler, storage_id: int, pattern: str,
                          ignore_own: bool = False):
        if pattern.startswith('/'):
            raise WildlandError('Pattern should not start with /')
        if storage_id not in self.storages:
            raise WildlandError(f'No storage: {storage_id}')
        with self.mount_lock:
            return self.file_watchers.add_watch(storage_id, pattern, handler, ignore_own=ignore_own)

    @control_command('add-subcontainer-watch')
    def control_add_subcontainer_watch(
            self,
            handler: ControlHandler,
            backend_param: Dict[str, Any]
    ):
        backend = StorageBackend.from_params(backend_param, deduplicate=True)
        for storage_id in self.storages:
            if self.storages.get_hash(storage_id) == backend.hash:
                ident = storage_id
                break
        else:
            raise ValueError(f"Unknown storage {backend.backend_id}")
        with self.mount_lock:
            return self.children_watchers.add_watch(ident, "*", handler)

    @control_command('breakpoint')
    def control_breakpoint(self, _handler):
        # Disabled in main() unless an option is given.
        # (TODO: not necessary with socket server?)
        # pylint: disable=method-hidden
        breakpoint()

    @control_command('test')
    def control_test(self, _handler, **kwargs):
        return {'kwargs': kwargs}

    def _stat(self, attr: Attr) -> os.stat_result:
        return os.stat_result((  # type: ignore
            attr.mode,
            0,  # st_ino
            None,  # st_dev
            1,  # nlink
            self.uid,
            self.gid,
            attr.size,
            attr.timestamp,  # atime
            attr.timestamp,  # mtime
            attr.timestamp  # ctime
        ))

    def _get_storage_relative_path(self, file_name: str, resolved_path: Resolved,
                                   parent: bool) -> PurePosixPath:
        return resolved_path.relpath / file_name if parent else resolved_path.relpath

    def _resolve_path(self, path: PurePosixPath, parent: bool) -> Resolved:
        path = path.parent if parent else path

        _, res = self.resolver.getattr_extended(path)

        if not res:
            raise IOError(errno.EACCES, str(path))

        return res

    def _is_same_storage(self, resolved_src_path: Resolved, resolved_dst_path: Resolved) -> bool:
        return resolved_src_path.ident == resolved_dst_path.ident

    #
    # File System API
    #

    def proxy(self, method_name: str, path: Union[str, PurePosixPath], *args,
              resolved_path: Optional[Resolved] = None,
              parent: bool = False,
              modify: bool = False,
              event_type: Optional[FileEventType] = None,
              **kwargs):
        """
        Proxy a call to the corresponding Storage.

        Flags:
          parent: if true, resolve the path based on parent. This will
          apply for calls that create a file or otherwise modify the parent
          directory.

          modify: if true, this is an operation that should not be proxied
          to read-only storage.

          event_type: event to notify about (FileEventType).
        """

        path = PurePosixPath(path)

        if resolved_path:
            resolved = resolved_path
        else:
            try:
                resolved = self._resolve_path(path, parent)
            except IOError as e:
                assert e.errno == errno.EACCES
                if modify:
                    raise IOError(errno.EROFS, str(path)) from e
                raise

        with self.mount_lock:
            storage = self.storages[resolved.ident]

        if not hasattr(storage, method_name):
            raise IOError(errno.ENOSYS, str(path))

        if modify and storage.read_only:
            raise IOError(errno.EROFS, str(path))

        relpath = self._get_storage_relative_path(path.name, resolved, parent)

        try:
            result = getattr(storage, method_name)(relpath, *args, **kwargs)
        except PermissionError as e:
            err = e.errno or errno.EACCES
            raise PermissionError(err, str(e)) from e
        # If successful, notify watches.

        if event_type is not None:
            self.file_watchers.notify_storage_watches(event_type, relpath, resolved.ident)
            self.children_watchers.notify_storage_watches(event_type, relpath, resolved.ident)
        return result

    def open(self, path: str, flags: int) -> File:
        modify = bool(flags & (os.O_RDWR | os.O_WRONLY))
        obj = self.proxy('open', path, flags, modify=modify)
        obj.created = False
        return obj

    def create(self, path, flags, mode):
        obj = self.proxy('create', path, flags, mode, parent=True, modify=True)
        obj.created = True
        return obj

    def getattr(self, path):
        attr, res = self.resolver.getattr_extended(PurePosixPath(path))
        if not res:
            return self._stat(attr)
        with self.mount_lock:
            if self.storages.is_read_only(res.ident):
                attr.mode &= ~0o222
        return self._stat(attr)

    def readdir(self, path: str, _offset: int) -> Iterable[str]:
        return ['.', '..'] + self.resolver.readdir(PurePosixPath(path))

    # pylint: disable=unused-argument

    def read(self, *args):
        return self.proxy('read', *args)

    def write(self, *args):
        return self.proxy('write', *args, modify=True)

    def fsync(self, *args):
        return self.proxy('fsync', *args)

    def release(self, path: str, flags: int, obj: File) -> None:
        # Notify if the file was created, or open for writing.
        event_type: Optional[FileEventType] = None
        if obj.created:
            event_type = FileEventType.CREATE
        elif flags & (os.O_RDWR | os.O_WRONLY):
            event_type = FileEventType.MODIFY
        return self.proxy('release', path, flags, obj, event_type=event_type)

    def flush(self, *args) -> None:
        return self.proxy('flush', *args)

    def fgetattr(self, path, *args):
        _st, res = self.resolver.getattr_extended(PurePosixPath(path))
        if not res:
            raise IOError(errno.EACCES, str(path))
        with self.mount_lock:
            storage = self.storages[res.ident]
        attr = storage.fgetattr(path, *args)
        if storage.read_only:
            attr.mode &= ~0o222
        return self._stat(attr)

    def ftruncate(self, *args):
        return self.proxy('ftruncate', *args, modify=True)

    def lock(self, *args, **kwargs):
        return self.proxy('lock', *args, **kwargs)

    def access(self, *args):
        return -errno.ENOSYS

    def bmap(self, *args):
        return -errno.ENOSYS

    def chmod(self, path, mode):
        return self.proxy('chmod', path, mode, modify=True, event_type=FileEventType.MODIFY)

    def chown(self, path, uid, gid):
        return self.proxy('chown', path, uid, gid, modify=True, event_type=FileEventType.MODIFY)

    def getxattr(self, *args):
        return -errno.ENOSYS

    def ioctl(self, *args):
        return -errno.ENOSYS

    def link(self, *args):
        return -errno.ENOSYS

    def listxattr(self, *args):
        return -errno.ENOSYS

    def mkdir(self, path, mode):
        return self.proxy('mkdir', path, mode, parent=True, modify=True,
                          event_type=FileEventType.CREATE)

    def mknod(self, *args):
        return -errno.ENOSYS

    def readlink(self, *args):
        return -errno.ENOSYS

    def removexattr(self, *args):
        return -errno.ENOSYS

    def rename(self, move_from: Union[str, PurePosixPath],
               move_to: Union[str, PurePosixPath]):
        move_from = PurePosixPath(move_from)
        move_to = PurePosixPath(move_to)
        resolved_from = self._resolve_path(move_from, parent=False)
        resolved_to = self._resolve_path(move_to, parent=True)

        if not self._is_same_storage(resolved_from, resolved_to):
            return -errno.EXDEV

        dst_relative = self._get_storage_relative_path(
            move_to.name, resolved_to, parent=True)

        return self.proxy('rename', move_from, dst_relative,
                          resolved_path=resolved_from, parent=False, modify=True,
                          event_type=FileEventType.MODIFY)

    def rmdir(self, path):
        return self.proxy('rmdir', path, modify=True, event_type=FileEventType.DELETE)

    def setxattr(self, *args):
        return -errno.ENOSYS

    def statfs(self):
        return os.statvfs(".")

    def symlink(self, *args):
        return -errno.ENOSYS

    def truncate(self, path, length):
        return self.proxy('truncate', path, length, modify=True, event_type=FileEventType.MODIFY)

    def unlink(self, path):
        return self.proxy('unlink', path, modify=True, event_type=FileEventType.DELETE)

    def utimens(self, path: str, atime: Timespec, mtime: Timespec):
        return self.proxy('utimens', path, atime, mtime, modify=True,
                          event_type=FileEventType.MODIFY)


class WildlandFSConflictResolver(ConflictResolver):
    """
    WildlandFS adapter for ConflictResolver.
    """

    def __init__(self, fs: WildlandFSBase):
        super().__init__()
        self.fs = fs

    def storage_getattr(self, ident: int, relpath: PurePosixPath) -> Attr:
        with self.fs.mount_lock:
            storage = self.fs.storages[ident]
        attr = storage.getattr(relpath)
        if storage.read_only:
            return Attr(
                mode=attr.mode & ~0o222,
                size=attr.size,
                timestamp=attr.timestamp)
        return attr

    def storage_readdir(self, ident: int, relpath: PurePosixPath) -> List[str]:
        with self.fs.mount_lock:
            storage = self.fs.storages[ident]
        return list(storage.readdir(relpath))


class LazyStorageDict:
    """
    A dict-like class, which lazy mount storages.

    Unmounts deleted storages.
    """
    # pylint: disable=missing-docstring

    def __init__(self):
        self._storages = dict()
        self._initialized = dict()

    def get(self, key):
        storage = self._storages[key]
        if self._initialized[key]:
            return storage

        try:
            storage.request_mount()
        except Exception as e:
            logger.exception('backend %s not mounted due to exception', storage.backend_id)
            raise WildlandError from e

        self._initialized[key] = True

        return storage

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        self._storages[key] = value
        self._initialized[key] = False

    def __delitem__(self, key):
        storage = self._storages[key]
        if self._initialized[key]:
            logger.debug('Unmounting storage %r', storage)
            storage.request_unmount()
        backend_id = storage.backend_id
        del self._storages[key]
        del self._initialized[key]
        logger.debug('Unmounted storage (backend-id=%s)', backend_id)

    def __iter__(self):
        return iter(self._storages)

    def __contains__(self, key):
        return key in self._storages

    def __len__(self):
        return len(self._storages)

    def get_type(self, key):
        storage = self._storages[key]
        return storage.TYPE

    def get_hash(self, key):
        storage = self._storages[key]
        return storage.hash

    def clear_cache(self, key):
        storage = self._storages[key]
        storage.clear_cache()

    def is_read_only(self, key):
        storage = self._storages[key]
        return storage.read_only

    def get_params(self, key):
        storage = self._storages[key]
        return storage.params
