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
Wildland Filesystem
'''

import errno
import logging
import os
from pathlib import PurePosixPath, Path
from typing import List, Dict, Optional
import threading

import fuse
fuse.fuse_python_api = 0, 2

from .fuse_utils import debug_handler
from .conflict import ConflictResolver
from .storage_backends.base import StorageBackend, Attr
from .exc import WildlandError
from .log import init_logging
from .control_server import ControlServer, control_command


logger = logging.getLogger('fuse')


class WildlandFS(fuse.Fuse):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing

        super().__init__(*args, **kwds)

        self.parser.add_option(mountopt='log', metavar='PATH',
            help='path to log file, use - for stderr')

        self.parser.add_option(mountopt='socket', metavar='SOCKET',
            help='path to control socket file')

        self.parser.add_option(mountopt='breakpoint', action='store_true',
            help='enable .control/breakpoint')

        self.parser.add_option(mountopt='single_thread', action='store_true',
            help='run single-threaded')

        # Mount information
        self.storages: Dict[int, StorageBackend] = {}
        self.storage_extra: Dict[int, Dict] = {}
        self.storage_paths: Dict[int, List[PurePosixPath]] = {}
        self.main_paths: Dict[PurePosixPath, int] = {}
        self.storage_counter = 1
        self.mount_lock = threading.Lock()

        self.uid = None
        self.gid = None
        self.install_debug_handler()

        # Disable file caching, so that we don't have to report the right file
        # size in getattr(), for example for auto-generated files.
        # See 'man 8 mount.fuse' for details.
        self.fuse_args.add('direct_io')

        self.resolver = WildlandFSConflictResolver(self)
        self.control_server = ControlServer()
        self.control_server.register_commands(self)

    def install_debug_handler(self):
        '''Decorate all python-fuse entry points'''
        for name in fuse.Fuse._attrs:
            if hasattr(self, name):
                method = getattr(self, name)
                setattr(self, name, debug_handler(method, bound=True))

    def main(self, args=None):
        # this is after cmdline parsing
        self.uid, self.gid = os.getuid(), os.getgid()

        self.init_logging(self.cmdline[0])

        self.multithreaded = not self.cmdline[0].single_thread

        if not self.cmdline[0].breakpoint:
            self.control_breakpoint = None

        super().main(args)

    def init_logging(self, args):
        '''
        Configure logging module.
        '''

        log_path = args.log or '/tmp/wlfuse.log'
        if log_path == '-':
            init_logging(console=True)
        else:
            init_logging(console=False, file_path=log_path)

    def _mount_storage(self, paths: List[PurePosixPath], storage: StorageBackend,
                       extra: Optional[Dict] = None, remount=False):
        '''
        Mount a storage under a set of paths.
        '''

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

        storage.mount()

        self.storages[ident] = storage
        self.storage_extra[ident] = extra or {}
        self.storage_paths[ident] = paths
        self.main_paths[main_path] = ident
        for path in paths:
            self.resolver.mount(path, ident)

    def _unmount_storage(self, ident: int):
        '''Unmount a storage'''

        assert self.mount_lock.locked()

        assert ident in self.storages
        assert ident in self.storage_paths
        storage = self.storages[ident]
        paths = self.storage_paths[ident]
        logger.info('Unmounting storage %r from paths: %s',
                     storage, [str(p) for p in paths])

        storage.unmount()

        # TODO check open files?
        del self.storages[ident]
        del self.storage_paths[ident]
        del self.main_paths[paths[0]]
        for path in paths:
            self.resolver.unmount(path, ident)

    # pylint: disable=missing-docstring


    #
    # .control API
    #

    @control_command('mount')
    def control_mount(self, items):
        for params in items:
            paths = [PurePosixPath(p) for p in params['paths']]
            storage_params = params['storage']
            read_only = params.get('read-only')
            extra = params.get('extra')
            remount = params.get('remount')
            storage = StorageBackend.from_params(storage_params, read_only)
            with self.mount_lock:
                self._mount_storage(paths, storage, extra, remount)

    @control_command('unmount')
    def control_unmount(self, storage_id: int):
        if storage_id not in self.storages:
            raise WildlandError(f'storage not found: {storage_id}')
        with self.mount_lock:
            self._unmount_storage(storage_id)

    @control_command('clear-cache')
    def control_clear_cache(self, storage_id=None):
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
    def control_paths(self):
        '''
        Mounted storages by path, for example::

            {"/foo": [0], "/bar/baz": [0, 1]}
        '''

        result: Dict[str, List[int]] = {}
        with self.mount_lock:
            for ident, paths in self.storage_paths.items():
                for path in paths:
                    result.setdefault(str(path), []).append(ident)
        return result

    @control_command('info')
    def control_info(self):
        '''
        Storage info by main path, for example::

            {
                "/foo": {
                    "paths": ["/foo", "/bar/baz"],
                    "type": "local",
                    "trusted_signer": null,
                    "extra": {}
                }
            }
        '''

        result: Dict[str, Dict] = {}
        with self.mount_lock:
            for ident in self.storages:
                result[str(ident)] = {
                    "paths": [str(path) for path in self.storage_paths[ident]],
                    "type": self.storages[ident].TYPE,
                    "extra": self.storage_extra[ident],
                }
        return result

    @control_command('breakpoint')
    def control_breakpoint(self):
        # Disabled in main() unless an option is given.
        # (TODO: not necessary with socket server?)
        # pylint: disable=method-hidden
        breakpoint()

    @control_command('test')
    def control_test(self, **kwargs):
        return {'kwargs': kwargs}

    def _stat(self, attr: Attr) -> fuse.Stat:
        return fuse.Stat(
            st_mode=attr.mode,
            st_nlink=1,
            st_uid=self.uid,
            st_gid=self.gid,
            st_size=attr.size,
            st_atime=attr.timestamp,
            st_mtime=attr.timestamp,
            st_ctime=attr.timestamp,
        )

    #
    # FUSE API
    #

    def fsinit(self):
        logger.info('mounting wildland')
        socket_path = Path(self.cmdline[0].socket or '/tmp/wlfuse.sock')
        self.control_server.start(socket_path)

    def fsdestroy(self):
        logger.info('unmounting wildland')
        self.control_server.stop()

    def proxy(self, method_name, path, *args,
              parent=False,
              modify=False,
              **kwargs):
        '''
        Proxy a call to corresponding Storage.

        If parent is true, resolve the path based on parent. This will apply
        for calls that create a file or otherwise modify the parent directory.

        If modify is true, this is an operation that should not be proxied to
        read-only storage.
        '''

        path = PurePosixPath(path)
        to_resolve = path.parent if parent else path

        _st, res = self.resolver.getattr_extended(to_resolve)
        if not res:
            raise IOError(errno.EACCES, str(path))

        with self.mount_lock:
            storage = self.storages[res.ident]

        if not hasattr(storage, method_name):
            raise IOError(errno.ENOSYS, str(path))

        if modify and storage.read_only:
            raise IOError(errno.EROFS, str(path))

        relpath = res.relpath / path.name if parent else res.relpath
        return getattr(storage, method_name)(relpath, *args, **kwargs)

    def open(self, path, flags):
        modify = bool(flags & (os.O_RDWR | os.O_WRONLY))
        return self.proxy('open', path, flags, modify=modify)

    def create(self, path, flags, mode):
        return self.proxy('create', path, flags, mode, parent=True, modify=True)

    def getattr(self, path):
        attr, res = self.resolver.getattr_extended(PurePosixPath(path))
        st = self._stat(attr)
        if not res:
            return st
        with self.mount_lock:
            storage = self.storages[res.ident]
        if storage.read_only:
            st.st_mode &= ~0o222
        return st

    def readdir(self, path, _offset):
        names = ['.', '..'] + self.resolver.readdir(PurePosixPath(path))
        return [fuse.Direntry(name) for name in names]

    # pylint: disable=unused-argument

    def read(self, *args):
        return self.proxy('read', *args)

    def write(self, *args):
        return self.proxy('write', *args, modify=True)

    def fsync(self, *args):
        return self.proxy('fsync', *args)

    def release(self, *args):
        return self.proxy('release', *args)

    def flush(self, *args):
        return self.proxy('flush', *args)

    def fgetattr(self, path, *args):
        _st, res = self.resolver.getattr_extended(PurePosixPath(path))
        if not res:
            raise IOError(errno.EACCES, str(path))
        with self.mount_lock:
            storage = self.storages[res.ident]
        attr = storage.fgetattr(path, *args)
        st = self._stat(attr)
        if storage.read_only:
            st.st_mode &= ~0o222
        return st

    def ftruncate(self, *args):
        return self.proxy('ftruncate', *args, modify=True)

    def lock(self, *args, **kwargs):
        return self.proxy('lock', *args, **kwargs)

    def access(self, *args):
        return -errno.ENOSYS

    def bmap(self, *args):
        return -errno.ENOSYS

    def chmod(self, *args):
        return -errno.ENOSYS

    def chown(self, *args):
        return -errno.ENOSYS

    def getxattr(self, *args):
        return -errno.ENOSYS

    def ioctl(self, *args):
        return -errno.ENOSYS

    def link(self, *args):
        return -errno.ENOSYS

    def listxattr(self, *args):
        return -errno.ENOSYS

    def mkdir(self, path, mode):
        return self.proxy('mkdir', path, mode, parent=True, modify=True)

    def mknod(self, *args):
        return -errno.ENOSYS

    def readlink(self, *args):
        return -errno.ENOSYS

    def removexattr(self, *args):
        return -errno.ENOSYS

    def rename(self, *args):
        return -errno.ENOSYS

    def rmdir(self, path):
        return self.proxy('rmdir', path, parent=True, modify=True)

    def setxattr(self, *args):
        return -errno.ENOSYS

    def statfs(self, *args):
        return -errno.ENOSYS

    def symlink(self, *args):
        return -errno.ENOSYS

    def truncate(self, path, length):
        return self.proxy('truncate', path, length, modify=True)

    def unlink(self, path):
        return self.proxy('unlink', path, parent=True, modify=True)

    def utime(self, *args):
        return -errno.ENOSYS

    def utimens(self, *args):
        return -errno.ENOSYS


class WildlandFSConflictResolver(ConflictResolver):
    '''
    WildlandFS adapter for ConflictResolver.
    '''

    def __init__(self, fs: WildlandFS):
        super().__init__()
        self.fs = fs

    def storage_getattr(self, ident: int, relpath: PurePosixPath) -> Attr:
        with self.fs.mount_lock:
            storage = self.fs.storages[ident]
        return storage.getattr(relpath)

    def storage_readdir(self, ident: int, relpath: PurePosixPath) -> List[str]:
        with self.fs.mount_lock:
            storage = self.fs.storages[ident]
        return list(storage.readdir(relpath))



def main():
    # pylint: disable=missing-docstring
    server = WildlandFS()
    server.parse(errex=1)
    server.main()


if __name__ == '__main__':
    main()
