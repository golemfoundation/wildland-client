# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Dropbox client wrapping and exposing Dropbox API calls that are relevant for the Dropbox plugin
"""

import errno

from pathlib import PurePosixPath
from typing import Callable, List, Optional

from dropbox import Dropbox
from dropbox.exceptions import ApiError, AuthError, BadInputError
from dropbox.files import (
    CommitInfo,
    DeleteResult,
    FileMetadata,
    FolderMetadata,
    Metadata,
    UploadSessionCursor,
    WriteMode
)

from wildland.log import get_logger

logger = get_logger('dropbox-client')


class DropboxClient:
    """
    Dropbox client exposing relevant Dropbox API for Dropbox plugin.
    """

    def __init__(self, token=None, app_key=None, refresh_token=None):
        self.token = token
        self.app_key = app_key
        self.refresh_token = refresh_token
        self._dropbox_connection: Optional[Dropbox] = None

        if not token and not app_key and not refresh_token:
            raise ValueError("Please provide access token or App Key with refresh token")

    def connect(self) -> None:
        """
        Create an object that routes all the Dropbox API requests to the Dropbox API endpoint.
        """
        if self.token:
            self._dropbox_connection = Dropbox(oauth2_access_token=self.token)
        else:
            self._dropbox_connection = Dropbox(
                oauth2_refresh_token=self.refresh_token,
                app_key=self.app_key
            )

    def disconnect(self) -> None:
        """
        Gracefully terminate the connection with Dropbox endpoint and free related resources.
        """
        if self.connection:
            self.connection.close()
        self._dropbox_connection = None

    @property
    def connection(self):
        """
        Return Dropbox connection and refresh it if necessary
        """
        if self._dropbox_connection:
            if self.refresh_token:
                self._dropbox_connection.check_and_refresh_access_token()
        else:
            self.connect()
            assert self._dropbox_connection
        return self._dropbox_connection

    def list_folder(self, path: PurePosixPath) -> List[Metadata]:
        """
        List content of the given directory.
        """
        try:
            path_str = self._convert_to_dropbox_path(path)
            listing = self.connection.files_list_folder(path_str)
            entries: list[Metadata] = listing.entries
            while listing.has_more:
                listing = self.connection.files_list_folder_continue(listing.cursor)
                entries.extend(listing.entries)
            return entries
        except (AuthError, BadInputError) as e:
            raise PermissionError(errno.EACCES,
                                  f'No permissions to list directory [{path_str}]') from e

    def get_file_content(self, path: PurePosixPath) -> bytes:
        """
        Get content of the given file.
        """
        path_str = self._convert_to_dropbox_path(path)
        try:
            _, response = self.connection.files_download(path_str)
        except (AuthError, BadInputError) as e:
            raise PermissionError(errno.EACCES, f'No permissions to read files [{path_str}]') from e
        return response.content

    def rmdir(self, path: PurePosixPath) -> DeleteResult:
        """
        Remove given directory.
        """
        return self.unlink(path)

    def unlink(self, path: PurePosixPath) -> DeleteResult:
        """
        Remove given file.
        """
        path_str = self._convert_to_dropbox_path(path)
        return self._unlink(path_str)

    def _unlink(self, path: str):
        try:
            return self.connection.files_delete_v2(path)
        except (AuthError, BadInputError) as e:
            raise PermissionError(
                errno.EACCES,
                f'No permissions to remove files and directories [{path}]') from e

    def mkdir(self, path: PurePosixPath) -> FolderMetadata:
        """
        Create given directory. In case of a conflict don't allow Dropbox to autorename.
        """
        path_str = self._convert_to_dropbox_path(path)
        try:
            return self.connection.files_create_folder_v2(path_str, autorename=False)
        except (AuthError, BadInputError) as e:
            raise PermissionError(errno.EACCES,
                                  f'No permissions to create directories [{path_str}]') from e

    def rename(self, move_from_path: PurePosixPath, move_to_path: PurePosixPath,
            overwrite: bool=True) -> Metadata:
        """
        Rename given file or folder.
        """
        move_from_str = self._convert_to_dropbox_path(move_from_path)
        move_to_str = self._convert_to_dropbox_path(move_to_path)
        destination_exists_handler = self._rename_with_overwrite if overwrite else None
        return self._rename(move_from_str, move_to_str, destination_exists_handler)

    def _rename(self, move_from_path: str, move_to_path: str,
            destination_exists_handler: Optional[Callable[[str, str, ApiError], Metadata]]=None) \
                -> Metadata:
        """
        Rename given file or folder.

        Dropbox API doesn't support overwriting the file when moving, thus we need to manually
        remove ``move_to_path`` if it already exists and it is not a directory.

        Alternative implementation could check if ``move_to_path`` file exists before calling API's
        ``move`` operation instead of handling API error that indicates a conflict. It would require
        more network traffic (unless cached) to check if a file exists. It could also introduce a
        race condition.
        """

        logger.debug('Renaming [%s] to [%s]', move_from_path, move_to_path)

        try:
            return self.connection.files_move(move_from_path, move_to_path)
        except (AuthError, BadInputError) as e:
            raise PermissionError(
                errno.EACCES,
                f'No permissions to move [{move_from_path}] to [{move_to_path}]') from e
        except ApiError as e:
            if destination_exists_handler and self._is_destination_exists_error(e):
                return destination_exists_handler(move_from_path, move_to_path, e)
            raise e

    def _rename_with_overwrite(self, move_from_path: str, move_to_path: str,
            original_overwrite_reason: ApiError, safe_rename: bool=True) -> Metadata:

        logger.debug('Rename destination [%s] already exist - removing it', move_to_path)

        if safe_rename:
            rename_handler = self._rename_with_overwrite_safely
        else:
            rename_handler = self._rename_with_overwrite_unsafely

        return rename_handler(move_from_path, move_to_path, original_overwrite_reason)

    def _rename_with_overwrite_safely(self, move_from_path: str, move_to_path: str,
            original_overwrite_reason: ApiError) -> Metadata:
        """
        This is safer rename implementation. Instead of removing ``move_to_path`` file before
        renaming ``move_from_path``, it temporarily renames ``move_to_path`` file to be able to
        recover it in case final rename fails (as opposed to unsafe rename implementation which
        deletes ``move_to_path`` before rename).
        """
        tmp_file_path = move_to_path + '.rename_tmp'

        try:
            self._rename(move_to_path, tmp_file_path)
        except (PermissionError, ApiError):
            logger.error('Failed to rename [%s] to [%s]', move_to_path, tmp_file_path,
                exc_info=True)
            raise ApiError from original_overwrite_reason

        try:
            metadata = self._rename(move_from_path, move_to_path)
        except (PermissionError, ApiError):
            # if below _rename() fails, we will leave destination filename with a temporary suffix
            self._rename(tmp_file_path, move_to_path)
            logger.error('Failed to rename [%s] to [%s]', move_to_path, tmp_file_path,
                exc_info=True)
            raise ApiError from original_overwrite_reason

        self._unlink(tmp_file_path)

        return metadata

    def _rename_with_overwrite_unsafely(self, move_from_path: str, move_to_path: str,
            original_overwrite_reason: ApiError) -> Metadata:
        """
        This is unsafe rename version. If ``_unlink()`` is successful but ``rename()`` is not, we
        effectively only delete destination file.
        """
        try:
            self._unlink(move_to_path)
            return self._rename(move_from_path, move_to_path)
        except:
            logger.error('Failed to remove [%s] and rename [%s] to [%s]', move_to_path,
                move_from_path, move_to_path, exc_info=True)
            raise ApiError from original_overwrite_reason

    def get_metadata(self, path: PurePosixPath) -> Metadata:
        """
        Get file/directory metadata. This is kind of a superset of getattr().
        """
        path_str = self._convert_to_dropbox_path(path)
        return self.connection.files_get_metadata(path_str)

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
        except (AuthError, BadInputError) as e:
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

    @staticmethod
    def _is_destination_exists_error(api_err: ApiError) -> bool:
        if api_err.error.is_to():
            to_err = api_err.error.get_to()
            return to_err.is_conflict()
        return False
