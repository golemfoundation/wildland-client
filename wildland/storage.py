#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import abc
import errno
from typing import Optional

from voluptuous import Schema

from .manifest import Manifest

class AbstractStorage(metaclass=abc.ABCMeta):
    '''Abstract storage implementation.

    Any implementation should inherit from this class.

    Currently the storage should implement an interface similar to FUSE.
    This implementation detail might change in the future.
    '''
    SCHEMA = Schema({})
    type = 'local'

    def __init__(self, *, manifest: Optional[Manifest] = None, **kwds):
        # pylint: disable=redefined-builtin, unused-argument
        if manifest:
            assert manifest.fields['type'] == self.type
            self.manifest = manifest

    @abc.abstractmethod
    def open(self, path, flags):
        raise NotImplementedError()

    @abc.abstractmethod
    def create(self, path, flags, mode):
        raise NotImplementedError()

    @abc.abstractmethod
    def getattr(self, path):
        raise NotImplementedError()

    @abc.abstractmethod
    def readdir(self, path):
        raise NotImplementedError()

    @abc.abstractmethod
    def truncate(self, path, length):
        raise NotImplementedError()

    @abc.abstractmethod
    def unlink(self, path):
        raise NotImplementedError()


def proxy(method_name):
    def method(_self, *args, **_kwargs):
        _path, rest, fileobj = args[0], args[1:-1], args[-1]
        if not hasattr(fileobj, method_name):
            return -errno.ENOSYS
        return getattr(fileobj, method_name)(*rest)

    method.__name__ = method_name

    return method


class FileProxyMixin:
    '''
    A mixin to use if you want to work with object-based files.
    Make sure that your open() and create() methods return objects.

    Example:

        class MyFile:
            def __init__(self, path, flags, mode=0, ...):
                ...

            def read(self, length, offset):
                ...


        class MyStorage(AbstractStorage, FileProxyMixin):
            def open(self, path, flags):
                return MyFile(path, flags, ...)

            def create(self, path, flags, mode):
                return MyFile(path, flags, ...)
    '''

    read = proxy('read')
    write = proxy('write')
    fsync = proxy('fsync')
    release = proxy('release')
    flush = proxy('flush')
    fgetattr = proxy('fgetattr')
    ftruncate = proxy('ftruncate')
    lock = proxy('lock')
