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

"""
Abstract classes for storage
"""

import abc
import hashlib
import itertools
import logging
import os
import pathlib
import posixpath
import stat
import urllib.parse
from collections import namedtuple
from dataclasses import dataclass
from pathlib import PurePosixPath, Path
from typing import Optional, Dict, Type, Any, List, Iterable, Tuple

import click

from ..manifest.sig import SigContext
from ..manifest.manifest import Manifest
from ..manifest.schema import Schema
from ..hashdb import HashDb

BLOCK_SIZE = 1024 ** 2
logger = logging.getLogger('storage')

HashCache = namedtuple('HashCache', ['hash', 'token'])


class StorageError(BaseException):
    """
    Error in the storage mechanism.
    """


class OptionalError(NotImplementedError):
    """
    A variant of NotImplementedError.

    This is a hack to stop pylint from complaining about methods that do not
    have to be implemented.
    """


class HashMismatchError(BaseException):
    """
    Thrown when hash mismatch occurs on an attempt to perform compare-and-swap.
    """


@dataclass
class Attr:
    """
    File attributes. A subset of ``statinfo``.
    """

    mode: int
    size: int = 0
    timestamp: int = 0

    def is_dir(self) -> bool:
        """
        Convenience method to check if this is a directory.
        """

        return stat.S_ISDIR(self.mode)

    @staticmethod
    def file(size: int = 0, timestamp: int = 0) -> 'Attr':
        """
        Simple file with default access mode.
        """

        return Attr(
            mode=stat.S_IFREG | 0o644,
            size=size,
            timestamp=timestamp)

    @staticmethod
    def dir(size: int = 0, timestamp: int = 0) -> 'Attr':
        """
        Simple directory with default access mode.
        """

        return Attr(
            mode=stat.S_IFDIR | 0o755,
            size=size,
            timestamp=timestamp)


