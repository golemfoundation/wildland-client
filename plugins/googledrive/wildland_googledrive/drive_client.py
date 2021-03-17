# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
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

"""
Google Drive client wrapping and exposing Google Drive API calls
that are relevant for the Google Drive plugin
"""
import errno
from io import BytesIO
from pathlib import PurePosixPath
from typing import Union

import httplib2shim

from googleapiclient.discovery import build, Resource
from googleapiclient.errors import Error
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from treelib import Node

# issue: ssl.SSLError: [SSL: DECRYPTION_FAILED_OR_BAD_RECORD_MAC] decryption
# failed or bad record mac (_ssl.c:2622)
#
# see: https://github.com/GoogleCloudPlatform/httplib2shim
httplib2shim.patch()

# for mimetypes, see: https://developers.google.com/drive/api/v3/mime-types
FOLDER_MIMETYPE = "application/vnd.google-apps.folder"


class DriveClient:
    """
    Google Drive client exposing relevant Google Drive API for Google Drive plugin.
    """

    def __init__(self, credentials, cache_tree):
        self.drive_api: Resource
        self.cache_tree = cache_tree
        self.credentials = Credentials(
            token=credentials["token"],
            refresh_token=credentials["refresh_token"],
            token_uri=credentials["token_uri"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            scopes=credentials["scopes"],
        )

    def connect(self) -> Resource:
        """
        Creates Drive API instance, reads root folder metadata of connected Drive Storage
        """
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())

        drive = build("drive", "v3", credentials=self.credentials)
        # pylint: disable=maybe-no-member
        self.drive_api = drive.files()
        root_folder = self.drive_api.get(fileId="root", fields="*").execute()
        return root_folder

    def disconnect(self) -> None:
        """
        Gracefully terminate the connection and frees allocated resources, including cache tree
        """
        assert self.drive_api
        self.drive_api.close()
        self.drive_api = None
        self.cache_tree.remove_node(self.cache_tree.root)

    def list_folder(self, path: PurePosixPath) -> list:
        """
        List content of the given directory.
        """
        try:
            parent_id = self._get_id_from_path(path)
            return self._retrieve_entries("'{}' in parents".format(parent_id))
        except (Error) as e:
            raise e

    def get_file_content(self, path: PurePosixPath) -> bytes:
        """
        Get content of the given file.
        """
        file_id = self._get_id_from_path(path)
        try:
            response = self.drive_api.get_media(fileId=file_id).execute()
        except Error as e:
            raise e
        return response

    def unlink(self, path: PurePosixPath) -> None:
        """
        Remove given file.
        """
        self._remove_entry(path)

    def mkdir(self, path: PurePosixPath) -> None:
        """
        Create given directory.
        """
        parent_id = self.cache_tree.root
        for item in path.parts:
            node_item = self._retrieve_from_cache_tree(item, parent_id)

            if not node_item:
                folder_id = self._retrieve_if_exist(item, parent_id)
            else:
                folder_id = node_item.identifier

            if folder_id:
                parent_id = folder_id
                continue

            file_metadata = {
                "name": item,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }

            try:
                parent_id = self.drive_api.create(
                    body=file_metadata, fields="id"
                ).execute()
            except PermissionError as e:
                raise PermissionError(
                    errno.EACCES, f"No permissions to create directories [{path}]"
                ) from e

    def rmdir(self, path: PurePosixPath) -> None:
        """
        Removes given directory.
        """
        self._remove_entry(path)

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath) -> None:
        """
        Renames and/or moves given entries from their sources to the provided destination
        TODO needs improvement
        """
        src_cursor_id = self.cache_tree.root
        dst_cursor_id = self.cache_tree.root
        for item in move_from.parts:
            node_item = self._retrieve_from_cache_tree(item, src_cursor_id)

            if not node_item:
                entry_id = self._retrieve_if_exist(item, src_cursor_id)
            else:
                entry_id = node_item.identifier

            if not entry_id:
                raise Exception("Source path is not exist: {}".format(move_from))
            src_cursor_id = entry_id

        # if paths are the same just update the name
        if move_from.parent == move_to.parent:
            # TODO check if there are other files with same name
            body = {"name": move_to.name}
            self.drive_api.update(
                fileId=src_cursor_id,
                body=body,
                fields="*",
            ).execute()
            self.cache_tree.update_node(src_cursor_id, tag=move_to.name)
            return

        src_entry = self.drive_api.get(
            fileId=src_cursor_id, fields="mimeType, parents"
        ).execute()
        # multi parents are not supported, we may need check for true parent id
        previous_parents = ",".join(src_entry.get("parents"))

        for item in move_to.parts:
            node_item = self._retrieve_from_cache_tree(item, dst_cursor_id)

            if not node_item:
                entry_id = self._retrieve_if_exist(item, dst_cursor_id)
            else:
                entry_id = node_item.identifier

            if not entry_id and item != move_to.name:
                raise Exception("Destination path is not exist: {}".format(move_to))
            if entry_id:
                dst_cursor_id = entry_id

        dst_entry = self.drive_api.get(
            fileId=dst_cursor_id, fields="id, name, mimeType, parents"
        ).execute()

        dst_id = dst_entry.get("id")
        dst_name = dst_entry.get("name")
        dst_parents = dst_entry.get("parents")
        dst_mimeType = dst_entry.get("mimeType")
        src_mimeType = src_entry.get("mimeType")

        # mv file file     - new parent is parent of dest file
        # mv folder folder - new parent is given folder if exist
        # + if not one level above is the parent
        new_parents = (
            ",".join(dst_parents)
            if FOLDER_MIMETYPE not in (dst_mimeType, src_mimeType)
            else dst_id
        )

        # mv file file     - destination file name is new name
        # mv folder folder - destination folder name is new name if not exist
        # + if it is just move src into and keep the old name
        body = {
            "name": move_to.name
            if dst_mimeType != FOLDER_MIMETYPE
            or (dst_mimeType == FOLDER_MIMETYPE and dst_name != move_to.name)
            else move_from.name
        }

        self.drive_api.update(
            fileId=src_cursor_id,
            addParents=new_parents,
            removeParents=previous_parents,
            body=body,
            fields="*",
        ).execute()
        self.cache_tree.move_node(src_cursor_id, new_parents)

    def get_metadata(self, path: PurePosixPath) -> Resource:
        """
        Get metadata of Google Drive file/directory.
        """
        file_id = self._get_id_from_path(path)
        return self.drive_api.get(fileId=file_id, fields="*").execute()

    def upload_file(self, data: bytes, path: PurePosixPath) -> Resource:
        """
        Save given bytes to the given Google Drive file.
        """
        return self._upload_file(data, path)

    def upload_empty_file(self, path: PurePosixPath) -> Resource:
        """
        Create an empty file on Google Drive Storage
        """
        return self._upload_file(bytes(), path, new_file=True)

    def _retrieve_entries(
        self, query: str = "", fields: str = "nextPageToken, files"
    ) -> list:
        """
        Retrieve paginated entries with given query.
        """

        # always exclude trashed files and all sort of google-apps file types,
        # but keep Google Drive folder mimeType
        #
        # for Google specific mimeTypes, see: https://developers.google.com/drive/api/v3/mime-types
        # for query structure;
        # see: https://developers.google.com/drive/api/v3/ref-search-terms
        # see: https://developers.google.com/drive/api/v3/search-files

        query += (
            " and trashed=false and (not mimeType contains 'application/vnd.google-apps'"
            "or mimeType='application/vnd.google-apps.folder')"
        )

        listing = self.drive_api.list(q=query, pageSize=200, fields=fields).execute()
        entries: list = listing.get("files", [])
        next_token = listing.get("nextPageToken")
        while next_token:
            listing = self.drive_api.list(
                q=query, pageSize=200, fields=fields, pageToken=next_token
            ).execute()
            next_token = listing.get("nextPageToken", None)
            next_entries = listing.get("files", [])
            entries.extend(next_entries)
        return entries

    def _get_id_from_path(self, path: PurePosixPath) -> str:
        """
        Retrieves the id of Google Drive entries from the paths that comes from FUSE calls.
        """
        parent_id = self.cache_tree.root

        if path in (PurePosixPath("/"), PurePosixPath(".")):
            return parent_id

        for path_item in path.parts:
            if path_item in ("/", "."):
                continue

            if not parent_id:
                raise Exception("Parent ID not found")

            node_item = self._retrieve_from_cache_tree(path_item, parent_id)

            if node_item:
                parent_id = node_item.identifier
                continue

            query = "'{}' in parents and name='{}'".format(parent_id, path_item)
            entries = self._retrieve_entries(query)

            if not entries:
                raise Exception("Invalid path")

            parent_id = entries[0].get("id", None)

        return parent_id

    def _retrieve_if_exist(self, name, parent_id) -> Union[bool, str]:
        """
        Retrieves the id of given entry name, if exist under given parent_id
        """
        try:
            query = "'{}' in parents and name='{}'".format(parent_id, name)
            entries = self._retrieve_entries(query)
            if not entries:
                return False
            return entries[0].get("id", None)
        except Exception:
            return False

    def _retrieve_from_cache_tree(self, item, parent_id) -> Node:
        """
        Checks if cache three has given item under the given parent_id
        """
        node_item = None
        try:
            node_item = next(
                self.cache_tree.filter_nodes(
                    lambda node, tag=item: (
                        node.tag == tag and node.bpointer == parent_id
                    )
                )
            )
        except StopIteration:
            pass
        return node_item

    def _upload_file(
        self, data: bytes, path: PurePosixPath, new_file: bool = False
    ) -> Resource:
        """
        Creates/updates files on Google Drive with given content
        """
        cursor_id = self.cache_tree.root

        for item in path.parts:
            if new_file and item == path.name:
                break

            node_item = self._retrieve_from_cache_tree(item, cursor_id)

            if not node_item:
                entry_id = self._retrieve_if_exist(item, cursor_id)
            else:
                entry_id = node_item.identifier

            if entry_id:
                cursor_id = entry_id

        media_body = MediaIoBaseUpload(
            BytesIO(data),
            mimetype="application/octet-stream",
            chunksize=1024 * 1024,
            resumable=False,
        )
        if new_file:
            file_metadata = {
                "name": path.name,
                "mimeType": "application/octet-stream",
                "parents": [cursor_id],
            }
            return self.drive_api.create(
                body=file_metadata, media_body=media_body, fields="*"
            ).execute()
        return self.drive_api.update(
            fileId=cursor_id, media_body=media_body, fields="*"
        ).execute()

    def _remove_entry(self, path: PurePosixPath) -> None:
        """
        Removes given entry both from Google Drive and cache tree
        """
        parent_id = self.cache_tree.root
        for item in path.parts:
            node_item = self._retrieve_from_cache_tree(item, parent_id)

            if not node_item:
                folder_id = self._retrieve_if_exist(item, parent_id)
            else:
                folder_id = node_item.identifier

            if not folder_id:
                raise Exception("Given path not exist: {}".format(path))

            parent_id = folder_id

        try:
            self.drive_api.delete(fileId=parent_id).execute()
            self.cache_tree.remove_node(parent_id)
        except PermissionError as e:
            raise PermissionError(
                errno.EACCES, f"No permissions to remove entry [{path}]"
            ) from e
