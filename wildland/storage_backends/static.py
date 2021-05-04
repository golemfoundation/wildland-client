# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>,
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

"""Static storage, publishes files from storage parameters"""

from functools import partial
from typing import Optional, Dict, Any, Mapping, Union
import click

from .base import StorageBackend
from .generated import GeneratedStorageMixin, StaticFileEntry, FuncDirEntry, DirEntry
from ..manifest.schema import Schema


class StaticStorageBackend(GeneratedStorageMixin, StorageBackend):
    """
    Read-only storage backend containing files listed in the storage manifest directly.
    """
    SCHEMA = Schema({
        "type": "object",
        "required": ["content"],
        "properties": {
            "content": {
                "type": "object",
                "description": "Content of the filesystem - mapping from file names to their"
                               "content. The content can be another mapping - it will be presented"
                               "as a directory then."
            },
        }
    })
    TYPE = 'static'

    def __init__(self, *, params: Optional[Dict[str, Any]] = None, **kwds):
        super().__init__(params=params, **kwds)
        self.read_only = True
        if params:
            self.content = params['content']
        else:
            self.content = {}

    def _dir(self, content):
        for name, data in content.items():
            if isinstance(data, bytes):
                yield StaticFileEntry(name, data)
            elif isinstance(data, str):
                yield StaticFileEntry(name, data.encode())
            elif isinstance(data, Mapping):
                yield FuncDirEntry(name, partial(self._dir, data))
            else:
                raise TypeError("Unexpected content type: {!r}".format(data))

    def get_root(self) -> DirEntry:
        return FuncDirEntry('.', partial(self._dir, self.content))

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--file'], metavar='PATH=CONTENT',
                         help='File to be placed in the storage',
                         multiple=True),
        ]

    @classmethod
    def cli_create(cls, data):
        content: Dict[str, Union[Dict, str]] = {}
        for file in data['file']:
            path, data = file.split('=', 1)
            path_parts = path.split('/')
            content_place: Dict[str, Any] = content
            for part in path_parts[:-1]:
                content_place = content_place.setdefault(part, {})
            content_place[path_parts[-1]] = data
        return {
            'content': content,
        }
