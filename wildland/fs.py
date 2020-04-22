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
import logging.config
import os
import pathlib
import stat
import json
from typing import List, Dict

import fuse
fuse.fuse_python_api = 0, 2

from .fuse_utils import debug_handler
from .storage.base import FileProxyMixin, AbstractStorage
from .storage.control import ControlStorage, control_directory, control_file
from .exc import WildlandError


class WildlandFS(fuse.Fuse, FileProxyMixin):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing

        super().__init__(*args, **kwds)

        self.parser.add_option(mountopt='log', metavar='PATH',
            help='path to log file, use - for stderr')

        self.storages: Dict[int, AbstractStorage] = {}
        self.storage_paths: Dict[int, List[pathlib.Path]] = {}
        self.paths: Dict[pathlib.Path, int] = {}

        self.uid = None
        self.gid = None
        self.install_debug_handler()

        # Run FUSE in single-threaded mode.
        # (TODO: verify what is needed for multi-threaded, what guarantees FUSE
        # gives us, etc.)
        # (TODO: make code coverage work in multi-threaded mode)
        self.multithreaded = False

    def install_debug_handler(self):
        '''Decorate all python-fuse entry points'''
        for name in fuse.Fuse._attrs:
            if hasattr(self, name):
                method = getattr(self, name)
                setattr(self, name, debug_handler(method, bound=True))

    def main(self, *args, **kwds): # pylint: disable=arguments-differ
        # this is after cmdline parsing
        self.uid, self.gid = os.getuid(), os.getgid()

        self.init_logging(self.cmdline[0])

        self.mount_storage(
            [pathlib.Path('/.control')],
            ControlStorage(fs=self, uid=self.uid, gid=self.gid))

        super().main(*args, **kwds)

    def init_logging(self, args):
        '''
        Configure logging module.
        '''

        config = {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {
                'default': {
                    'class': 'logging.Formatter',
                    'format': '%(asctime)s %(levelname)s [%(name)s] %(message)s',
                },
            },
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stderr',
                    'formatter': 'default',
                },
            },
            'root': {
                'level': 'DEBUG',
                'handlers': [],
            },
            'loggers': {
                'gnupg': {'level': 'INFO'},
                'boto3': {'level': 'INFO'},
                'botocore': {'level': 'INFO'},
                's3transfer': {'level': 'INFO'},
            }
        }

        log_path = args.log or '/tmp/wlfuse.log'

        if log_path == '-':
            config['root']['handlers'].append('console')
        else:
            config['handlers']['file'] = {
                'class': 'logging.FileHandler',
                'filename': log_path,
                'formatter': 'default',
            }
            config['root']['handlers'].append('file')
        logging.config.dictConfig(config)

    def mount_storage(self, paths: List[pathlib.Path], storage: AbstractStorage):
        '''
        Mount a storage under a set of paths.
        '''

        logging.info('Mounting storage %r under paths: %s',
                    storage, [str(p) for p in paths])

        intersection = set(self.paths).intersection(paths)
        if intersection:
            raise WildlandError('path collision: %r' % intersection)

        ident = 0
        while ident in self.storages:
            ident += 1

        self.storages[ident] = storage
        self.storage_paths[ident] = paths
        for path in paths:
            self.paths[path] = ident

    def unmount_storage(self, ident: int):
        '''Unmount a storage'''

        assert ident in self.storages
        assert ident in self.storage_paths
        storage = self.storages[ident]
        paths = self.storage_paths[ident]
        logging.info('unmounting storage %r from paths: %s',
                     storage, [str(p) for p in paths])

        # TODO check open files?
        for path in paths:
            assert path in self.paths
            del self.paths[path]
        del self.storages[ident]
        del self.storage_paths[ident]

    def resolve_path(self, path: pathlib.Path):
        '''Given path inside Wildland mount, return which storage is
        responsible, and a path relative to the container root.

        The storage with longest prefix is returned.

        :obj:`None`, :obj:`None` is returned if in no particular storage.
        '''

        for cpath in sorted(self.paths, key=lambda x: len(str(x)), reverse=True):
            try:
                relpath = path.relative_to(cpath)
            except ValueError:
                continue
            else:
                storage = self.storages[self.paths[cpath]]
                return storage, relpath
        return None, None


    def is_on_path(self, path):
        '''
        Check if the given path is inside (but not a root) of at least one
        container.
        '''
        for cpath in self.paths:
            try:
                relpath = cpath.relative_to(path)
                if relpath.parts:
                    return True
            except ValueError:
                continue
        return False


    # pylint: disable=missing-docstring


    #
    # .control API
    #

    @control_file('mount', read=False, write=True)
    def control_mount(self, content: bytes):
        params = json.loads(content)
        paths = [pathlib.Path(p) for p in params['paths']]
        storage_fields = params['storage']
        storage = AbstractStorage.from_fields(storage_fields, self.uid, self.gid)
        self.mount_storage(paths, storage)

    @control_file('unmount', read=False, write=True)
    def control_unmount(self, content: bytes):
        ident = int(content)
        if ident not in self.storages:
            raise WildlandError(f'storage not found: {ident}')
        self.unmount_storage(ident)

    @control_file('paths')
    def control_paths(self):
        result = {str(path): ident for path, ident in self.paths.items()}
        return (json.dumps(result, indent=2) + '\n').encode()

    @control_directory('storage')
    def control_containers(self):
        for ident, storage in self.storages.items():
            yield str(ident), storage


    #
    # FUSE API
    #

    def fsinit(self):
        logging.info('mounting wildland')

    def fsdestroy(self):
        logging.info('unmounting wildland')

    def proxy(self, method_name, path, *args, **kwargs):
        '''
        Proxy a call to corresponding Storage.
        '''

        path = pathlib.PurePosixPath(path)
        storage, relpath = self.resolve_path(path)
        if storage is None:
            return -errno.ENOENT

        return getattr(storage, method_name)(relpath, *args, **kwargs)

    def open(self, path, flags):
        return self.proxy('open', path, flags)

    def create(self, path, flags, mode):
        return self.proxy('create', path, flags, mode)

    def getattr(self, path):
        path = pathlib.PurePosixPath(path)

        # XXX there is a problem, when the path exists, but is also on_path
        #   - it can be not a directory
        #   - it can have conflicting permissions (might it be possible to deny
        #     access to other container?)

        storage, relpath = self.resolve_path(path)

        if storage is not None:
            try:
                return storage.getattr(relpath)
            except FileNotFoundError:
                # maybe this is on path to next container, so we have to
                # check is on path; if that would not be the case, we'll
                # raise -ENOENT later anyway
                pass

        if self.is_on_path(path):
            return fuse.Stat(
                st_mode=0o755 | stat.S_IFDIR,
                st_nlink=0, # XXX is this OK?
                st_uid=self.uid,
                st_gid=self.gid,
            )

        return -errno.ENOENT

    # XXX this looks unneeded
