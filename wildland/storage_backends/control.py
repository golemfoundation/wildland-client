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
Synthetic storage, which services :path:`/.control` directory
'''

import errno
import logging
import os
from pathlib import PurePosixPath
import stat
import posix

import fuse

from .base import StorageBackend, FileProxyMixin
from ..exc import WildlandError

CONTROL_FILE_MAX_SIZE = 40960

class ControlFile:
    '''Control file handler'''
    def __init__(self, node, *, uid, gid, need_read, need_write):
        # pylint: disable=unused-argument
        self.node = node
        self.uid = uid
        self.gid = gid

        self.buffer = self.node() if need_read else None
        if self.buffer is not None:
            assert len(self.buffer) <= CONTROL_FILE_MAX_SIZE

    # pylint: disable=missing-docstring

    def release(self, flags):
        pass

    def fgetattr(self):
#       st_size = len(self.buffer) if self.buffer is not None else 0

        return fuse.Stat(
            st_mode=0o644 | stat.S_IFREG,
            st_nlink=1,
            st_uid=self.uid,
            st_gid=self.gid,
            st_size=CONTROL_FILE_MAX_SIZE,
        )

    def read(self, length, offset):
        if self.buffer is None:
            raise OSError(errno.EINVAL, '')
        return self.buffer[offset:offset+length]

    def write(self, buf, offset):
        assert offset == 0
        try:
            self.node(buf)
        except WildlandError:
            # libfuse will return EINVAL anyway, but make it explicit here.
            logging.exception('control write error')
            raise OSError(errno.EINVAL, '')
        return len(buf)

    def ftruncate(self, length):
        pass


class ControlStorageBackend(FileProxyMixin, StorageBackend):
    '''Control pseudo-storage'''
    file_class = ControlFile

    def __init__(self, fs, uid, gid):
        super().__init__()
        self.fs = fs
        self.uid = uid
        self.gid = gid

    @classmethod
    def cli_options(cls):
        raise NotImplementedError()

    @classmethod
    def cli_create(cls, data):
        raise NotImplementedError()

    def get_node_for_path(self, path, *, need_directory=False, need_file=False,
            need_read=False, need_write=False):
        '''Return a python object, which represents particular inode

        This can be three different things:

        - a callable with `_control_directory` attribute set to :obj:`False`;
          this means the inode in question looks like regular file; depeding on
          `_control_read` and `_control_write`, the file can be read from and/or
          written to by calling the function
        - a callable with `_control_directory` attribute set to :obj:`True`; the
          inode is a directory, and to list it, one should call that callable,
          which will return an iterable which yields 2-tuples: child name and an
          object representing the child
        - an object without `_control_directory` attribute; the inode is
          a directory and the nodes inside it are those attributes that in turn
          have their attribute `_control_directory` (either :obj:`True` or
          :obj:`False)
        '''
        logging.debug('get_node_for_path(path=%r)', path)
        path = PurePosixPath(path)
        node = self._query_object_for_node(self.fs, *path.parts)

        if need_directory and not self.node_isdir(node):
            raise OSError(errno.ENOTDIR, '')
        if (need_file or need_read or need_write) and self.node_isdir(node):
            raise OSError(errno.EISDIR, '')
        if ((need_read and not node._control_read)
        or (need_write and not node._control_write)):
            raise OSError(errno.EACCES, '')

        return node

    def _query_object_for_node(self, obj, part0=None, *parts):
        # pylint: disable=keyword-arg-before-vararg
        if part0 is None:
            return obj

        for name, attr in self.node_list(obj):
            if name == part0:
                return self._query_object_for_node(attr, *parts)

        raise OSError(errno.ENOENT, '')

    @staticmethod
    def node_isdir(node):
        ''':obj:`True` if the node is a directory

        The result is undefined on invalid nodes
        '''
        return getattr(node, '_control_directory', True)

    @staticmethod
    def node_list(obj):
        '''List a node which is a directory

        The result is undefined if the node is not an actual control node
        '''
        try:
            obj._control_directory

        except AttributeError:
            for attr in dir(obj):
                try:
                    attr = getattr(obj, attr)
                    name = getattr(attr, '_control_name')
                except AttributeError:
                    continue
                yield name, attr
            return

        if not obj._control_directory:
            raise OSError(errno.ENOTDIR, '')

        yield from obj()

    # pylint: disable=missing-docstring

    def open(self, path, flags):
        read = bool((flags & posix.O_ACCMODE) in (os.O_RDONLY, os.O_RDWR))
        write = bool((flags & posix.O_ACCMODE) in (os.O_WRONLY, os.O_RDWR))

        node = self.get_node_for_path(
            path, need_file=True,
            need_read=read, need_write=write)
        return ControlFile(node, uid=self.uid, gid=self.gid,
                           need_read=read,
                           need_write=write)

    def create(self, path, flags, mode):
        raise OSError(errno.ENOSYS, '')

    def getattr(self, path):
        node = self.get_node_for_path(path)

        if self.node_isdir(node):
            return fuse.Stat(
                st_mode=stat.S_IFDIR | 0o755,
                st_nlink=2, # XXX +number of subdirectories
                st_uid=self.uid,
                st_gid=self.gid,
            )

        st_mode = stat.S_IFREG
        if node._control_read:
            st_mode += 0o444
        if node._control_write:
            st_mode += 0o200

        return fuse.Stat(
            st_mode=st_mode,
            st_nlink=1,
            st_uid=self.uid,
            st_gid=self.gid,
            st_size=CONTROL_FILE_MAX_SIZE,
        )

    def readdir(self, path):
        node = self.get_node_for_path(path, need_directory=True)
        for name, _obj in self.node_list(node):
            yield name

    def truncate(self, path, length):
        pass

    def unlink(self, path):
        raise OSError(errno.EPERM, '')

    def mkdir(self, path, mode):
        raise OSError(errno.EPERM, '')

    def rmdir(self, path):
        raise OSError(errno.EPERM, '')
