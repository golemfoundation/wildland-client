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
Local storage, similar to :command:`mount --bind`
'''

import os
from pathlib import Path, PurePosixPath
import logging
import threading

import click

from .base import StorageBackend, File, Attr
from ..fuse_utils import flags_to_mode
from ..manifest.schema import Schema

__all__ = ['LocalStorageBackend']


def to_attr(st: os.stat_result) -> Attr:
    '''
    Convert os.stat_result to Attr.
    '''

    return Attr(
        mode=st.st_mode,
        size=st.st_size,
        timestamp=int(st.st_mtime),
    )


class LocalFile(File):
    '''A file on disk

    (does not need to be a regular file)
    '''

    def __init__(self, path, realpath, flags, mode=0):
        self.path = path
        self.realpath = realpath

        self.file = os.fdopen(
            os.open(realpath, flags, mode),
            flags_to_mode(flags))
        self.lock = threading.Lock()

    # pylint: disable=missing-docstring

    def release(self, _flags):
        return self.file.close()

    def fgetattr(self):
        '''...

        Without this method, at least :meth:`read` does not work.
        '''
        with self.lock:
            st = to_attr(os.fstat(self.file.fileno()))
            # Make sure to return the correct size.
            # TODO: Unfortunately this is not enough, as fstat() causes FUSE to
            # call getattr(), not fgetattr():
            # https://github.com/libfuse/libfuse/issues/62
            st.size = self.file.seek(0, 2)
        return st

    def read(self, length, offset):
        with self.lock:
            self.file.seek(offset)
            return self.file.read(length)

    def write(self, data, offset):
        with self.lock:
            self.file.seek(offset)
            return self.file.write(data)

    def ftruncate(self, length):
        with self.lock:
            self.file.truncate(length)


class LocalStorageBackend(StorageBackend):
    '''Local, file-based storage'''
    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs-path",
                "description": "Path in the local filesystem"
            }
        }
    })
    TYPE = 'local'

    def __init__(self, *, relative_to=None, **kwds):
        super().__init__(**kwds)
        path = Path(self.params['path'])
        if relative_to is not None:
            path = relative_to / path
        path = path.resolve()
        if not path.is_dir():
            logging.warning('LocalStorage root does not exist: %s', path)
        self.root = path

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--path'], metavar='PATH',
                         help='local path',
                         required=True)
        ]

    @classmethod
    def cli_create(cls, data):
        return {'path': data['path']}

    def _path(self, path: PurePosixPath) -> Path:
        '''Given path inside filesystem, calculate path on disk, relative to
        :attr:`self.root`

        Args:
            path (pathlib.PurePosixPath): the path
        Returns:
            pathlib.Path: path relative to :attr:`self.root`
        '''
        ret = (self.root / path).resolve()
        ret.relative_to(self.root) # this will throw ValueError if not relative
        return ret


    # pylint: disable=missing-docstring

    def open(self, path, flags):
        return LocalFile(path, self._path(path), flags)

    def create(self, path, flags, mode):
        return LocalFile(path, self._path(path), flags, mode)

    def getattr(self, path):
        return to_attr(os.lstat(self._path(path)))

    def readdir(self, path):
        return os.listdir(self._path(path))

    def truncate(self, path, length):
        return os.truncate(self._path(path), length)

    def unlink(self, path):
        return os.unlink(self._path(path))

    def mkdir(self, path, mode):
        return os.mkdir(self._path(path), mode)

    def rmdir(self, path):
        return os.rmdir(self._path(path))
