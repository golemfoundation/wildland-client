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
Abstract classes for storage
'''

import abc
import errno
from typing import Optional

from ..manifest.schema import Schema
from ..manifest.manifest import Manifest
from ..exc import WildlandError

class AbstractStorage(metaclass=abc.ABCMeta):
    '''Abstract storage implementation.

    Any implementation should inherit from this class.

    Currently the storage should implement an interface similar to FUSE.
    This implementation detail might change in the future.
    '''
    SCHEMA = Schema('storage')
    TYPE = ''

    def __init__(self, *, manifest: Optional[Manifest] = None, **kwds):
        # pylint: disable=redefined-builtin, unused-argument
        if manifest:
            assert manifest.fields['type'] == self.TYPE
            self.manifest = manifest

    @staticmethod
    def from_fields(fields, uid, gid) -> 'AbstractStorage':
        '''
        Construct a Storage from fields originating from manifest.

        Assume the fields have been validated before.
        '''

        manifest = Manifest.from_fields(fields)
        manifest.skip_signing()

        return AbstractStorage.from_manifest(manifest, uid, gid)

    @staticmethod
    def from_manifest(manifest, uid, gid) -> 'AbstractStorage':
        '''
        Construct a Storage from manifest.
        '''

        # pylint: disable=import-outside-toplevel,cyclic-import
        from .local import LocalStorage
        from .s3 import S3Storage

        storage_type = manifest.fields['type']
        if storage_type == 'local':
            return LocalStorage(manifest=manifest)
        if storage_type == 's3':
            return S3Storage(manifest=manifest, uid=uid, gid=gid)
        raise WildlandError(f'unknown storage type: {storage_type}')

    @staticmethod
    def is_manifest_supported(manifest):
        '''
        Check if the storage type is supported.
        '''
        storage_type = manifest.fields['type']
        return storage_type in ['local', 's3']

    @staticmethod
    def validate_manifest(manifest):
        '''
        Validate manifest, assuming it's of a supported type.
        '''

        # pylint: disable=import-outside-toplevel,cyclic-import
        from .local import LocalStorage
        from .s3 import S3Storage

        storage_type = manifest.fields['type']
        if storage_type == 'local':
            manifest.apply_schema(LocalStorage.SCHEMA)
        if storage_type == 's3':
            manifest.apply_schema(S3Storage.SCHEMA)
        raise WildlandError(f'unknown storage type: {storage_type}')


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

    @abc.abstractmethod
    def mkdir(self, path, mode):
        raise NotImplementedError()

    @abc.abstractmethod
    def rmdir(self, path):
        raise NotImplementedError()


def _proxy(method_name):
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

    read = _proxy('read')
    write = _proxy('write')
    fsync = _proxy('fsync')
    release = _proxy('release')
    flush = _proxy('flush')
    fgetattr = _proxy('fgetattr')
    ftruncate = _proxy('ftruncate')
    lock = _proxy('lock')