class File(metaclass=abc.ABCMeta):
    """
    Abstract base class for a file. To be returned from ``open()`` and ``create()``.

    Methods are optional to implement, except :meth:`File.release`.
    """

    # pylint: disable=missing-docstring, no-self-use

    @abc.abstractmethod
    def release(self, flags: int) -> None:
        """
        Releases file-related resources.
        """
        raise NotImplementedError()

    def read(self, length: Optional[int] = None, offset: int = 0) -> bytes:
        """
        Read data from an open file. This method is a proxy for
        :meth:`wildland.storage_backends.base.StorageBackend.read`.
        """
        raise OptionalError()

    def write(self, data: bytes, offset: int) -> int:
        """
        Write data to an open file. This method is a proxy for
        :meth:`wildland.storage_backends.base.StorageBackend.write`.
        """
        raise OptionalError()

    def fgetattr(self) -> Attr:
        raise OptionalError()

    def ftruncate(self, length: int) -> None:
        raise OptionalError()

    def flush(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release(0)


class StorageBackend(metaclass=abc.ABCMeta):
    """Abstract storage implementation.

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
    """
    SCHEMA = Schema('storage')
    TYPE = ''

    _types: Dict[str, Type['StorageBackend']] = {}
    _cache: Dict[str, 'StorageBackend'] = {}

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
            self.read_only = params.get('read-only', False)

        if read_only:
            self.read_only = True

        self.ignore_own_events = False

        self.watcher_instance = None
        self.hash_cache: Dict[PurePosixPath, HashCache] = {}
        self.hash_db = None
        self.mounted = 0

        self.backend_id = self.params['backend-id']

    @classmethod
    def cli_options(cls) -> List[click.Option]:
        """
        Provide a list of command-line options needed to create this storage.
        """
        raise OptionalError()

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert provided command-line arguments to a list of storage parameters.
        """
        raise OptionalError()

    @staticmethod
    def types() -> Dict[str, Type['StorageBackend']]:
        """
        Lazily initialized type -> storage class mapping.
        """

        if not StorageBackend._types:
            # pylint: disable=import-outside-toplevel,cyclic-import
            from .dispatch import get_storage_backends
            StorageBackend._types = get_storage_backends()

        return StorageBackend._types

    def request_mount(self) -> None:
        """
        Request storage to be mounted, if not mounted already.
        """
        if self.mounted == 0:
            self.mount()
        self.mounted += 1

    def request_unmount(self) -> None:
        """
        Request storage to be unmounted, if not used anymore.
        """
        self.mounted -= 1
        if self.mounted == 0:
            self.unmount()

    def __enter__(self):
        self.request_mount()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.request_unmount()

    # pylint: disable=missing-docstring, no-self-use

    def mount(self) -> None:
        """
        Initialize. Called when mounting.

        Backend should implement this method if necessary.
        External callers should use *request_mount* instead.
        """

    def unmount(self) -> None:
        """
        Clean up. Called when unmounting.

        Backend should implement this method if necessary.
        External callers should use *request_unmount* instead.
        """

    def clear_cache(self) -> None:
        """
        Clear cache, if any.
        """

    def start_watcher(self, handler, ignore_own_events=False):
        self.ignore_own_events = ignore_own_events

        if self.watcher_instance:
            raise StorageError("Watcher already exists")

        self.watcher_instance = self.watcher()  # pylint: disable=assignment-from-none

        if not self.watcher_instance:
            return None

        self.watcher_instance.start(handler)

        return self.watcher_instance

    def stop_watcher(self):
        if not self.watcher_instance:
            return

        self.watcher_instance.stop()

        self.watcher_instance = None
        self.ignore_own_events = False

    def watcher(self):
        """
        Create a StorageWatcher (see watch.py) for this storage, if supported. If the storage
        manifest contains a 'watcher-interval' parameter, SimpleStorageWatcher (which is a naive,
        brute-force watcher that scans the entire storage every watcher-interval seconds) will be
        used. If a given StorageBackend provides a better solution, it's recommended to overwrite
        this method to provide it. It is recommended to still use SimpleStorageWatcher if the user
        explicitly specifies watcher-interval in the manifest. See local.py for a simple super()
        implementation that avoids duplicating code.

        Note that changes originating from FUSE are reported without using this
        mechanism.
        """
        if 'watcher-interval' in self.params:
            # pylint: disable=import-outside-toplevel, cyclic-import
            logger.warning("Using simple storage watcher - it can be very inefficient.")
            from ..storage_backends.watch import SimpleStorageWatcher
            return SimpleStorageWatcher(self, interval=int(self.params['watcher-interval']))
        return None

    def set_config_dir(self, config_dir):
        """
        Set path to config dir. Used to store hashes in a local sqlite DB.
        """
        self.hash_db = HashDb(config_dir)
    # FUSE file operations. Return a File instance.

    @abc.abstractmethod
    def open(self, path: PurePosixPath, flags: int) -> File:
        """
        Open a file with given ``path``. Access ``flags`` should be used to check if the operation
        is permitted.
        """
        raise NotImplementedError()

    def create(self, path: PurePosixPath, flags: int, mode: int = 0o666):
        """
        Create and open a file. If the file does not exist, first create it with the specified mode,
        and then open it.
        """
        raise OptionalError()

    # Method proxied to the File instance

    def release(self, _path: PurePosixPath, flags: int, obj: File) -> None:
        obj.release(flags)

    def read(self, _path: PurePosixPath, length: Optional[int], offset: int, obj: File) -> bytes:
        """
        Read data from an open file.

        Read should return exactly the number of bytes requested except on EOF or error, otherwise
        the rest of the data will be substituted with zeroes. An exception to this is when the
        ``direct_io`` mount option is specified, in which case the return value of the read system
        call will reflect the return value of this operation.

        This method is proxied to :meth:`wildland.storage_backends.base.File.read`.
        """
        return obj.read(length, offset)

    def write(self, _path: PurePosixPath, data: bytes, offset: int, obj: File) -> int:
        """
        Write data to an open file.

        Write should return exactly the number of bytes requested except on error. An exception to
        this is when the ``direct_io`` mount option is specified.

        This method is proxied to :meth:`wildland.storage_backends.base.File.write`.
        """
        return obj.write(data, offset)

    def fgetattr(self, _path: PurePosixPath, obj: File) -> Attr:
        return obj.fgetattr()

    def ftruncate(self, _path: PurePosixPath, length: int, obj: File) -> None:
        return obj.ftruncate(length)

    def flush(self, _path: PurePosixPath, obj: File) -> None:
        obj.flush()

    # Other FUSE operations

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        Get file attributes.
        """
        raise OptionalError()

    def readdir(self, path: PurePosixPath) -> Iterable[str]:
        """
        Return iterable of files' names living in the given directory.
        """
        raise OptionalError()

    def truncate(self, path: PurePosixPath, length: int) -> None:
        """
        Truncate or extend the given file so that it is precisely ``length`` bytes long.
        """
        raise OptionalError()

    def unlink(self, path: PurePosixPath) -> None:
        """
        Remove a file.
        """
        raise OptionalError()

    def mkdir(self, path: PurePosixPath, mode: int = 0o777) -> None:
        """
        Create a directory with the given name. The directory permissions are encoded in ``mode``.
        """
        raise OptionalError()

    def rmdir(self, path: PurePosixPath) -> None:
        """
        Remove a directory.
        """
        raise OptionalError()

    def chmod(self, path: PurePosixPath, mode: int) -> None:
        raise OptionalError()

    def chown(self, _path: PurePosixPath, _uid: int, _gid: int) -> None:
        return OptionalError()

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        raise OptionalError()

    def utimens(self, path: PurePosixPath, atime, mtime) -> None:
        """
        https://github.com/libfuse/python-fuse/blob/6c3990f9e3dce927c693e66dc14138822b42564b/fuse.py#L474

        :param atime: fuse.Timespec access time
        :param mtime: fuse.Timespec modification time
        """
        raise OptionalError()

    # Other operations

    def get_file_token(self, path: PurePosixPath) -> Optional[int]:
        # used to implement hash caching; should provide a token that changes when the file changes.
        raise OptionalError()

    def get_hash(self, path: PurePosixPath):
        """
        Return (and, if get_file_token is implemented, cache) sha256 hash for object at path.
        """
        try:
            current_token = self.get_file_token(path)
        except OptionalError:
            current_token = None

        if current_token:
            hash_cache = self.retrieve_hash(path)
            if hash_cache and current_token == hash_cache.token:
                return hash_cache.hash

        hasher = hashlib.sha256()
        offset = 0
        try:
            with self.open(path, os.O_RDONLY) as obj:
                size = obj.fgetattr().size
                while offset < size:
                    data = obj.read(BLOCK_SIZE, offset)
                    offset += len(data)
                    hasher.update(data)
        except NotADirectoryError:
            return None

        new_hash = hasher.hexdigest()
        if current_token:
            self.store_hash(path, HashCache(new_hash, current_token))
        return new_hash

    def store_hash(self, path, hash_cache):
        """
        Store provided hash in persistent (if available) storage and in local dict.
        """
        if self.hash_db:
            self.hash_db.store_hash(self.backend_id, path, hash_cache)
        self.hash_cache[path] = hash_cache

    def retrieve_hash(self, path):
        """
        Get cached hash, if possible; priority is given to local dict, then to permanent storage.
        """
        if path in self.hash_cache:
            return self.hash_cache[path]
        if self.hash_db:
            return self.hash_db.retrieve_hash(self.backend_id, path)
        return None

    def open_for_safe_replace(self, path: PurePosixPath, flags: int, original_hash: str) -> File:
        """
        This should implement a version of compare-and-swap: open a file, write data as needed,
        but apply those changes (on release) only if file hash before the changes matched
        original_hash. Should throw HashMismatchError if hashes are mismatched (both at open
        and at release).
        """
        raise OptionalError()

    def walk(self, directory=PurePosixPath('')) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        A simplified variant of os.walk : returns a generator of paths of all objects in the given
        directory (or the whole storage if none given). Assumes the results will be given
        depth-first.
        """
        for path in self.readdir(directory):
            full_path = directory / path
            file_obj_atr = self.getattr(full_path)
            yield full_path, file_obj_atr
            if file_obj_atr.is_dir():
                yield from self.walk(full_path)

    def list_subcontainers(
            self,
            sig_context: Optional[SigContext] = None,
        ) -> Iterable[dict]:
        """
        List sub-containers provided by this storage.

        This method should return an iterable of dict representation of partial manifests.
        Specifically, 'owner' field must not be filled in (will be inherited from
        the parent container).

        Storages of listed containers, when set as 'delegate' backend,
        may reference parent (this) container via Wildland URL:
        `wildland:@default:@parent-container:`

        :return:
        """
        raise OptionalError()

    @staticmethod
    def from_params(params, read_only=False, deduplicate=False) -> 'StorageBackend':
        """
        Construct a Storage from fields originating from manifest.

        Assume the fields have been validated before.

        :param deduplicate: return cached object instance when called with the same params
        """

        if deduplicate:
            deduplicate = params['backend-id']
            if deduplicate in StorageBackend._cache:
                return StorageBackend._cache[deduplicate]

        # Recursively handle proxy storages
        if 'storage' in params:
            # do not modify function argument - it can be used for other things
            params = params.copy()
            params['storage'] = StorageBackend.from_params(params['storage'],
                                                           deduplicate=deduplicate)

        storage_type = params['type']
        cls = StorageBackend.types()[storage_type]
        backend = cls(params=params, read_only=read_only)
        if deduplicate:
            StorageBackend._cache[deduplicate] = backend
        return backend

    @staticmethod
    def is_type_supported(storage_type):
        """
        Check if the storage type is supported.
        """
        return storage_type in StorageBackend.types()

    @staticmethod
    def validate_manifest(manifest):
        """
        Validate manifest, assuming it's of a supported type.
        """

        storage_type = manifest.fields['type']
        cls = StorageBackend.types()[storage_type]
        manifest.apply_schema(cls.SCHEMA)

    def get_url_for_path(self, path):
        """
        Return a URL, under which a file can be accessed.
        """
        assert not path.is_absolute()
        if 'base-url' not in self.params:
            return None
        return posixpath.join(self.params['base-url'],
            urllib.parse.quote_from_bytes(bytes(pathlib.PurePosixPath(path))))


class StaticSubcontainerStorageMixin:
    """
    A backend storage mixin that is used in all backends that support ``subcontainers`` key in their
    manifests.

    The ``subcontainers`` key is an array that holds a list of relative paths to the subcontainers
    manifests within the storage itself. The paths are relative to the storage's root (i.e. ``path``
    for Local storage backend).

    When adding this mixin, you should append the following snippet to the backend's ``SCHEMA``::

        "subcontainers" : {
            "type": "array",
            "items": {
                "$ref": "types.json#rel-path",
            }
        }

    """

    def list_subcontainers(
        self,
        sig_context: Optional[SigContext] = None,
    ) -> Iterable[dict]:
        """
        Return list of subcontainers manifest fields based and perform an integrity check on each
        container.
        """
        if not sig_context:
            raise ValueError('Signature context must be defined for static subcontainers')

        trusted_owner = self.params.get('owner') if self.params.get('trusted') else None
        for subcontainer_path in self.params.get('subcontainers', []):
            with self.open(PurePosixPath(subcontainer_path), os.O_RDONLY) as file:
                manifest = Manifest.from_bytes(
                    data=file.read(None, 0),
                    sig_context=sig_context,
                    trusted_owner=trusted_owner,
                )

                if self.params.get('owner') == manifest.fields.get('owner'):
                    yield manifest.fields

def _inner_proxy(method_name):
    def method(self, *args, **kwargs):
        return getattr(self.inner, method_name)(*args, **kwargs)

    method.__name__ = method_name
    return method


def verify_local_access(path: Path, user: str, is_local_owner: bool):
    """
    Check if given WL user can access a local file.

    This includes checking if user is on a local-owners list,
    or if a accessed directory (or any of its ancestors)
    have explicitly allowed given user access using `.wildland-owners` file.

    If access is given, returns True, otherwise throws PermissionError

    :param path: path to check
    :param user: user id (string like 0x...)
    :param is_local_owner: whether the user is in local owners list
    :return:
    """

    if is_local_owner:
        return True

    for parent in itertools.chain([path], path.parents):
        flag_file = parent / '.wildland-owners'
        try:
            allowed_owners = flag_file.read_text('utf-8', 'ignore').splitlines()
            for owner in allowed_owners:
                owner = owner.partition('#')[0].strip()
                if owner == user:
                    return True
        except (FileNotFoundError, NotADirectoryError):
            # silently ignore those
            pass
        except OSError as e:
            logger.warning('Cannot read %s: %s', flag_file, e)

    raise PermissionError(
        'User {} is not allowed to access {}: not in local-owners nor .wildland-owners file'.
            format(user, path))
