# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                 Maja Kostacinska <maja@wildland.io>
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
Initial implementation of the git backend, used to expose git repositories
as wildland containers.
"""

# pylint: disable=no-member
import stat
from pathlib import PurePosixPath
from typing import List, Union, Optional, Callable, Iterable, Tuple

import uuid
import click

from git import Blob, Tree
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.storage_backends.buffered import FullBufferedFile
from wildland.manifest.schema import Schema
from wildland.log import get_logger
from .git_client import GitClient

logger = get_logger('git-backend')


class GitFile(FullBufferedFile):
    """
    Representation of a git file
    """

    def __init__(self,
                 client: GitClient,
                 path_parts: List[str],
                 attr: Attr, clear_cache_callback: Optional[Callable] = None):
        super().__init__(attr, clear_cache_callback)
        self.client = client
        self.path_parts = path_parts
        self.attr = attr

    def read_full(self) -> bytes:
        data = self.client.get_file_content(self.path_parts)
        return data

    def write_full(self, data: bytes) -> int:
        pass


class GitStorageBackend(DirectoryCachedStorageMixin, StorageBackend):
    """
    A read-only backend for exposing git repositories as containers.
    """

    SCHEMA = Schema({
        "title": "Git storage manifest",
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "type": ["string"],
                "description": "Git URL leading to the chosen repository",
            },
            "username": {
                "type": ["string"],
                "description": "The git username used for authorization \
                                purposes"
            },
            "password": {
                "type": ["string"],
                "description": "The git password/token used for authorization \
                                when cloning the chosen repository."
            },
        }
    })
    TYPE = 'git'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        repo_url = self.params['url']
        location = f'/tmp/git_repo/{self.params["owner"]}/{self._directory_uuid()}'
        username = self.params.get('username')
        password = self.params.get('password')
        self.client = GitClient(repo_url, location, username, password)
        self.read_only = True

    def _directory_uuid(self) -> str:
        """
        Generates an uuid necessary in order to clone the repository to an unique
        directory
        """
        return str(uuid.uuid3(uuid.UUID(self.backend_id), str(self.params['url'])))

    @classmethod
    def cli_options(cls):
        opts = super(GitStorageBackend, cls).cli_options()
        opts.extend([
            click.Option(
                ['--url'], metavar='URL', required=True,
                help='Git url leading to the repo',
            ),
            click.Option(
                ['--username'], required=False,
                help='The git username - used for authorization purposes'
            ),
            click.Option(
                ['--password'], required=False,
                help='The git password/personal access token. Necessary for authorization purposes'
            )
        ])
        return opts

    @classmethod
    def cli_create(cls, data):
        result = super(GitStorageBackend, cls).cli_create(data)
        result.update({
            'url': data['url'],
            'username': data['username'],
            'password': data['password']
        })
        return result

    def mount(self) -> None:
        self.client.connect()

    def unmount(self) -> None:
        self.client.disconnect()

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, Attr]]:
        for obj in self.client.list_folder(self.convert_to_subparts(path)):
            attr = self._get_attr_from_object(obj)
            yield obj.name, attr

    def open(self, path: PurePosixPath, _flags: int) -> GitFile:
        obj = self.client.get_object(self.convert_to_subparts(path))
        attr = self._get_attr_from_object(obj)
        return GitFile(self.client, self.convert_to_subparts(path), attr, None)

    def _get_attr_from_object(self, obj: Union[Blob, Tree]):
        if isinstance(obj, Blob):
            attr = Attr(mode=stat.S_IFREG | 0o644,
                        size=obj.size,
                        timestamp=self.client.get_commit_timestamp())
        else:
            assert isinstance(obj, Tree)
            attr = Attr(mode=stat.S_IFDIR | 0o755)

        return attr

    @classmethod
    def convert_to_subparts(cls, path: PurePosixPath):
        """
        Converts the given path to a list of it's subparts, for example:
        - /path/to/something
        Will be converted into the following list:
        - ['path', 'to', 'something']
        """
        to_return = path.parts

        if len(to_return) > 0 and to_return[0] == '/':
            to_return = to_return[1:]

        return to_return
