#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import errno
import logging
import os
import pathlib
import stat
import sys

import fuse
fuse.fuse_python_api = 0, 2

from . import (
    container as _container,
    storage as _storage,
)
from .fuse_utils import debug_handler
from .storage_control import ControlStorage, control


class WildlandFS(fuse.Fuse, _storage.FileProxyMixin):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing

        super().__init__(*args, **kwds)

        self.parser.add_option(mountopt='manifest', metavar='PATH',
            action='append',
            help='paths to the container manifests')

        self.paths = {}
        self.containers = []
        self.uid = None
        self.gid = None
        self.install_debug_handler()

    def install_debug_handler(self):
        '''Decorate all python-fuse entry points'''
        for name in fuse.Fuse._attrs:
            if hasattr(self, name):
                method = getattr(self, name)
                setattr(self, name, debug_handler(method, bound=True))

    def main(self, *args, **kwds): # pylint: disable=arguments-differ
        # this is after cmdline parsing

        self.containers.append(
            _container.Container(self, ['/.control'], ControlStorage(fs=self)))

        for path in self.cmdline[0].manifest:
            path = pathlib.Path(path)
            logging.info('loading manifest %s', path)

            try:
                with open(path) as file:
                    self.containers.append(
                        _container.Container.fromyaml(self, file))
            except: # pylint: disable=bare-except
                logging.exception('error loading manifest %s', path)
                sys.exit(1)

        for container in self.containers:
            cpaths = [pathlib.PurePosixPath(p) for p in container.paths]
            intersection = set(self.paths).intersection(cpaths)
            if intersection:
                logging.error('path collision: %r', intersection)
                sys.exit(1)

            for path in cpaths:
                self.paths[path] = container

        super().main(*args, **kwds)


    def get_container_for_path(self, path):
        '''Given path inside Wildland mount, return which container is
        responsible, and a path relative to the container root.

        The container with longest prefix is returned.

        :obj:`None`, :obj:`None` is returned if in no particular container.
        '''

        for cpath in sorted(self.paths, key=lambda x: len(str(x)), reverse=True):
            try:
                relpath = path.relative_to(cpath)
            except ValueError:
                continue
            else:
                container = self.paths[cpath]
                logging.debug(' path=%r container=%r relpath=%r', path, container, relpath)
                return container, relpath
        return None, None


    def is_on_path(self, path):
        ''':obj:`True` if the given path contains at least one container
        (possibly indirectly).
        '''
        for cpath in self.paths:
            try:
                cpath.relative_to(path)
                logging.debug(' path=%r container=None', path)
                return True
            except ValueError:
                continue


    @control('cmd', write=True)
    def control_cmd(self, data):
        logging.debug('command: %r', data)

    @control('paths', read=True)
    def control_paths(self):
        result = ''

        for i, container in enumerate(self.containers):
            for path in container.paths:
                # TODO container identifiers
                result += f'{path} {i}\n'

        return result.encode()

    @control('containers', directory=True)
    def control_containers(self):
        for i, container in enumerate(self.containers):
            # TODO container identifier
            yield str(i), container


    #
    # FUSE API
    #

    # pylint: disable=missing-docstring

    def fsinit(self):
        logging.info('mounting wildland')
        self.uid, self.gid = os.getuid(), os.getgid()

    def fsdestroy(self):
        logging.info('unmounting wildland')

    def open(self, path, flags):
        path = pathlib.PurePosixPath(path)
        container, relpath = self.get_container_for_path(path)

        if container is None:
            return -errno.ENOENT

        return container.storage.open(relpath, flags)

    def create(self, path, flags, mode):
        path = pathlib.PurePosixPath(path)
        container, relpath = self.get_container_for_path(path)

        if container is None:
            return -errno.ENOENT

        return container.storage.create(relpath, flags, mode)

    def getattr(self, path):
        path = pathlib.PurePosixPath(path)

        # XXX there is a problem, when the path exists, but is also on_path
        #   - it can be not a directory
        #   - it can have conflicting permissions (might it be possible to deny
        #     access to other container?)

        container, relpath = self.get_container_for_path(path)

        if container is not None:
            try:
                return container.storage.getattr(relpath)
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

    def readdir(self, path, offset):
        path = pathlib.PurePosixPath(path)

        # TODO missing . and ..
        # TODO disallow .control in all containers, or disallow mounting /

        ret = set()
        exists = False

        container, relpath = self.get_container_for_path(path)

        if container is not None:
            try:
                ret.update(container.storage.readdir(relpath))
                exists = True
            except FileNotFoundError:
                pass

        for p in self.paths:
            logging.debug('p=%r', p)
            try:
                suffix = p.relative_to(path)
            except ValueError:
                continue
            else:
                logging.debug('suffix.parts=%r', suffix.parts)
                if suffix.parts:
                    ret.add(suffix.parts[0])
                exists = True

        if path == pathlib.PurePosixPath('/'):
            exists = True
            ret.add('.control')

        if exists:
            logging.debug(' → %r', ret)
            return (fuse.Direntry(i) for i in ret)

        assert not ret
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
        path = pathlib.PurePosixPath(path)
        container, relpath = self.get_container_for_path(path)

        if container is None:
            return -errno.ENOENT

        return container.storage.truncate(relpath, length)

    def unlink(self, path):
        path = pathlib.PurePosixPath(path)
        container, relpath = self.get_container_for_path(path)

        if container is None:
            return -errno.ENOENT

        return container.storage.unlink(relpath)

    def utime(self, *args):
        return -errno.ENOSYS

    def utimens(self, *args):
        return -errno.ENOSYS

def main():
    # pylint: disable=missing-docstring
    log_path = os.environ.get('WLFUSE_LOG', '/tmp/wlfuse.log')
    if os.environ.get('WLFUSE_LOG_STDERR'):
        logging.basicConfig(format='%(asctime)s %(message)s',
                            stream=sys.stderr, level=logging.NOTSET)
    else:
        logging.basicConfig(format='%(asctime)s %(message)s',
                            filename=log_path, level=logging.NOTSET)

    server = WildlandFS()
    server.parse(errex=1)
    server.main()
