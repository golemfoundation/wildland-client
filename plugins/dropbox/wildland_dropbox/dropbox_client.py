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
Dropbox client wrapping and exposing Dropbox API calls that are relevant for the Dropbox plugin
"""

import errno
from pathlib import PurePosixPath

from dropbox import Dropbox
from dropbox.exceptions import AuthError, BadInputError
from dropbox.files import (
    CommitInfo,
    DeleteResult,
    FileMetadata,
    FolderMetadata,
    Metadata,
    UploadSessionCursor,
    WriteMode
)


class DropboxClient:
    """
    Dropbox client exposing relevant Dropbox API for Dropbox plugin.
    """

    def __init__(self, access_token):
        self.access_token = access_token
        self.connection = None

    def connect(self) -> None:
        """
        Create an object that routes all the Dropbox API requests to the Dropbox API endpoint.
        """
        self.connection = Dropbox(self.access_token)

    def disconnect(self) -> None:
        """
        Gracefully terminate the connection with Dropbox endpoint and free related resources.
        """
        assert self.connection
        self.connection.close()
        self.connection = None

    def list_folder(self, path: PurePosixPath) -> list[Metadata]:
        """
        List content of the given directory.
        """
        try:
            path = self._convert_to_dropbox_path(path)
            listing = self.connection.files_list_folder(path)
            entries: list[Metadata] = listing.entries
            while listing.has_more:
                listing = self.connection.files_list_folder_continue(listing.cursor)
                entries.extend(listing.entries)
            return entries
        except (AuthError, BadInputError) as e:
            raise PermissionError(errno.EACCES, f'No permissions to list directory [{path}]') from e

    def get_file_content(self, path: PurePosixPath) -> bytes:
        """
        Get content of the given file.
        """
        path = self._convert_to_dropbox_path(path)
        try:
            _, response = self.connection.files_download(path)
        except BadInputError as e:
            raise PermissionError(errno.EACCES, f'No permissions to read files [{path}]') from e
        return response.content

    def unlink(self, path: PurePosixPath) -> DeleteResult:
        """
        Remove given file.
        """
        path = self._convert_to_dropbox_path(path)
        try:
            return self.connection.files_delete_v2(path)
        except BadInputError as e:
            raise PermissionError(
                errno.EACCES,
                f'No permissions to remove files and directories [{path}]') from e

    def mkdir(self, path: PurePosixPath) -> FolderMetadata:
        """
        Create given directory. In case of a conflict don't allow Dropbox to autorename.
        """
        path = self._convert_to_dropbox_path(path)
        try:
            return self.connection.files_create_folder_v2(path, autorename=False)
        except BadInputError as e:
            raise PermissionError(errno.EACCES,
                                  f'No permissions to create directories [{path}]') from e

    def rmdir(self, path: PurePosixPath) -> DeleteResult:
        """
        Remove given directory.
        """
        return self.unlink(path)

    def get_metadata(self, path: PurePosixPath) -> Metadata:
        """
        Get file/directory metadata. This is kind of a superset of getattr().
        """
        path = self._convert_to_dropbox_path(path)
        return self.connection.files_get_metadata(path)

    def upload_file(self, data: bytes, path: PurePosixPath) -> FileMetadata:
        """
        Save given bytes to the given Dropbox file.

        Dropbox exposes different API for uploading files larger than 150 MB. If you try to create
        a file with size over 150 MB you will get an empty file being created. Files smaller than
        the given limit can be uploaded to Dropbox using any of the two APIs.
        """
        max_bytes_upload_size = 140000000
        dropbox_path = self._convert_to_dropbox_path(path)
        try:
            if len(data) > max_bytes_upload_size:
                self._upload_large_file(data, dropbox_path)
            return self._upload_small_file(data, dropbox_path)
        except BadInputError as e:
            raise PermissionError(errno.EACCES, f'No permissions to write file [{path}]') from e

    def _upload_small_file(self, data: bytes, path: str) -> FileMetadata:
        return self.connection.files_upload(data, path, mode=WriteMode.overwrite)

    def _upload_large_file(self, data: bytes, path: str) -> FileMetadata:
        CHUNK_SIZE = 10 * 1024 * 1024  # 10 MiB
        offset = CHUNK_SIZE
        file_size = len(data)
        upload_session = self.connection.files_upload_session_start(
            data[:offset],
            close=offset>=file_size)
        cursor = UploadSessionCursor(session_id=upload_session.session_id, offset=offset)
        commit = CommitInfo(path=path, mode=WriteMode.overwrite)

        while offset < file_size:
            if file_size - offset <= CHUNK_SIZE:
                self.connection.files_upload_session_finish(
                    data[offset:offset + CHUNK_SIZE],
                    cursor,
                    commit)
            else:
                self.connection.files_upload_session_append_v2(
                    data[offset:offset + CHUNK_SIZE],
                    cursor,
                    close=False)
            offset += CHUNK_SIZE
            cursor.offset = offset

    def upload_empty_file(self, path: PurePosixPath) -> FileMetadata:
        """
        Create empty file. This is essentially what `touch` command does.
        """
        return self.upload_file(bytes(), path)

    @staticmethod
    def _convert_to_dropbox_path(path: PurePosixPath) -> str:
        """
        Converts path that comes from FUSE call to the path that is Dropbox API friendly.
        In particular, Dropbox uses empty string instead of '.'.
        """
        return '' if path == PurePosixPath('.') else str('/' / path)
