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
from pathlib import PurePosixPath
from typing import Optional, Dict, Type, Any, List, Iterable
import stat

import click
import yaml
import fuse

from ..manifest.schema import Schema
from .control_decorators import control_file


class OptionalError(NotImplementedError):
    '''
    A variant of NotImplementedError.

    This is a hack to stop pylint from complaining about methods that do not
    have to be implemented.
    '''


class File(metaclass=abc.ABCMeta):
    '''
    Abstract base class for a file. To be returned from open() and create().

    Methods are optional to implement, except release().
    '''

    # pylint: disable=missing-docstring, no-self-use

    @abc.abstractmethod
    def release(self, flags: int) -> None:
        raise NotImplementedError()

    def read(self, length: int, offset: int) -> bytes:
        raise OptionalError()

    def write(self, data: bytes, offset: int) -> int:
        raise OptionalError()

    def fgetattr(self) -> fuse.Stat:
        raise OptionalError()

    def ftruncate(self, length: int) -> None:
        raise OptionalError()


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
                 uid: int,
                 gid: int,
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

        self.uid = uid
        self.gid = gid

    @classmethod
    def cli_options(cls) -> List[click.Option]:
        '''
        Provide a list of command-line options needed to create this storage.
        '''
        raise OptionalError()

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        '''
        Convert provided command-line arguments to a list of storage parameters.
        '''
        raise OptionalError()

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

    # pylint: disable=missing-docstring, no-self-use

    @control_file('manifest.yaml')
    def control_manifest_read(self) -> bytes:
        return yaml.dump(self.params).encode('ascii')

    def mount(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    # FUSE file operations. Return a File instance.

    @abc.abstractmethod
    def open(self, path: PurePosixPath, flags: int) -> File:
        raise NotImplementedError()

    @abc.abstractmethod
    def create(self, path: PurePosixPath, flags: int, mode: int):
        raise NotImplementedError()

    # Method proxied to the File instance

    def release(self, _path: PurePosixPath, flags: int, obj: File) -> None:
        obj.release(flags)

    def read(self, _path: PurePosixPath, length: int, offset: int, obj: File) -> bytes:
        return obj.read(length, offset)

    def write(self, _path: PurePosixPath, data: bytes, offset: int, obj: File) -> int:
        return obj.write(data, offset)

    def fgetattr(self, _path: PurePosixPath, obj: File) -> fuse.Stat:
        return obj.fgetattr()

    def ftruncate(self, _path: PurePosixPath, length: int, obj: File) -> None:
        return obj.ftruncate(length)

    # Other FUSE operations

    def getattr(self, path: PurePosixPath) -> fuse.Stat:
        raise OptionalError()

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        raise OptionalError()

    def truncate(self, path: PurePosixPath, length: int) -> None:
        raise OptionalError()

    @abc.abstractmethod
    def unlink(self, path: PurePosixPath) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def mkdir(self, path: PurePosixPath, mode: int) -> None:
        raise NotImplementedError()

    @abc.abstractmethod
    def rmdir(self, path: PurePosixPath) -> None:
        raise NotImplementedError()

    # Helpers

    def simple_file_stat(self, size: int, timestamp: int) -> fuse.Stat:
        '''
        Create a fuse.Stat object for a regular file.
        '''

        return fuse.Stat(
            st_mode=stat.S_IFREG | 0o644,
            st_nlink=1,
            st_uid=self.uid,
            st_gid=self.gid,
            st_size=size,
            st_atime=timestamp,
            st_mtime=timestamp,
            st_ctime=timestamp,
        )

    def simple_dir_stat(self, size: int = 0, timestamp: int = 0) -> fuse.Stat:
        '''
        Create a fuse.Stat object for a directory.
        '''

        return fuse.Stat(
            st_mode=stat.S_IFDIR | 0o755,
            st_nlink=1,
            st_uid=self.uid,
            st_gid=self.gid,
            st_size=size,
            st_atime=timestamp,
            st_mtime=timestamp,
            st_ctime=timestamp,
        )

    @staticmethod
    def from_params(params, uid, gid, read_only=False) -> 'StorageBackend':
        '''
        Construct a Storage from fields originating from manifest.

        Assume the fields have been validated before.
        '''

        storage_type = params['type']
        cls = StorageBackend.types()[storage_type]
        backend = cls(params=params, uid=uid, gid=gid, read_only=read_only)
        return backend

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


def _inner_proxy(method_name):
    def method(self, *args, **kwargs):
        return getattr(self.inner, method_name)(*args, **kwargs)

    method.__name__ = method_name
    return method
