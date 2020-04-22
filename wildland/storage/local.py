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
import pathlib
import logging

from .base import AbstractStorage, FileProxyMixin
from .control import control_file
from ..fuse_utils import flags_to_mode
from ..manifest.schema import Schema

__all__ = ['LocalStorage']

class LocalFile:
    '''A file on disk

    (does not need to be a regular file)
    '''
    def __init__(self, path, realpath, flags, mode=0):
        self.path = path
        self.realpath = realpath

        self.file = os.fdopen(
            os.open(realpath, flags, mode),
            flags_to_mode(flags))

    # pylint: disable=missing-docstring

    def release(self, _flags):
        return self.file.close()

    def fgetattr(self):
        '''...

        Without this method, at least :meth:`read` does not work.
        '''
        return os.fstat(self.file.fileno())

    def read(self, length, offset):
        self.file.seek(offset)
        return self.file.read(length)

    def write(self, buf, offset):
        self.file.seek(offset)
        return self.file.write(buf)

    def ftruncate(self, length):
        return self.file.truncate(length)


class LocalStorage(AbstractStorage, FileProxyMixin):
    '''Local, file-based storage'''
    SCHEMA = Schema('storage-local')
    TYPE = 'local'

    def __init__(self, *, manifest, relative_to=None, **kwds):
        super().__init__(manifest=manifest, **kwds)
        path = pathlib.Path(manifest.fields['path'])
        if relative_to is not None:
            path = relative_to / path
        path = path.resolve()
        if not path.is_dir():
            logging.warning('LocalStorage root does not exist: %s', path)
        self.root = path

    def _path(self, path):
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
        return os.lstat(self._path(path))

    def readdir(self, path):
        return os.listdir(self._path(path))

    def truncate(self, path, length):
        return os.truncate(self._path(path), length)

    def unlink(self, path):
        return os.unlink(self._path(path))

    @control_file('manifest.yaml')
    def control_manifest_read(self):
        return self.manifest.to_bytes()
