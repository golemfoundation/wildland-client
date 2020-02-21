#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import abc
import logging

from voluptuous import Schema

class AbstractStorage(metaclass=abc.ABCMeta):
    '''Abstract storage implementation.

    Any implementation should inherit from this class.

    Currently the storage should implement an interface similar to FUSE.
    This implementation detail might change in the future.
    '''
    SCHEMA = Schema({})

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
