# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Patryk Bęza <patryk@wildland.io>
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
Dropbox storage backend
"""
import errno
import logging
import stat
from pathlib import PurePosixPath, PosixPath
from typing import Iterable, Tuple, Optional, Callable

import click
from dropbox.files import FileMetadata, FolderMetadata, Metadata
from dropbox.exceptions import ApiError
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import FullBufferedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.storage_backends.file_subcontainers import FileSubcontainersMixin
from wildland.manifest.schema import Schema
from .dropbox_client import DropboxClient

logger = logging.getLogger('storage-dropbox')


class DropboxFileAttr(Attr):
    """
    Attributes of a Dropbox file/directory.
    """

    def __init__(self, mode, size: int=0, timestamp: int=0, content_hash: Optional[str]=None):
        super().__init__(
            mode=mode,
            size=size,
            timestamp=timestamp)
        self.content_hash = content_hash

    @classmethod
    def from_file_metadata(cls, metadata: FileMetadata) -> 'DropboxFileAttr':
        """
        Convert given file's metadata to attribute object.
        """
        latest_modification = max(
            metadata.client_modified,
            metadata.server_modified)
        timestamp = int(latest_modification.timestamp())
        return cls(
            stat.S_IFREG | 0o644,
            metadata.size,
            timestamp,
            metadata.content_hash)

    @classmethod
    def from_folder_metadata(cls, _metadata: FolderMetadata) -> 'DropboxFileAttr':
        """
        Convert given file's metadata to attribute object.
        """
        # Currently there is no way to get last modified date for Dropbox directories.
        # See: https://github.com/dropbox/dropbox-sdk-java/issues/130
        return cls(stat.S_IFDIR | 0o755)


class DropboxFile(FullBufferedFile):
    """
    Representation of a Dropbox file.
    """

    def __init__(self, client: DropboxClient, path: PurePosixPath, attr: DropboxFileAttr,
                 clear_cache_callback: Optional[Callable]=None):
        super().__init__(attr, clear_cache_callback)
        self.client = client
        self.path = path
        self.attr = attr

    def read_full(self) -> bytes:
        return self.client.get_file_content(self.path)

    def write_full(self, data: bytes) -> int:
        self.client.upload_file(data, self.path)
        return len(data)


class DropboxStorageBackend(FileSubcontainersMixin, DirectoryCachedStorageMixin, StorageBackend):
    """
    Dropbox storage supporting both read and write operations.
    """

    SCHEMA = Schema({
        "title": "Dropbox storage manifest",
        "type": "object",
        "required": ["token"],
        "properties": {
            "location": {
                "$ref": "/schemas/types.json#abs-path",
                "description": "Absolute POSIX path acting as a root directory in user's dropbox"
            },
            "token": {
                "type": ["string"],
                "description": "Dropbox OAuth 2.0 access token. You can generate it in Dropbox App "
                               "Console.",
            },
            "manifest-pattern": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#pattern-glob"},
                    {"$ref": "/schemas/types.json#pattern-list"},
                ]
            },
        }
    })
    TYPE = 'dropbox'
    LOCATION_PARAM = 'location'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        dropbox_access_token = self.params['token']
        self.client = DropboxClient(dropbox_access_token)
        self.root = PosixPath(self.params.get('location', '/')).resolve()

    @classmethod
    def cli_options(cls):
        opts = super(DropboxStorageBackend, cls).cli_options()
        opts.extend([
            click.Option(
                ['--location'], metavar='PATH', required=False, default='/',
                help='Absolute path to root directory in your Dropbox account.'),
            click.Option(
                ['--token'], metavar='ACCESS_TOKEN', required=True,
                help='Dropbox OAuth 2.0 access token. You can generate it in Dropbox App Console.')
        ])
        return opts

    @classmethod
    def cli_create(cls, data):
        result = super(DropboxStorageBackend, cls).cli_create(data)
        result.update({
            'location': data['location'],
            'token': data['token'],
        })
        return result

    @staticmethod
    def _get_attr_from_metadata(metadata: Metadata) -> DropboxFileAttr:
        if isinstance(metadata, FileMetadata):
            attr = DropboxFileAttr.from_file_metadata(metadata)
        else:
            assert isinstance(metadata, FolderMetadata)
            attr = DropboxFileAttr.from_folder_metadata(metadata)
        return attr

    def _path(self, path: PurePosixPath) -> PosixPath:
        """Given path, return a path with :attr:`self.root` prefix, relative to /
        Note that :attr:`self.root` is always an absolute path

        Args:
            path (pathlib.PurePosixPath): the path
        Returns:
            pathlib.PosixPath: path relative to /
        """
        path = (self.root / path).resolve().relative_to('/')
        return path

    def mount(self) -> None:
        self.client.connect()

    def unmount(self) -> None:
        self.client.disconnect()

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, DropboxFileAttr]]:
        for metadata in self.client.list_folder(self._path(path)):
            attr = self._get_attr_from_metadata(metadata)
            yield metadata.name, attr

    def open(self, path: PurePosixPath, _flags: int) -> DropboxFile:
        try:
            metadata = self.client.get_metadata(self._path(path))
            attr = self._get_attr_from_metadata(metadata)
            return DropboxFile(self.client, self._path(path), attr, self.clear_cache)
        except ApiError as e:
            if e.error.is_path() and e.error.get_path().is_not_found():
                raise FileNotFoundError(errno.ENOENT, str(self._path(path))) from e
            raise e

    def create(self, path: PurePosixPath, _flags: int, _mode: int = 0o666) -> DropboxFile:
        metadata = self.client.upload_empty_file(self._path(path))
        attr = DropboxFileAttr.from_file_metadata(metadata)
        self.clear_cache()
        return DropboxFile(self.client, self._path(path), attr, self.clear_cache)

    def unlink(self, path: PurePosixPath) -> None:
        self.client.unlink(self._path(path))
        self.clear_cache()

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777) -> None:
        self.client.mkdir(self._path(path))
        self.clear_cache()

    def rmdir(self, path: PurePosixPath) -> None:
        self.client.rmdir(self._path(path))
        self.clear_cache()

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath) -> None:
        self.client.rename(move_from, move_to)
        self.clear_cache()

    def utimens(self, path: PurePosixPath, _atime, _mtime) -> None:
        # pylint: disable=no-self-use
        logger.debug("utimens dummy op %s", str(path))

    def truncate(self, path: PurePosixPath, length: int) -> None:
        """
        Truncate given file.

        There is no Dropbox API call for a truncate syscall. The following is a poor man's
        implementation that involves reading a full content of the file, truncating it and saving
        back on Dropbox.
        """
        if length == 0:
            truncated_content = bytes()
        else:
            full_file_content = self.client.get_file_content(self._path(path))
            truncated_content = full_file_content[:length]
        self.client.upload_file(truncated_content, path)
        self.clear_cache()

    def get_file_token(self, path: PurePosixPath) -> Optional[str]:
        if path == PurePosixPath('.'):
            return None  # DirectoryCachedStorageMixin returns Attr.dir() for '.'
        attr = self.getattr(self._path(path))
        assert isinstance(attr, DropboxFileAttr)
        return attr.content_hash
