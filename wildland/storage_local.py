#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import os
import errno
import pathlib

import fuse
from voluptuous import Schema, All, Coerce, IsDir

from . import storage

class LocalStorage(storage.AbstractStorage):
    '''Local, file-based storage'''
    SCHEMA = Schema({
        # pylint: disable=no-value-for-parameter
        'type': 'local',
        'path': All(Coerce(pathlib.Path)),
    }, required=True)

    def __init__(self, path, relative_to=None, **kwds):
        path = pathlib.Path(path)
        if relative_to is not None:
            path = relative_to / path
        path = path.resolve()
        if not path.is_dir():
            raise OSError(errno.ENOENT,
                f'LocalStorage root does not exist: {path}')
        self.root = path

    def _path(self, path):
        ret = (self.root / path).resolve()
        ret.relative_to(self.root) # this will throw ValueError if not relative
        return ret

#   def open(self, path):
#       return open(self._path(path))

    def getattr(self, path):
        return os.lstat(self._path(path))

    def readdir(self, path):
        return os.listdir(self._path(path))
