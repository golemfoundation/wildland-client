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
import errno

import dateutil.parser
import requests
import requests.auth
from lxml import etree
import click

from wildland.storage_backends.cached import CachedStorageBackend, Info
from wildland.manifest.schema import Schema


class WebdavStorageBackend(CachedStorageBackend):
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

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        return self.propfind(PurePosixPath('.'), 'infinity')

    def backend_info_single(self, path: PurePosixPath) -> Info:
        '''
        Retrieve information about a single path.
        '''

        props = list(self.propfind(path, '0'))
        if not props:
            raise FileNotFoundError(errno.ENOENT, str(path))
        return props[0][1]

    def propfind(self, path: PurePosixPath, depth: str) -> \
        Iterable[Tuple[PurePosixPath, Info]]:
        '''
        Make a WebDAV PROPFIND request.
        '''

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

            yield path, Info(is_dir=is_dir, size=size, timestamp=timestamp)

    def make_url(self, path: PurePosixPath) -> str:
        '''
        Convert a Path to resource URL.
        '''

        full_path = self.base_path / path
        return urljoin(self.base_url, quote(str(full_path)))

    def backend_create_file(self, path: PurePosixPath) -> Info:
        return self.backend_save_file(path, b'')

    def backend_create_dir(self, path: PurePosixPath) -> Info:
        resp = self.session.request(
            method='MKCOL',
            url=self.make_url(path),
        )
        resp.raise_for_status()
        return self.backend_info_single(path)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        resp = self.session.request(
            method='GET',
            url=self.make_url(path),
            headers={'Accept': '*/*'}
        )
        resp.raise_for_status()
        return resp.content

    def backend_save_file(self, path: PurePosixPath, data: bytes) -> Info:
        resp = self.session.request(
            method='PUT',
            url=self.make_url(path),
            data=data,
        )
        resp.raise_for_status()
        return self.backend_info_single(path)

    def backend_delete_file(self, path: PurePosixPath):
        resp = self.session.request(
            method='DELETE',
            url=self.make_url(path),
        )
        resp.raise_for_status()

    def backend_delete_dir(self, path: PurePosixPath):
        return self.backend_delete_file(path)
