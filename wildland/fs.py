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
from pathlib import PurePosixPath
import json
from typing import List, Dict

import fuse
fuse.fuse_python_api = 0, 2

from .fuse_utils import debug_handler
from .conflict import ConflictResolver
from .storage_backends.base import StorageBackend
from .storage_backends.control import ControlStorageBackend
from .storage_backends.control_decorators import control_directory, control_file
from .exc import WildlandError
from .log import init_logging


class WildlandFS(fuse.Fuse):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing

        super().__init__(*args, **kwds)

        self.parser.add_option(mountopt='log', metavar='PATH',
            help='path to log file, use - for stderr')

        self.storages: Dict[int, StorageBackend] = {}
        self.storage_paths: Dict[int, List[PurePosixPath]] = {}
        self.storage_counter = 0

        self.uid = None
        self.gid = None
        self.install_debug_handler()

        # Run FUSE in single-threaded mode.
        # (TODO: verify what is needed for multi-threaded, what guarantees FUSE
        # gives us, etc.)
        # (TODO: make code coverage work in multi-threaded mode)
        self.multithreaded = False

        # Disable file caching, so that we don't have to report the right file
        # size in getattr(), for example for auto-generated files.
        # See 'man 8 mount.fuse' for details.
        self.fuse_args.add('direct_io')

        self.resolver = WildlandFSConflictResolver(self)

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

        self.mount_storage(
            [PurePosixPath('/.control')],
            ControlStorageBackend(fs=self))

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

    def mount_storage(self, paths: List[PurePosixPath], storage: StorageBackend):
        '''
        Mount a storage under a set of paths.
        '''

        logging.info('Mounting storage %r under paths: %s',
                    storage, [str(p) for p in paths])

        ident = self.storage_counter
        self.storage_counter += 1

        storage.mount()

        self.storages[ident] = storage
        self.storage_paths[ident] = paths
        for path in paths:
            self.resolver.mount(path, ident)

    def unmount_storage(self, ident: int):
        '''Unmount a storage'''

        assert ident in self.storages
        assert ident in self.storage_paths
        storage = self.storages[ident]
        paths = self.storage_paths[ident]
        logging.info('unmounting storage %r from paths: %s',
                     storage, [str(p) for p in paths])

        # TODO check open files?
        del self.storages[ident]
        del self.storage_paths[ident]
        for path in paths:
            self.resolver.unmount(path, ident)

    # pylint: disable=missing-docstring


    #
    # .control API
    #

    @control_file('mount', read=False, write=True)
    def control_mount(self, content: bytes):
        params = json.loads(content)
        paths = [PurePosixPath(p) for p in params['paths']]
        storage_params = params['storage']
        read_only = params.get('read_only')
        storage = StorageBackend.from_params(storage_params, read_only)
        self.mount_storage(paths, storage)

    @control_file('unmount', read=False, write=True)
    def control_unmount(self, content: bytes):
        ident = int(content)
        if ident not in self.storages:
            raise WildlandError(f'storage not found: {ident}')
        self.unmount_storage(ident)

    @control_file('refresh', read=False, write=True)
    def control_refresh(self, content: bytes):
        ident = int(content)
        if ident not in self.storages:
            raise WildlandError(f'storage not found: {ident}')
        logging.info('refreshing storage: %s', ident)
        self.storages[ident].refresh()

    @control_file('paths')
    def control_paths(self):
        result: Dict[str, List[int]] = {}
        for ident, paths in self.storage_paths.items():
            for path in paths:
                result.setdefault(str(path), []).append(ident)
        return (json.dumps(result, indent=2) + '\n').encode()

    @control_directory('storage')
    def control_containers(self):
        for ident, storage in self.storages.items():
            yield str(ident), storage

    def add_uid_gid(self, attr: fuse.Stat) -> fuse.Stat:
        if attr.st_uid is None:
            attr.st_uid = self.uid
        if attr.st_gid is None:
            attr.st_gid = self.gid
        return attr

    #
    # FUSE API
    #

    def fsinit(self):
        logging.info('mounting wildland')

    def fsdestroy(self):
        logging.info('unmounting wildland')

    def proxy(self, method_name, path, *args,
              parent=False,
              **kwargs):
        '''
        Proxy a call to corresponding Storage.

        If parent is true, resolve the path based on parent. This will apply
        for calls that create a file or otherwise modify the parent directory.
        '''

        path = PurePosixPath(path)
        to_resolve = path.parent if parent else path

        _st, res = self.resolver.getattr_extended(to_resolve)
        if not res:
            return -errno.EACCES

        storage = self.storages[res.ident]
        if not hasattr(storage, method_name):
            return -errno.ENOSYS

        relpath = res.relpath / path.name if parent else res.relpath
        return getattr(storage, method_name)(relpath, *args, **kwargs)

    def open(self, path, flags):
        return self.proxy('open', path, flags)

    def create(self, path, flags, mode):
        return self.proxy('create', path, flags, mode, parent=True)

    def getattr(self, path):
        return self.add_uid_gid(self.resolver.getattr(PurePosixPath(path)))

    def readdir(self, path, _offset):
        names = ['.', '..'] + self.resolver.readdir(PurePosixPath(path))
        return [fuse.Direntry(name) for name in names]

    # pylint: disable=unused-argument

    def read(self, *args):
        return self.proxy('read', *args)

    def write(self, *args):
        return self.proxy('write', *args)

    def fsync(self, *args):
        return self.proxy('fsync', *args)

    def release(self, *args):
        return self.proxy('release', *args)

    def flush(self, *args):
        return self.proxy('flush', *args)

    def fgetattr(self, path, *args):
        return self.add_uid_gid(self.proxy('fgetattr', path, *args))

    def ftruncate(self, *args):
        return self.proxy('ftruncate', *args)

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
        return self.proxy('mkdir', path, mode, parent=True)

    def mknod(self, *args):
        return -errno.ENOSYS

    def readlink(self, *args):
        return -errno.ENOSYS

    def removexattr(self, *args):
        return -errno.ENOSYS

    def rename(self, *args):
        return -errno.ENOSYS

    def rmdir(self, path):
        return self.proxy('rmdir', path, parent=True)

    def setxattr(self, *args):
        return -errno.ENOSYS

    def statfs(self, *args):
        return -errno.ENOSYS

    def symlink(self, *args):
        return -errno.ENOSYS

    def truncate(self, path, length):
        return self.proxy('truncate', path, length)

    def unlink(self, path):
        return self.proxy('unlink', path, parent=True)

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

    def storage_getattr(self, ident: int, relpath: PurePosixPath) -> fuse.Stat:
        return self.fs.storages[ident].getattr(relpath)

    def storage_readdir(self, ident: int, relpath: PurePosixPath) -> fuse.Stat:
        return self.fs.storages[ident].readdir(relpath)



def main():
    # pylint: disable=missing-docstring
    server = WildlandFS()
    server.parse(errex=1)
    server.main()


if __name__ == '__main__':
    main()
