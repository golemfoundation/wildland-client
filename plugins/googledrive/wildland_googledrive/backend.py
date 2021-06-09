# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Muhammed Tanrikulu <muhammed@wildland.io>
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Google Drive storage backend
"""
import errno
import logging
import json
import stat

from datetime import datetime
from pathlib import PosixPath, PurePosixPath
from typing import cast, Callable, Iterable, Optional, Tuple

import click

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError
from treelib import Tree
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import File, FullBufferedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.storage_backends.file_subcontainers import FileSubcontainersMixin
from wildland.manifest.schema import Schema
from .drive_client import DriveClient

# for scopes, see: https://developers.google.com/drive/api/v3/about-auth
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
# for mimetypes, see: https://developers.google.com/drive/api/v3/mime-types
FOLDER_MIMETYPE = "application/vnd.google-apps.folder"


class DriveFileAttr(Attr):
    """
    Attributes of a Google Drive file.
    """

    def __init__(self, size: int, timestamp: int, head_revision_id: str):
        self.mode = stat.S_IFREG | 0o644
        self.size = size
        self.timestamp = timestamp
        self.head_revision_id = head_revision_id

    @classmethod
    def from_file_metadata(cls, metadata):
        """
        Convert given file's metadata to attribute object.
        """
        latest_modification = metadata["modifiedTime"]
        modification_date = datetime.strptime(
            latest_modification, "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        size = int(metadata.get("size", 0))
        timestamp = int(modification_date.timestamp())
        head_revision_id = metadata.get("headRevisionId", None)
        return cls(
            size,
            timestamp,
            head_revision_id,
        )


class DriveFile(FullBufferedFile):
    """
    Representation of a Google Drive file.
    """

    def __init__(
        self,
        client: DriveClient,
        path: PurePosixPath,
        attr: Attr,
        clear_cache_callback: Optional[Callable] = None,
    ):
        super().__init__(attr, clear_cache_callback)
        self.client = client
        self.path = path
        self.attr = attr

    def read_full(self) -> bytes:
        return self.client.get_file_content(self.path)

    def write_full(self, data: bytes) -> int:
        self.client.upload_file(data, self.path)
        return len(data)


class DriveStorageBackend(
    FileSubcontainersMixin, DirectoryCachedStorageMixin, StorageBackend
):
    """
    Google Drive storage supporting both read and write operations.
    """

    SCHEMA = Schema(
        {
            "title": "Google Drive storage manifest",
            "type": "object",
            "required": ["credentials"],
            "properties": {
                "location": {
                    "$ref": "/schemas/types.json#abs-path",
                    "description": "Absolute POSIX path acting as a root directory in user's google drive",  # pylint: disable=line-too-long
                },
                "credentials": {
                    "type": "object",
                    "required": [
                        "token",
                        "refresh_token",
                        "token_uri",
                        "client_id",
                        "client_secret",
                        "scopes",
                    ],
                },
                "manifest-pattern": {
                    "oneOf": [
                        {"$ref": "/schemas/types.json#pattern-glob"},
                        {"$ref": "/schemas/types.json#pattern-list"},
                    ]
                },
            },
        }
    )
    TYPE = "googledrive"
    LOCATION_PARAM = "location"

    def __init__(self, **kwds):
        super().__init__(**kwds)
        drive_access_credentials = self.params.get("credentials")
        self.cache_tree = Tree()
        self.client = DriveClient(drive_access_credentials, self.cache_tree)
        self.root = PosixPath(self.params.get("location", "/")).resolve()
        self.logger = logging.getLogger("Google Drive Logger")

    @classmethod
    def cli_options(cls):
        opts = super(DriveStorageBackend, cls).cli_options()
        opts.extend(
            [
                click.Option(
                    ["--location"],
                    metavar="PATH",
                    required=False,
                    default="/",
                    help="Absolute path to root directory in your Google Drive account.",
                ),
                click.Option(
                    ["--credentials"],
                    metavar="CREDENTIALS",
                    required=True,
                    help="Google Drive Client Configuration Object",
                ),
                click.Option(
                    ["--skip-interaction"],
                    default=False,
                    is_flag=True,
                    required=False,
                    help="Pass pre-generated refresh token as credential"
                    "and pass this flag to skip interaction",
                ),
            ]
        )
        return opts

    @classmethod
    def cli_create(cls, data):
        credentials = None
        client_config = json.loads(data["credentials"])
        if data["skip_interaction"]:
            credentials = client_config
        else:
            flow = InstalledAppFlow.from_client_config(client_config, DRIVE_SCOPES)
            credentials = flow.run_console()
            credentials = json.loads(credentials.to_json())

        result = super(DriveStorageBackend, cls).cli_create(data)
        result.update({"location": data["location"], "credentials": credentials})
        return result

    @staticmethod
    def _get_attr_from_metadata(metadata) -> Attr:
        if metadata["mimeType"] == FOLDER_MIMETYPE:
            latest_modification = metadata["modifiedTime"]
            modification_date = datetime.strptime(
                latest_modification, "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            timestamp = int(modification_date.timestamp())
            return Attr.dir(timestamp=timestamp)
        return DriveFileAttr.from_file_metadata(metadata)

    def mount(self) -> None:
        root_folder = self.client.connect(self.root)
        self.cache_tree.create_node(
            root_folder["name"], root_folder["id"], data=FOLDER_MIMETYPE
        )

    def unmount(self) -> None:
        self.client.disconnect()

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, Attr]]:
        for metadata in self.client.list_folder(path):
            attr = self._get_attr_from_metadata(metadata)
            self.add_into_tree(metadata)
            yield metadata.get("name"), attr

    def open(self, path: PurePosixPath, _flags: int) -> File:
        try:
            metadata = self.client.get_metadata(path)
            attr = self._get_attr_from_metadata(metadata)
            return DriveFile(self.client, path, attr, self.clear_cache)
        except HttpError as e:
            if e.resp.status == "404":
                raise FileNotFoundError(errno.ENOENT, str(path)) from e
            if e.resp.status == "403":
                raise PermissionError(
                    errno.EACCES, f"No permissions to read file [{path}]"
                ) from e
            raise e

    def create(self, path: PurePosixPath, _flags: int, _mode: int = 0o666) -> File:
        metadata = self.client.upload_empty_file(path)
        attr = DriveFileAttr.from_file_metadata(metadata)
        self.clear_cache()
        return DriveFile(self.client, path, attr, self.clear_cache)

    def chmod(self, path: PurePosixPath, mode: int):
        self.logger.debug("chmod > mode: %d path: %s", mode, path)

    def chown(self, path: PurePosixPath, uid: int, gid: int):
        self.logger.debug("chown > uid: %d gid: %d path: %s", uid, gid, path)

    def utimens(self, path: PurePosixPath, atime, mtime) -> None:
        self.logger.debug("utimens > path: %s", path)

    def unlink(self, path: PurePosixPath) -> None:
        self.client.unlink(path)
        self.clear_cache()

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777) -> None:
        self.client.mkdir(path)
        self.clear_cache()

    def rmdir(self, path: PurePosixPath) -> None:
        self.client.rmdir(path)
        self.clear_cache()

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        self.client.rename(move_from, move_to)
        self.clear_cache()

    def truncate(self, path: PurePosixPath, length: int) -> None:
        """
        Truncate given file.
        """
        if length == 0:
            truncated_content = bytes()
        else:
            full_file_content = self.client.get_file_content(path)
            truncated_content = full_file_content[:length]
        self.client.upload_file(truncated_content, path)
        self.clear_cache()

    def get_file_token(self, path: PurePosixPath) -> Optional[str]:
        attr: DriveFileAttr = cast(DriveFileAttr, self.getattr(path))
        return str(int(attr.head_revision_id, 16))

    def add_into_tree(self, metadata):
        """
        Map current dir file/folder items into cache tree
        """
        current_node = self.cache_tree.get_node(metadata["id"])
        try:
            if not current_node:
                self.cache_tree.create_node(
                    metadata["name"],
                    metadata["id"],
                    parent=metadata["parents"][0],
                    data=metadata["mimeType"],
                )
        except Exception as error:
            raise Exception(f"Cache tree error: {error}") from error
