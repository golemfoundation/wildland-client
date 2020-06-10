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
from pathlib import PurePosixPath
from typing import Optional, Dict, Type, Any, List, TypeVar
import click
import yaml
import fuse

from ..manifest.schema import Schema
from .control_decorators import control_file


F = TypeVar('F')


class StorageBackend(metaclass=abc.ABCMeta):
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

    _types: Dict[str, Type['StorageBackend']] = {}

    def __init__(self, *,
                 params: Optional[Dict[str, Any]] = None,
                 read_only: bool = False,
                 **kwds):
        # pylint: disable=redefined-builtin, unused-argument
        self.read_only = False
        self.params: Dict[str, Any] = {}
        if params:
            assert params['type'] == self.TYPE
            self.params = params
            self.read_only = params.get('read_only', False)

        if read_only:
            self.read_only = True

    @classmethod
    def cli_options(cls) -> List[click.Option]:
        '''
        Provide a list of command-line options needed to create this storage.
        '''
        raise NotImplementedError()

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Convert provided command-line arguments to a list of storage parameters.
        '''
        raise NotImplementedError()

    @staticmethod
    def types() -> Dict[str, Type['StorageBackend']]:
        '''
        Lazily initialized type -> storage class mapping.
        '''

        if not StorageBackend._types:
            # pylint: disable=import-outside-toplevel,cyclic-import
            from .dispatch import get_storage_backends
            StorageBackend._types = get_storage_backends()

        return StorageBackend._types

    # pylint: disable=missing-docstring

    @control_file('manifest.yaml')
    def control_manifest_read(self) -> bytes:
        return yaml.dump(self.params).encode('ascii')

    def mount(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    # File operations (here described on abstract type F).
    # Can be implemented using FileProxyMixin, see below.

    @abc.abstractmethod
    def open(self, path: PurePosixPath, flags: int) -> F:
        raise NotImplementedError()

    @abc.abstractmethod
    def create(self, path: PurePosixPath, flags: int, mode: int) -> F:
        raise NotImplementedError()

    @abc.abstractmethod
    def release(self, path: PurePosixPath, flags: int, obj: F) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def read(self, path: PurePosixPath, length: int, offset: int, obj: F) -> bytes:
        raise NotImplementedError()

    @abc.abstractmethod
    def write(self, path: PurePosixPath, data: bytes, offset: int, obj: F) -> int:
        raise NotImplementedError()

    @abc.abstractmethod
    def fgetattr(self, path: PurePosixPath, obj: F) -> fuse.Stat:
        raise NotImplementedError()

    @abc.abstractmethod
    def ftruncate(self, path: PurePosixPath, length: int, obj: F) -> None:
        raise NotImplementedError()

    # Other operations.

    @abc.abstractmethod
    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        raise NotImplementedError()

    @abc.abstractmethod
    def readdir(self, path: PurePosixPath) -> List[str]:
        raise NotImplementedError()

    @abc.abstractmethod
    def truncate(self, path: PurePosixPath, length: int) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def unlink(self, path: PurePosixPath) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def mkdir(self, path: PurePosixPath, mode: int) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def rmdir(self, path: PurePosixPath) -> None:
        raise NotImplementedError()


    @staticmethod
    def from_params(params, uid, gid, read_only=False) -> 'StorageBackend':
        '''
        Construct a Storage from fields originating from manifest.

        Assume the fields have been validated before.
        '''

        storage_type = params['type']
        cls = StorageBackend.types()[storage_type]
        return cls(params=params, uid=uid, gid=gid, read_only=read_only)

    @staticmethod
    def is_type_supported(storage_type):
        '''
        Check if the storage type is supported.
        '''
        return storage_type in StorageBackend.types()

    @staticmethod
    def validate_manifest(manifest):
        '''
        Validate manifest, assuming it's of a supported type.
        '''

        storage_type = manifest.fields['type']
        cls = StorageBackend.types()[storage_type]
        manifest.apply_schema(cls.SCHEMA)


def _proxy(method_name):
    def method(_self, *args, **_kwargs):
        _path, rest, fileobj = args[0], args[1:-1], args[-1]
        try:
            return getattr(fileobj, method_name)(*rest)
        except NotImplementedError:
            raise OSError(errno.ENOSYS, '')

    method.__name__ = method_name

    return method


class File(metaclass=abc.ABCMeta):
    '''
    Abstract base class for a file. Subclass and use with FileProxyMixin.

    Methods are optional to implement, except release().
    '''

    # pylint: disable=missing-docstring

    @abc.abstractmethod
    def release(self, flags: int) -> None:
        raise NotImplementedError()

    def read(self, length: int, offset: int) -> bytes:
        raise NotImplementedError()

    def write(self, data: bytes, offset: int) -> int:
        raise NotImplementedError()

    def fgetattr(self) -> fuse.Stat:
        raise NotImplementedError()

    def ftruncate(self, length: int) -> None:
        raise NotImplementedError()


class FileProxyMixin:
    '''
    A mixin to use if you want to work with object-based files.
    Make sure that your open() and create() methods return objects.

    Example:

        class MyFile(File):
            def __init__(self, path, flags, mode=0, ...):
                ...

            def read(self, length, offset):
                ...


        class MyStorageBackend(FileProxyMixin, StorageBackend):
            def open(self, path, flags):
                return MyFile(path, flags, ...)

            def create(self, path, flags, mode):
                return MyFile(path, flags, ...)
    '''

    read = _proxy('read')
    write = _proxy('write')
    fsync = _proxy('fsync')
    release = _proxy('release')
    # flush = _proxy('flush')
    fgetattr = _proxy('fgetattr')
    ftruncate = _proxy('ftruncate')
    # lock = _proxy('lock')
