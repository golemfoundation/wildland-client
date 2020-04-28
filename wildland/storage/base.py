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
from typing import Optional, Dict, List, Type

from .control_decorators import control_file
from ..manifest.schema import Schema
from ..manifest.manifest import Manifest


class AbstractStorage(metaclass=abc.ABCMeta):
    '''Abstract storage implementation.

    Any implementation should inherit from this class.

    Currently the storage should implement an interface similar to FUSE.
    This implementation detail might change in the future.

    Although FUSE allows returning an error value (like -errno.ENOENT), the
    storage should always raise an exception if the operation fails, like so:

        raise FileNotFoundError(str(path))

    Or:

        raise OSError(errno.ENOENT, str(path))

    See also Python documentation for OS exceptions:
    https://docs.python.org/3/library/exceptions.html#os-exceptions
    '''
    SCHEMA = Schema('storage')
    TYPE = ''

    _types: Dict[str, Type['AbstractStorage']] = {}

    def __init__(self, *, manifest: Optional[Manifest] = None, **kwds):
        # pylint: disable=redefined-builtin, unused-argument
        self.manifest: Optional[Manifest] = None
        if manifest:
            assert manifest.fields['type'] == self.TYPE
            self.manifest = manifest

    @staticmethod
    def types() -> Dict[str, Type['AbstractStorage']]:
        '''
        Lazily initialized type -> storage class mapping.
        '''

        if AbstractStorage._types:
            return AbstractStorage._types

        # pylint: disable=import-outside-toplevel,cyclic-import
        from .local import LocalStorage
        from .local_cached import LocalCachedStorage
        from .s3 import S3Storage
        from .webdav import WebdavStorage

        classes: List[Type[AbstractStorage]] = [
            LocalStorage,
            LocalCachedStorage,
            S3Storage,
            WebdavStorage,
        ]

        for cls in classes:
            AbstractStorage._types[cls.TYPE] = cls

        return AbstractStorage._types

    # pylint: disable=missing-docstring

    def mount(self):
        pass

    def refresh(self):
        pass

    @control_file('manifest.yaml')
    def control_manifest_read(self):
        if self.manifest:
            return self.manifest.to_bytes()
        return b''

    @abc.abstractmethod
    def open(self, path, flags):
        raise NotImplementedError()

    @abc.abstractmethod
    def create(self, path, flags, mode):
        raise NotImplementedError()

    @abc.abstractmethod
    def release(self, path, flags, obj):
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, path, length, offset, obj):
        raise NotImplementedError()

    @abc.abstractmethod
    def write(self, path, data, offset, obj):
        raise NotImplementedError()

    @abc.abstractmethod
    def fgetattr(self, path, obj):
        raise NotImplementedError()

    @abc.abstractmethod
    def ftruncate(self, path, length, obj):
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

        storage_type = manifest.fields['type']
        cls = AbstractStorage.types()[storage_type]
        return cls(manifest=manifest, uid=uid, gid=gid)

    @staticmethod
    def is_manifest_supported(manifest):
        '''
        Check if the storage type is supported.
        '''
        storage_type = manifest.fields['type']
        return storage_type in AbstractStorage.types()

    @staticmethod
    def validate_manifest(manifest):
        '''
        Validate manifest, assuming it's of a supported type.
        '''

        storage_type = manifest.fields['type']
        cls = AbstractStorage.types()[storage_type]
        manifest.apply_schema(cls.SCHEMA)


def _proxy(method_name):
    def method(_self, *args, **_kwargs):
        _path, rest, fileobj = args[0], args[1:-1], args[-1]
        if not hasattr(fileobj, method_name):
            raise OSError(errno.ENOSYS, '')
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


        class MyStorage(FileProxyMixin, AbstractStorage):
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
