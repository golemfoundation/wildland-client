#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import os
import pathlib
import logging

from voluptuous import Schema, All, Coerce

from . import storage as _storage
from .fuse_utils import flags_to_mode
from .storage_control import control_file

__all__ = ['LocalStorage']

class LocalFile:
    def __init__(self, path, realpath, flags, mode=0):
        self.path = path
        self.realpath = realpath

        self.file = os.fdopen(
            os.open(realpath, flags, mode),
            flags_to_mode(flags))

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


class LocalStorage(_storage.AbstractStorage, _storage.FileProxyMixin):
    '''Local, file-based storage'''
    SCHEMA = Schema({
        # pylint: disable=no-value-for-parameter
        'signer': All(str),
        'type': 'local',
        'path': All(Coerce(pathlib.Path)),
    }, required=True)
    type = 'local'

    def __init__(self, *, manifest, relative_to=None, **kwds):
        super().__init__(manifest=manifest, **kwds)
        path = pathlib.Path(manifest.fields['path'])
        if relative_to is not None:
            path = relative_to / path
        path = path.resolve()
        if not path.is_dir():
            logging.warning('LocalStorage root does not exist: %s', path)
        self.root = path

    def open(self, path, flags):
        return LocalFile(path, self._path(path), flags)

    def create(self, path, flags, mode):
        return LocalFile(path, self._path(path), flags, mode)

    def _path(self, path):
        ret = (self.root / path).resolve()
        ret.relative_to(self.root) # this will throw ValueError if not relative
        return ret

    def getattr(self, path):
        return os.lstat(self._path(path))

    def readdir(self, path):
        return os.listdir(self._path(path))

    def truncate(self, path, length):
        with open(self._path(path), 'ab') as file:
            file.truncate(length)

    def unlink(self, path):
        return os.unlink(self._path(path))

    @control_file('manifest.yaml')
    def control_manifest_read(self):
        return self.manifest.to_bytes()
