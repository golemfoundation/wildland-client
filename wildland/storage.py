#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import abc
import errno
import logging

from voluptuous import Schema

class AbstractFile(metaclass=abc.ABCMeta):
    # to be set in IntermediateFile (see fuse.py)
    fs = None

    # to be set in __new__ (see below)
    container = None
    storage = None

    @abc.abstractmethod
    def __init__(self, fs, container, storage, path, flags, *args):
        self.fs = fs
        self.container = container
        self.storage = storage
        self.log = logging.getLogger(type(self).__name__)

    # NOTE: due to hasattr() logic in python-fuse, all used methods need to be
    # defined here! therefore we can't make them abstract
    # XXX or can we? every implementer will have to make concious decision about
    # each one

    # pylint: disable=no-self-use,unused-argument

    def read(self, *args, **kwds):
        return -errno.ENOSYS

    def write(self, *args, **kwds):
        return -errno.ENOSYS

    def fsync(self, *args, **kwds):
        return -errno.ENOSYS

    def release(self, *args, **kwds):
        return -errno.ENOSYS

    def flush(self, *args, **kwds):
        return -errno.ENOSYS

    def fgetattr(self, *args, **kwds):
        return -errno.ENOSYS

    def ftruncate(self, *args, **kwds):
        return -errno.ENOSYS

    def lock(self, *args, **kwds):
        return -errno.ENOSYS


class AbstractStorage(metaclass=abc.ABCMeta):
    '''Abstract storage implementation.

    Any implementation should inherit from this class.

    Currently the storage should implement an interface similar to FUSE.
    This implementation detail might change in the future.
    '''
    SCHEMA = Schema({})

    def __init__(self, *, fs, **_kwds):
        self.fs = fs

    @property
    @abc.abstractmethod
    def file_class(self):
        raise NotImplementedError()

    @classmethod
    def fromdict(cls, data, **kwds):
        '''Load storage manifest from :class:`dict`'''
        logging.debug('%s.fromdict(%r)', cls.__name__, data)
        data = cls.SCHEMA(data)
        logging.debug('data=%r', data)
        return cls(**data, **kwds)

    # pylint: disable=missing-docstring

    @abc.abstractmethod
    def getattr(self, path):
        raise NotImplementedError()

    @abc.abstractmethod
    def readdir(self, path):
        raise NotImplementedError()

    @abc.abstractmethod
    def truncate(self, path, length):
        raise NotImplementedError()
