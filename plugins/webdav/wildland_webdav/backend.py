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

"""
WebDAV storage backend
"""

from pathlib import PurePosixPath
from typing import Iterable, Tuple
from urllib.parse import urljoin, urlparse, quote, unquote
import os

import dateutil.parser
import requests
import requests.auth
from lxml import etree
import click

from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import FullBufferedFile, PagedFile
from wildland.storage_backends.cached import CachedStorageMixin
from wildland.storage_backends.file_subcontainers import FileSubcontainersMixin
from wildland.manifest.schema import Schema


class WebdavFile(FullBufferedFile):
    """
    A buffered WebDAV file.
    """

    def __init__(self, session, url: str, attr: Attr, clear_cache_callback):
        super().__init__(attr, clear_cache_callback)
        self.session = session
        self.url = url

    def read_full(self) -> bytes:
        resp = self.session.request(
            method='GET',
            url=self.url,
            headers={'Accept': '*/*'},
        )
        resp.raise_for_status()
        return resp.content

    def write_full(self, data: bytes) -> int:
        resp = self.session.request(
            method='PUT',
            url=self.url,
            data=data,
        )
        resp.raise_for_status()
        return len(data)


class PagedWebdavFile(PagedFile):
    """
    A read-only paged WebDAV file.
    """

    def __init__(self, session, url: str,
                 attr: Attr):
        super().__init__(attr)
        self.session = session
        self.url = url

    def read_range(self, length, start) -> bytes:
        range_header = 'bytes={}-{}'.format(start, start+length-1)

        resp = self.session.request(
            method='GET',
            url=self.url,
            headers={
                'Accept': '*/*',
                'Range': range_header
            },
        )
        resp.raise_for_status()
        return resp.content


class WebdavStorageBackend(FileSubcontainersMixin, CachedStorageMixin, StorageBackend):
    """
    WebDAV storage.
    """

    SCHEMA = Schema({
        "type": "object",
        "required": ["url", "credentials"],
        "properties": {
            "url": {
            "$ref": "/schemas/types.json#http-url",
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
            },
            "manifest-pattern": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#pattern-glob"},
                    {"$ref": "/schemas/types.json#pattern-list"},
                ]
            },
        }
    })
    TYPE = 'webdav'
    LOCATION_PARAM = 'url'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        credentials = self.params['credentials']
        self.auth = requests.auth.HTTPBasicAuth(
            credentials['login'], credentials['password'])
        self.session = requests.session()
        self.session.auth = self.auth

        self.public_url = self.params['url']
        self.base_path = PurePosixPath(urlparse(self.public_url).path)

    @classmethod
    def cli_options(cls):
        opts = super(WebdavStorageBackend, cls).cli_options()
        opts.extend([
            click.Option(['--url'], metavar='URL', required=True),
            click.Option(['--login'], metavar='LOGIN', required=True),
            click.Option(['--password'], metavar='PASSWORD', required=True,
                         help='Password (omit for a password prompt)',
                         prompt=True, hide_input=True),
        ])
        return opts

    @classmethod
    def cli_create(cls, data):
        result = super(WebdavStorageBackend, cls).cli_create(data)
        result.update({
            'url': data['url'],
            'credentials': {
                'login': data['login'],
                'password': data['password'],
            }
        })
        return result

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        path = PurePosixPath('.')
        depth = 'infinity'
        resp = self.session.request(
            method='PROPFIND',
            url=self.make_url(path),
            headers={'Accept': '*/*', 'Depth': depth},
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
                yield path, Attr.dir(size, timestamp)
            else:
                yield path, Attr.file(size, timestamp)

    def make_url(self, path: PurePosixPath) -> str:
        """
        Convert a Path to resource URL.
        """

        full_path = self.base_path / path
        return urljoin(self.public_url, quote(str(full_path)))

    def open(self, path: PurePosixPath, flags: int):
        attr = self.getattr(path)

        if flags & (os.O_WRONLY | os.O_RDWR):
            return WebdavFile(self.session, self.make_url(path), attr, self.clear_cache)

        return PagedWebdavFile(self.session, self.make_url(path), attr)

    def create(self, path: PurePosixPath, _flags: int, _mode: int = 0o666):
        resp = self.session.request(
            method='PUT', url=self.make_url(path), data=b'')
        resp.raise_for_status()
        self.clear_cache()
        attr = self.getattr(path)
        return WebdavFile(self.session, self.make_url(path), attr, self.clear_cache)

    def truncate(self, path: PurePosixPath, length: int):
        if length > 0:
            raise NotImplementedError()
        resp = self.session.request(
            method='PUT', url=self.make_url(path), data=b'')
        resp.raise_for_status()

    def _mkdir_with_parent(self, path: PurePosixPath):
        url = self.make_url(path)
        resp = self.session.request(
            method='MKCOL',
            url=url,
        )

        # WebDAV spec (RFC 4918) chapter 9.3 says code 409 "Conflict" is non-existing parent,
        # try to create it (even if above public_url) and retry
        if resp.status_code == 409 and urlparse(url).path != '/':
            self._mkdir_with_parent(path / '..')
            resp = self.session.request(
                method='MKCOL',
                url=url,
            )

        # The endpoint (URL) doesn't map to any dav resource. We most likely went to "deep" and
        # passed the webdav root path.
        if resp.status_code == 405:
            return

        resp.raise_for_status()

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777) -> None:
        self._mkdir_with_parent(path)
        self.clear_cache()

    def unlink(self, path: PurePosixPath):
        resp = self.session.request(
            method='DELETE',
            url=self.make_url(path),
        )
        resp.raise_for_status()
        self.clear_cache()

    def rmdir(self, path: PurePosixPath):
        self.unlink(path)
