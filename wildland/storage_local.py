#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import errno
import os
import pathlib

from voluptuous import Schema, All, Coerce
import yaml

from . import storage as _storage
from .fuse_utils import flags_to_mode, handler
from .storage_control import control

__all__ = ['LocalStorage']

class LocalFile:
    @handler
    def __init__(self, path, realpath, flags, mode=0):
        self.path = path
        self.realpath = realpath

        # pylint: disable=protected-access
        self.file = os.fdopen(
            os.open(realpath, flags, mode),
            flags_to_mode(flags))

    @handler
    def release(self, _flags):
        return self.file.close()

    @handler
    def fgetattr(self):
        '''...

        Without this method, at least :meth:`read` does not work.
        '''
        return os.fstat(self.file.fileno())

    @handler
    def read(self, length, offset):
        self.file.seek(offset)
        return self.file.read(length)

    @handler
    def write(self, buf, offset):
        self.file.seek(offset)
        return self.file.write(buf)

    @handler
    def ftruncate(self, length):
        return self.file.truncate(length)


class LocalStorage(_storage.AbstractStorage, _storage.FileProxyMixin):
    '''Local, file-based storage'''
    SCHEMA = Schema({
        # pylint: disable=no-value-for-parameter
        'type': 'local',
        'path': All(Coerce(pathlib.Path)),
    }, required=True)

    def __init__(self, *, path, relative_to=None, **kwds):
        super().__init__(**kwds)
        path = pathlib.Path(path)
        if relative_to is not None:
            path = relative_to / path
        path = path.resolve()
        if not path.is_dir():
            raise OSError(errno.ENOENT,
                f'LocalStorage root does not exist: {path}')
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

    @control('manifest.yaml', read=True)
    def control_manifest_read(self):
        return yaml.dump({'type': 'local', 'path': os.fspath(self.root)},
            default_flow_style=False).encode()