#   def opendir(self, path):
#       logging.debug('opendir(%r)', path)
#       path = pathlib.PurePosixPath(path)
#       container, relpath = self.get_container_for_path(path)
#       if container is not None:
#           try:
#               return container.storage.opendir(relpath)
#           except FileNotFoundError:
#               pass
#
#       if self.is_on_path(path):
#           return FIXME
#
#       return -errno.ENOENT

    def readdir(self, path, _offset):
        path = pathlib.PurePosixPath(path)

        # TODO disallow .control in all containers, or disallow mounting /

        ret = {'.', '..'}
        exists = False

        storage, relpath = self.resolve_path(path)

        if storage is not None:
            try:
                ret.update(storage.readdir(relpath))
                exists = True
            except FileNotFoundError:
                pass

        for p in self.paths:
            try:
                suffix = p.relative_to(path)
            except ValueError:
                continue
            else:
                if suffix.parts:
                    ret.add(suffix.parts[0])
                    exists = True

        if path == pathlib.PurePosixPath('/'):
            exists = True
            ret.add('.control')

        if exists:
            return (fuse.Direntry(i) for i in ret)

        raise OSError(errno.ENOENT, '')

    # pylint: disable=unused-argument

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

    def mkdir(self, *args):
        return -errno.ENOSYS

    def mknod(self, *args):
        return -errno.ENOSYS

    def readlink(self, *args):
        return -errno.ENOSYS

    def removexattr(self, *args):
        return -errno.ENOSYS

    def rename(self, *args):
        return -errno.ENOSYS

    def rmdir(self, *args):
        return -errno.ENOSYS

    def setxattr(self, *args):
        return -errno.ENOSYS

    def statfs(self, *args):
        return -errno.ENOSYS

    def symlink(self, *args):
        return -errno.ENOSYS

    def truncate(self, path, length):
        return self.proxy('truncate', path, length)

    def unlink(self, path):
        return self.proxy('unlink', path)

    def utime(self, *args):
        return -errno.ENOSYS

    def utimens(self, *args):
        return -errno.ENOSYS

def main():
    # pylint: disable=missing-docstring
    server = WildlandFS()
    server.parse(errex=1)
    server.main()
