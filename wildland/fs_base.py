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
import logging
import os
import stat

import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import List, Dict, Iterable, Optional, Set, Union

from .conflict import ConflictResolver, Resolved
from .storage_backends.base import Attr, File, StorageBackend
from .storage_backends.watch import FileEvent, StorageWatcher
from .exc import WildlandError
from .control_server import ControlServer, ControlHandler, control_command
from .manifest.schema import Schema


logger = logging.getLogger('fs')


@dataclass
class Watch:
    """
    A watch added by a connected user.
    """

    id: int
    storage_id: int
    pattern: str
    handler: ControlHandler

    def __str__(self):
        return f'{self.storage_id}:{self.pattern}'


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
        self.storages: Dict[int, StorageBackend] = {}
        self.storage_extra: Dict[int, Dict] = {}
        self.storage_paths: Dict[int, List[PurePosixPath]] = {}
        self.main_paths: Dict[PurePosixPath, int] = {}
        self.storage_counter = 1

        self.mount_lock = threading.Lock()

        self.watches: Dict[int, Watch] = {}
        self.storage_watches: Dict[int, Set[int]] = {}
        self.watchers: Dict[int, StorageWatcher] = {}
        self.watch_counter = 1

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

    def _mount_storage(self, paths: List[PurePosixPath], storage: StorageBackend,
                       extra: Optional[Dict] = None, remount: bool = False) -> None:
        """
        Mount a storage under a set of paths.
        """

        assert self.mount_lock.locked()

        logger.info('Mounting storage %r under paths: %s',
                    storage, [str(p) for p in paths])

        main_path = paths[0]
        current_ident = self.main_paths.get(main_path)
        if current_ident is not None:
            if remount:
                logger.info('Unmounting current storage: %s, for main path: %s',
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

    def _unmount_storage(self, storage_id: int) -> None:
        """Unmount a storage"""

        assert self.mount_lock.locked()

        if storage_id in self.storage_watches:
            for watch_id in list(self.storage_watches[storage_id]):
                self._remove_watch(watch_id)

        assert storage_id in self.storages
        assert storage_id in self.storage_paths
        storage = self.storages[storage_id]
        paths = self.storage_paths[storage_id]

        logger.info('Unmounting storage %r from paths: %s',
                    storage, [str(p) for p in paths])

        storage.request_unmount()

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
    def control_mount(self, _handler, items):
        collected_errors = list()
        for params in items:
            paths = [PurePosixPath(p) for p in params['paths']]
            assert len(paths) > 0
            storage_params = params['storage']
            read_only = params.get('read-only', False)
            extra_params = params.get('extra')
            remount = params.get('remount')
            storage = StorageBackend.from_params(storage_params, read_only, deduplicate=True)
            try:
                storage.request_mount()
                with self.mount_lock:
                    self._mount_storage(paths, storage, extra_params, remount)
            except Exception as e:
                logger.exception('backend %s not mounted due to exception', storage.backend_id)
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
                for ident, storage in self.storages.items():
                    logger.info('clearing cache for storage: %s', ident)
                    storage.clear_cache()
                return

            if storage_id not in self.storages:
                raise WildlandError(f'storage not found: {storage_id}')
            logger.info('clearing cache for storage: %s', storage_id)
            self.storages[storage_id].clear_cache()

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
                    "type": self.storages[ident].TYPE,
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
            storage = self.storages[storage_id]

            result.append({
                'storage': {
                    'container-path': storage.params['container-path'],
                    'backend-id': storage.backend_id,
                    'owner': storage.params['owner'],
                    'read-only': storage.read_only,
                    'hash': storage.hash,
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
            return self._add_watch(storage_id, pattern, handler, ignore_own=ignore_own)

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

    def _notify_storage_watches(self, event_type, relpath, storage_id):
        with self.mount_lock:
            if storage_id not in self.storage_watches:
                return

            if storage_id in self.watchers:
                return
            watches = [self.watches[watch_id]
                       for watch_id in self.storage_watches[storage_id]]

        if not watches:
            return

        event = FileEvent(event_type, relpath)
        for watch in watches:
            self._notify_watch(watch, [event])

    def _add_watch(self, storage_id: int, pattern: str, handler: ControlHandler,
                   ignore_own: bool = False):
        assert self.mount_lock.locked()

        watch = Watch(
            id=self.watch_counter,
            storage_id=storage_id,
            pattern=pattern,
            handler=handler,
        )
        logger.info('adding watch: %s', watch)
        self.watches[watch.id] = watch
        if storage_id not in self.storage_watches:
            self.storage_watches[storage_id] = set()

        self.storage_watches[storage_id].add(watch.id)
        self.watch_counter += 1

        handler.on_close(lambda: self._cleanup_watch(watch.id))

        # Start a watch thread, but only if the storage provides watcher() method
        if len(self.storage_watches[storage_id]) == 1:

            def watch_handler(events):
                return self._watch_handler(storage_id, events)
            watcher = self.storages[storage_id].start_watcher(
                watch_handler, ignore_own_events=ignore_own)

            if watcher:
                logger.info('starting watcher for storage %d', storage_id)
                self.watchers[storage_id] = watcher

        return watch.id

    def _watch_handler(self, storage_id: int, events: List[FileEvent]):
        logger.debug('events from %d: %s', storage_id, events)
        watches = [self.watches[watch_id]
                   for watch_id in self.storage_watches.get(storage_id, [])]

        for watch in watches:
            self._notify_watch(watch, events)

    def _notify_watch(self, watch: Watch, events: List[FileEvent]):
        events = [event for event in events
                  if event.path.match(watch.pattern)]
        if not events:
            return

        logger.info('notify watch: %s: %s', watch, events)
        data = [{
            'type': event.type,
            'path': str(event.path),
            'watch-id': watch.id,
            'storage-id': watch.storage_id,
        } for event in events]
        watch.handler.send_event(data)

    def _cleanup_watch(self, watch_id):
        with self.mount_lock:
            # Could be removed earlier, when unmounting storage.
            if watch_id in self.watches:
                self._remove_watch(watch_id)

    def _remove_watch(self, watch_id):
        assert self.mount_lock.locked()

        watch = self.watches[watch_id]
        logger.info('removing watch: %s', watch)

        if (len(self.storage_watches[watch.storage_id]) == 1 and
                watch.storage_id in self.watchers):

            logger.info('stopping watcher for storage: %s', watch.storage_id)
            self.storages[watch.storage_id].stop_watcher()
            del self.watchers[watch.storage_id]

        self.storage_watches[watch.storage_id].remove(watch_id)
        del self.watches[watch_id]

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

    def proxy(self, method_name, path: Union[str, PurePosixPath], *args,
              resolved_path: Optional[Resolved] = None,
              parent=False,
              modify=False,
              event_type=None,
              **kwargs):
        """
        Proxy a call to the corresponding Storage.

        Flags:
          parent: if true, resolve the path based on parent. This will
          apply for calls that create a file or otherwise modify the parent
          directory.

          modify: if true, this is an operation that should not be proxied
          to read-only storage.

          event_type: event to notify about (create, update, delete).
        """

        path = PurePosixPath(path)
        resolved = self._resolve_path(path, parent) if not resolved_path else resolved_path
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
            self._notify_storage_watches(event_type, relpath, resolved.ident)
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
            storage = self.storages[res.ident]
        if storage.read_only:
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
        event_type: Optional[str] = None
        if obj.created:
            event_type = 'create'
        elif flags & (os.O_RDWR | os.O_WRONLY):
            event_type = 'modify'
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
        return self.proxy('chmod', path, mode, modify=True, event_type='update')

    def chown(self, path, uid, gid):
        return self.proxy('chown', path, uid, gid, modify=True, event_type='update')

    def getxattr(self, *args):
        return -errno.ENOSYS

    def ioctl(self, *args):
        return -errno.ENOSYS

    def link(self, *args):
        return -errno.ENOSYS

    def listxattr(self, *args):
        return -errno.ENOSYS

    def mkdir(self, path, mode):
        return self.proxy('mkdir', path, mode, parent=True, modify=True, event_type='create')

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
                          event_type='update')

    def rmdir(self, path):
        return self.proxy('rmdir', path, modify=True, event_type='delete')

    def setxattr(self, *args):
        return -errno.ENOSYS

    def statfs(self, *args):
        return -errno.ENOSYS

    def symlink(self, *args):
        return -errno.ENOSYS

    def truncate(self, path, length):
        return self.proxy('truncate', path, length, modify=True, event_type='modify')

    def unlink(self, path):
        return self.proxy('unlink', path, modify=True, event_type='delete')

    def utimens(self, path: str, atime: Timespec, mtime: Timespec):
        return self.proxy('utimens', path, atime, mtime, modify=True,
                          event_type='modify')


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
