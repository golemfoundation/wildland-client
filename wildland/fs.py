#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import errno
import logging
import os
import pathlib
import stat
import sys
import uuid

import fuse
fuse.fuse_python_api = 0, 2

from .container import Container
from .storage import FileProxyMixin
from .fuse_utils import debug_handler
from .storage_control import ControlStorage, control_directory, control_file
from .exc import WildlandError


class WildlandFS(fuse.Fuse, FileProxyMixin):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing

        super().__init__(*args, **kwds)

        self.parser.add_option(mountopt='manifest', metavar='PATH',
            action='append',
            help='paths to the container manifests')

        self.parser.add_option(mountopt='log', metavar='PATH',
            help='path to log file, use - for stderr')

        # path -> Storage
        self.paths = {}
        # ident -> Container
        self.containers = {}
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
        self.uid, self.gid = os.getuid(), os.getgid()

        log_path = self.cmdline[0].log or '/tmp/wlfuse.log'
        if log_path == '-':
            logging.basicConfig(format='%(asctime)s %(message)s',
                                stream=sys.stderr, level=logging.NOTSET)
        else:
            logging.basicConfig(format='%(asctime)s %(message)s',
                                filename=log_path, level=logging.NOTSET)

        self.paths[pathlib.PurePosixPath('/.control')] = \
            ControlStorage(fs=self, uid=self.uid, gid=self.gid)

        if self.cmdline[0].manifest:
            for path in self.cmdline[0].manifest:
                path = pathlib.Path(path)
                container = self.load_container(path)
                self.mount_container(container)

        super().main(*args, **kwds)

    def load_container(self, path: pathlib.Path) -> Container:
        logging.info('loading manifest %s', path)

        try:
            return Container.from_yaml_file(path)
        except Exception:
            raise WildlandError('error loading manifest %s' % path)

    def load_container_direct(self, content: bytes) -> Container:
        logging.info('loading manifest directly')

        try:
            return Container.from_yaml_content(content)
        except Exception:
            raise WildlandError('error loading manifest')

    def mount_container(self, container: Container):
        if container.ident in self.containers:
            raise WildlandError('container with already mounted: %s' %
                                container.ident)

        cpaths = [pathlib.PurePosixPath(p) for p in container.paths]
        intersection = set(self.paths).intersection(cpaths)
        if intersection:
            raise WildlandError('path collision: %r' % intersection)

        for path in cpaths:
            self.paths[path] = container.storage

        self.containers[container.ident] = container

    def unmount_container(self, ident):
        container = self.containers.get(ident)
        if not container:
            raise WildlandError('container not mounted: %s')
        # TODO don't unmount if for open files?
        cpaths = [pathlib.PurePosixPath(p) for p in container.paths]
        for path in cpaths:
            assert path in self.paths
            del self.paths[path]

        del self.containers[container.ident]

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
                storage = self.paths[cpath]
                return storage, relpath
        return None, None


    def is_on_path(self, path):
        ''':obj:`True` if the given path contains at least one container
        (possibly indirectly).
        '''
        for cpath in self.paths:
            try:
                cpath.relative_to(path)
                return True
            except ValueError:
                continue


    @control_file('cmd', read=False, write=True)
    def control_cmd(self, data: bytes):
        logging.debug('command: %r', data)

        # TODO encoding?
        command, _sep, arg = data.decode().rstrip().partition(' ')

        if command == 'mount':
            path = pathlib.Path(arg)
            container = self.load_container(path)
            self.mount_container(container)
        elif command == 'unmount':
            try:
                ident = uuid.UUID(arg)
            except ValueError:
                raise WildlandError('wrong UUID: %s' % arg)
            self.unmount_container(ident)
        else:
            raise WildlandError('unknown command: %s' % data)

    @control_file('mount', read=False, write=True)
    def control_mount_direct(self, content: bytes):
        logging.debug('mount')
        container = self.load_container_direct(content)
        self.mount_container(container)

    @control_file('paths')
    def control_paths(self):
        result = ''

        for ident, container in self.containers.items():
            for path in container.paths:
                result += f'{path} {ident}\n'

        return result.encode()

    @control_directory('containers')
    def control_containers(self):
        for ident, container in self.containers.items():
            yield str(ident), container


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

        # TODO missing . and ..
        # TODO disallow .control in all containers, or disallow mounting /

        ret = set()
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
        return self.proxy('truncate', path, length)

    def unlink(self, path):
        return self.proxy('unlink', path)

    def utime(self, *args):
        return -errno.ENOSYS

    def utimens(self, *args):
        return -errno.ENOSYS

def main():
    server = WildlandFS()
    server.parse(errex=1)
    server.main()
