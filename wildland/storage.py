#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import abc
import errno
import logging

from voluptuous import Schema


class AbstractStorage(metaclass=abc.ABCMeta):
    '''Abstract storage implementation.

    Any implementation should inherit from this class.

    Currently the storage should implement an interface similar to FUSE.
    This implementation detail might change in the future.
    '''
    SCHEMA = Schema({})

    def __init__(self, type=None):
        pass

    @classmethod
    def fromdict(cls, data, **kwds):
        '''Load storage manifest from :class:`dict`'''
        logging.debug('%s.fromdict(%r)', cls.__name__, data)
        data = cls.SCHEMA(data)
        logging.debug('data=%r', data)
        return cls(**data, **kwds)

    # pylint: disable=missing-docstring

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
