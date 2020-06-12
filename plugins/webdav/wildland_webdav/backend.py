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
WebDAV storage backend
'''

from pathlib import PurePosixPath
from typing import Iterable, Tuple
from urllib.parse import urljoin, urlparse, quote, unquote

import dateutil.parser
import requests
import requests.auth
from lxml import etree
import click
import fuse

from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.buffered import BufferedStorageBackend
from wildland.storage_backends.cached2 import CachedStorageBackend
from wildland.manifest.schema import Schema


class WebdavStorageBackend(StorageBackend):
    '''
    WebDAV storage.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["url", "credentials"],
        "properties": {
            "url": {
            "$ref": "types.json#http_url",
                "description": "HTTP URL, e.g. https://example.com/remote.php/dav/files/user/"
            },
            "credentials": {
                "type": "object",
                "required": ["login", "password"],
                "properties": {
                    "login": {"type": "string"},
                    "password": {"type": "string"}
                },
                "additionalProperties": False
            }
        }
    })
    TYPE = 'webdav'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        credentials = self.params['credentials']
        auth = requests.auth.HTTPBasicAuth(
            credentials['login'], credentials['password'])
        self.session = requests.Session()
        self.session.auth = auth

        self.base_url = self.params['url']
        self.base_path = PurePosixPath(urlparse(self.base_url).path)

    @classmethod
    def add_wrappers(cls, backend):
        return BufferedStorageBackend(
            CachedStorageBackend(backend))

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--url'], metavar='URL', required=True),
            click.Option(['--login'], metavar='LOGIN', required=True),
            click.Option(['--password'], metavar='PASSWORD', required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'url': data['url'],
            'credentials': {
                'login': data['login'],
                'password': data['password'],
            }
        }

    def extra_info_all(self) -> Iterable[Tuple[PurePosixPath, fuse.Stat]]:
        path = PurePosixPath('.')
        depth = 'infinity'
        resp = self.session.request(
            method='PROPFIND',
            url=self.make_url(path),
            headers={'Accept': '*/*', 'Depth': depth}
        )
        resp.raise_for_status()

        doc = etree.fromstring(resp.content)
        for response in doc.findall('./{DAV:}response'):
            href = response.findtext('./{DAV:}href')
            if href is None:
                continue
            full_path = unquote(urlparse(href).path)
            path = PurePosixPath(full_path).relative_to(self.base_path)

            prop = response.find('./{DAV:}propstat/{DAV:}prop')
            if prop is None:
                continue

            is_dir = (
                prop.find('./{DAV:}resourcetype/{DAV:}collection') is not None
            )

            timestamp = 0
            last_modified = prop.findtext('./{DAV:}getlastmodified')
            if last_modified:
                timestamp = int(
                    dateutil.parser.parse(last_modified).timestamp())

            size = 0
            content_length = prop.findtext('./{DAV:}getcontentlength')
            if content_length:
                size = int(content_length)

            if is_dir:
                yield path, self.simple_dir_stat(size, timestamp)
            else:
                yield path, self.simple_file_stat(size, timestamp)

    def make_url(self, path: PurePosixPath) -> str:
        '''
        Convert a Path to resource URL.
        '''

        full_path = self.base_path / path
        return urljoin(self.base_url, quote(str(full_path)))

    def create(self, path: PurePosixPath, flags: int, mode: int):
        self.extra_write_full(path, b'', None)

    def truncate(self, path: PurePosixPath, length: int):
        if length > 0:
            raise NotImplementedError()
        self.extra_write_full(path, b'', None)

    def mkdir(self, path: PurePosixPath, _mode: int) -> None:
        resp = self.session.request(
            method='MKCOL',
            url=self.make_url(path),
        )
        resp.raise_for_status()

    def extra_read_full(self, path: PurePosixPath, _handle) -> bytes:
        resp = self.session.request(
            method='GET',
            url=self.make_url(path),
            headers={'Accept': '*/*'}
        )
        resp.raise_for_status()
        return resp.content

    def extra_write_full(self, path: PurePosixPath, data: bytes, _handle) -> int:
        resp = self.session.request(
            method='PUT',
            url=self.make_url(path),
            data=data,
        )
        resp.raise_for_status()
        return len(data)

    def unlink(self, path: PurePosixPath):
        resp = self.session.request(
            method='DELETE',
            url=self.make_url(path),
        )
        resp.raise_for_status()

    def rmdir(self, path: PurePosixPath):
        self.unlink(path)
