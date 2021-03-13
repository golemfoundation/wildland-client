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

import logging
import stat
from pathlib import PurePosixPath
from typing import Iterable, Tuple, Optional, Callable

import click
from dropbox.files import FileMetadata, FolderMetadata, Metadata
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import FullBufferedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
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


class DropboxStorageBackend(DirectoryCachedStorageMixin, StorageBackend):
    """
    Dropbox storage supporting both read and write operations.
    """

    SCHEMA = Schema({
        "title": "Dropbox storage manifest",
        "type": "object",
        "required": ["token"],
        "properties": {
            "token": {
                "type": ["string"],
                "description": "Dropbox OAuth 2.0 access token. You can generate it in Dropbox App "
                               "Console.",
            },
        }
    })
    TYPE = 'dropbox'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        dropbox_access_token = self.params['token']
        self.client = DropboxClient(dropbox_access_token)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(
                ['--token'], metavar='ACCESS_TOKEN', required=True,
                help='Dropbox OAuth 2.0 access token. You can generate it in Dropbox App Console.')
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'token': data['token'],
        }

    @staticmethod
    def _get_attr_from_metadata(metadata: Metadata) -> DropboxFileAttr:
        if isinstance(metadata, FileMetadata):
            attr = DropboxFileAttr.from_file_metadata(metadata)
        else:
            assert isinstance(metadata, FolderMetadata)
            attr = DropboxFileAttr.from_folder_metadata(metadata)
        return attr

    def mount(self) -> None:
        self.client.connect()

    def unmount(self) -> None:
        self.client.disconnect()

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, DropboxFileAttr]]:
        for metadata in self.client.list_folder(path):
            attr = self._get_attr_from_metadata(metadata)
            yield metadata.name, attr

    def open(self, path: PurePosixPath, _flags: int) -> DropboxFile:
        metadata = self.client.get_metadata(path)
        attr = self._get_attr_from_metadata(metadata)
        return DropboxFile(self.client, path, attr, self.clear_cache)

    def create(self, path: PurePosixPath, _flags: int, _mode: int = 0o666) -> DropboxFile:
        metadata = self.client.upload_empty_file(path)
        attr = DropboxFileAttr.from_file_metadata(metadata)
        self.clear_cache()
        return DropboxFile(self.client, path, attr, self.clear_cache)

    def unlink(self, path: PurePosixPath) -> None:
        self.client.unlink(path)
        self.clear_cache()

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777) -> None:
        self.client.mkdir(path)
        self.clear_cache()

    def rmdir(self, path: PurePosixPath) -> None:
        self.client.rmdir(path)
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
            full_file_content = self.client.get_file_content(path)
            truncated_content = full_file_content[:length]
        self.client.upload_file(truncated_content, path)
        self.clear_cache()

    def get_file_token(self, path: PurePosixPath) -> Optional[str]:
        if path == PurePosixPath('.'):
            return None  # DirectoryCachedStorageMixin returns Attr.dir() for '.'
        attr = self.getattr(path)
        assert isinstance(attr, DropboxFileAttr)
        return attr.content_hash
