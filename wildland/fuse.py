#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import errno
import functools
import itertools
import logging
import os
import pathlib
import stat
import sys

import fuse
fuse.fuse_python_api = 0, 2

from .container import Container

# XXX do not use
DEBUG_COLLECTIONS = False

def _is_iterable(value):
    try:
        iter(value)
    except TypeError:
        return False
    return True

def handler(func):
    '''A decorator for wrapping FUSE API.

    Helpful for debugging.
    '''
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        try:
            logging.debug('%s(%s)', func.__name__, ', '.join(itertools.chain(
                (repr(i) for i in args[1:]),
                (f'{k}={v!r}' for k, v in kwds.items()))))
            ret = func(*args, **kwds)
            if isinstance(ret, int):
                try:
                    ret_repr = '-' + errno.errorcode.get(-ret)
                except KeyError:
                    ret_repr = str(ret)
            elif DEBUG_COLLECTIONS and _is_iterable(ret) and not isinstance(ret,
                    (os.stat_result, os.statvfs_result)):
                ret_repr = ret = list(ret)
            else:
                ret_repr = repr(ret)
            logging.debug('%s → %s', func.__name__, ret_repr)
            return ret
        except OSError:
            raise
        except:
            logging.exception('error while handling %s', func.__name__)
            raise
    return wrapper

class WildlandFS(fuse.Fuse):
    '''A FUSE implementation of Wildland'''
    # pylint: disable=no-self-use,too-many-public-methods
#   file_class = WildlandFile

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing

        super().__init__(*args, **kwds)

        self.parser.add_option(mountopt='manifest', metavar='PATH',
            action='append',
            help='paths to the container manifests')

        self.paths = {}
        self.containers = []
        self._uid = None
        self._gid = None

        self.fds = set()

    def main(self, *args, **kwds): # pylint: disable=arguments-differ
        # this is after cmdline parsing

        for path in self.cmdline[0].manifest:
            path = pathlib.Path(path)
            logging.info('loading manifest %s', path)

            try:
                with open(path) as file:
                    self.containers.append(Container.fromyaml(file))
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
                manifest = self.paths[cpath]
                logging.debug(' path=%r manifest=%r relpath=%r', path, manifest, relpath)
                return manifest, relpath
        return None, None


    def is_on_path(self, path):
        ''':obj:`True` if the given path contains at least one container
        (possibly indirectly).
        '''
        for cpath in self.paths:
            try:
                cpath.relative_to(path)
                logging.debug(' path=%r manifest=None', path)
                return True
            except ValueError:
                continue


    #
    # FUSE API
    #

    # pylint: disable=missing-docstring

    @handler
    def fsinit(self):
        logging.info('mounting wildland')
        self._uid, self._gid = os.getuid(), os.getgid()

    @handler
    def fsdestroy(self):
        logging.info('unmounting wildland')

    @handler
    def getattr(self, path):
        path = pathlib.PurePosixPath(path)
        manifest, relpath = self.get_container_for_path(path)

        if manifest is not None:
            try:
                return manifest.storage.getattr(relpath)
            except FileNotFoundError:
                # maybe this is on path to next container, so we have to
                # check is on path; if that would not be the case, we'll
                # raise -ENOENT later anyway
                pass

        if self.is_on_path(path):
            return fuse.Stat(
                st_mode=0o755 | stat.S_IFDIR,
                st_nlink=0, # XXX is this OK?
                st_uid=self._uid,
                st_gid=self._gid,
            )

        return -errno.ENOENT

    # XXX this looks unneeded
#   @handler
#   def opendir(self, path):
#       logging.debug('opendir(%r)', path)
#       path = pathlib.PurePosixPath(path)
#       manifest, relpath = self.get_container_for_path(path)
#       if manifest is not None:
#           try:
#               return manifest.storage.opendir(relpath)
#           except FileNotFoundError:
#               pass
#
#       if self.is_on_path(path):
#           return FIXME
#
#       return -errno.ENOENT

    @handler
    def readdir(self, path, offset):
        path = pathlib.PurePosixPath(path)

        ret = set()
        exists = False

        manifest, relpath = self.get_container_for_path(path)

        if manifest is not None:
            try:
                ret.update(manifest.storage.readdir(relpath))
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

        if exists:
            logging.debug(' → %r', ret)
            return (fuse.Direntry(i) for i in ret)

        assert not ret
        raise OSError(errno.ENOENT, '')

    @handler
    def access(self, *args):
        return -errno.ENOSYS

    @handler
    def bmap(self, *args):
        return -errno.ENOSYS

    @handler
    def chmod(self, *args):
        return -errno.ENOSYS

    @handler
    def chown(self, *args):
        return -errno.ENOSYS

    @handler
    def create(self, *args):
        return -errno.ENOSYS

    @handler
    def fgetattr(self, *args):
        return -errno.ENOSYS

    @handler
    def flush(self, *args):
        return -errno.ENOSYS

    @handler
    def fsync(self, *args):
        return -errno.ENOSYS

    @handler
    def fsyncdir(self, *args):
        return -errno.ENOSYS

    @handler
    def ftruncate(self, *args):
        return -errno.ENOSYS

    @handler
    def getxattr(self, *args):
        return -errno.ENOSYS

    @handler
    def ioctl(self, *args):
        return -errno.ENOSYS

    @handler
    def link(self, *args):
        return -errno.ENOSYS

    @handler
    def listxattr(self, *args):
        return -errno.ENOSYS

    @handler
    def lock(self, *args, **kwds):
        return -errno.ENOSYS

    @handler
    def mkdir(self, *args):
        return -errno.ENOSYS

    @handler
    def mknod(self, *args):
        return -errno.ENOSYS

    @handler
    def open(self, *args):
        return -errno.ENOSYS

    @handler
    def read(self, *args):
        return -errno.ENOSYS

    @handler
    def readlink(self, *args):
        return -errno.ENOSYS

    @handler
    def release(self, *args):
        return -errno.ENOSYS

#   @handler
#   def releasedir(self, *args):
#       return -errno.ENOSYS

    @handler
    def removexattr(self, *args):
        return -errno.ENOSYS

    @handler
    def rename(self, *args):
        return -errno.ENOSYS

    @handler
    def rmdir(self, *args):
        return -errno.ENOSYS

    @handler
    def setxattr(self, *args):
        return -errno.ENOSYS

    @handler
    def statfs(self, *args):
        return -errno.ENOSYS

    @handler
    def symlink(self, *args):
        return -errno.ENOSYS

    @handler
    def truncate(self, *args):
        return -errno.ENOSYS

    @handler
    def unlink(self, *args):
        return -errno.ENOSYS

    @handler
    def utime(self, *args):
        return -errno.ENOSYS

    @handler
    def utimens(self, *args):
        return -errno.ENOSYS

    @handler
    def write(self, *args):
        return -errno.ENOSYS

def main():
    # pylint: disable=missing-docstring
    logging.basicConfig(format='%(asctime)s %(message)s',
        filename='/tmp/wlfuse.log', level=logging.NOTSET)
    server = WildlandFS()
    server.parse(errex=1)
    server.main()
