#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

# pylint: disable=protected-access

import errno
import logging
import os
import pathlib
import stat

import fuse

from . import storage as _storage
from .fuse_utils import handler

CONTROL_FILE_MAX_SIZE = 4096

def control(name, *, read=False, write=False, directory=False):
    assert '/' not in name
    if directory:
        assert not read and not write

    def decorator(func):
        func._control_name = name
        func._control_read = read
        func._control_write = write
        func._control_directory = directory
        return func

    return decorator

class ControlFile(_storage.AbstractFile):
    def __repr__(self):
        return f'<ControlFile relpath={self.path!r}>'

    @handler
    def __init__(self, fs, container, storage, path, flags, *args):
        super().__init__(fs, container, storage, path, flags, *args)
        self.path = path
        read = bool((flags & os.O_ACCMODE) in (os.O_RDONLY, os.O_RDWR))
        write = bool((flags & os.O_ACCMODE) in (os.O_WRONLY, os.O_RDWR))
        self.node = storage.get_node_for_path(path, need_file=True,
            need_read=read, need_write=write)

        self.buffer = self.node() if read else None
        if self.buffer is not None:
            assert len(self.buffer) <= CONTROL_FILE_MAX_SIZE

    @handler
    def release(self, flags):
        pass

    @handler
    def fgetattr(self):
#       st_size = len(self.buffer) if self.buffer is not None else 0

        return fuse.Stat(
            st_mode=0o644 | stat.S_IFREG,
            st_nlink=1,
            st_uid=self.fs.uid,
            st_gid=self.fs.gid,
            st_size=CONTROL_FILE_MAX_SIZE,
        )

    @handler
    def read(self, length, offset):
        if self.buffer is None:
            return -errno.EINVAL
        return self.buffer[offset:offset+length]

    @handler
    def write(self, buf, offset):
        assert offset == 0
        logging.debug('%s: written %r', self.path, buf)
        self.node(buf)
        return len(buf)

    @handler
    def ftruncate(self, length):
        pass

class ControlStorage(_storage.AbstractStorage):
    '''Control pseudo-storage'''
    file_class = ControlFile

    def get_node_for_path(self, path, *, need_directory=False, need_file=False,
            need_read=False, need_write=False):
        logging.debug('get_node_for_path(path=%r)', path)
        path = pathlib.PurePosixPath(path)
        # pylint: disable=no-value-for-parameter
        node = self.query_object_for_node(self.fs, *path.parts)

        if need_directory and not self.node_isdir(node):
            raise OSError(errno.ENOTDIR, '')
        if (need_file or need_read or need_write) and self.node_isdir(node):
            raise OSError(errno.EISDIR, '')
        if ((need_read and not node._control_read)
        or (need_write and not node._control_write)):
            raise OSError(errno.ENOANO, '')

        return node

    @staticmethod
    def node_isdir(node):
        return getattr(node, '_control_directory', True)

    @staticmethod
    def node_list(obj):
        try:
            obj._control_directory

        except AttributeError:
            for attr in dir(obj):
                try:
                    attr = getattr(obj, attr)
                    name = attr._control_name
                except AttributeError:
                    continue
                yield name, attr
            return

        if not obj._control_directory:
            raise OSError(errno.ENOTDIR, '')

        yield from obj()

    def query_object_for_node(self, obj, part0=None, *parts):
        if part0 is None:
            return obj

        for name, attr in self.node_list(obj):
            if name == part0:
                return self.query_object_for_node(attr, *parts)

        raise OSError(errno.ENOENT, '')

    def getattr(self, path):
        node = self.get_node_for_path(path)

        if self.node_isdir(node):
            return fuse.Stat(
                st_mode=stat.S_IFDIR | 0o755,
                st_nlink=2, # XXX +number of subdirectories
                st_uid=self.fs.uid,
                st_gid=self.fs.gid,
            )

        st_mode = stat.S_IFREG
        if node._control_read:
            st_mode += 0o444
        if node._control_write:
            st_mode += 0o200

        return fuse.Stat(
            st_mode=st_mode,
            st_nlink=1,
            st_uid=self.fs.uid,
            st_gid=self.fs.gid,
            st_size=CONTROL_FILE_MAX_SIZE,
        )

    def readdir(self, path):
        node = self.get_node_for_path(path, need_directory=True)
        for name, _obj in self.node_list(node):
            yield name

    def truncate(self, path, length):
        pass
