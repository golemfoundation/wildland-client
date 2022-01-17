# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Indexed HTTP storage backend
"""

from datetime import datetime
from pathlib import PurePosixPath
from typing import Iterable, Tuple
from urllib.parse import urljoin, urlparse, quote
import errno
from io import BytesIO

import click
from lxml import etree
import requests

from wildland.storage_backends.file_children import FileChildrenMixin
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import FullBufferedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.manifest.schema import Schema
from wildland.log import get_logger

logger = get_logger('storage-http')


# TODO: Changed to FullBufferedFile due to pre-release hotfix. Requires proper implementation
# ref. https://gitlab.com/wildland/wildland-client/-/issues/467
class PagedHttpFile(FullBufferedFile):
    """
    A read-only fully buffered HTTP file.
    """

    def __init__(self,
                 session,
                 url: str,
                 attr):
        super().__init__(attr)
        self.session = session
        self.url = url

    def read_full(self) -> bytes:
        resp = self.session.request(
            method='GET',
            url=self.url,
            headers={
                'Accept': '*/*',
            }
        )
        resp.raise_for_status()
        return resp.content

    def write_full(self, data: bytes) -> int:
        raise IOError(errno.EROFS, str(self.url))


class HttpStorageBackend(FileChildrenMixin, DirectoryCachedStorageMixin, StorageBackend):
    """
    A read-only HTTP storage that gets its information from directory listings.
    """

    SCHEMA = Schema({
        "title": "Storage manifest (HTTP index)",
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "$ref": "/schemas/types.json#http-url",
                "description": "HTTP URL pointing to an index",
            },
            "manifest-pattern": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#pattern-glob"},
                    {"$ref": "/schemas/types.json#pattern-list"},
                ]
            }
        }
    })
    TYPE = 'http'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.url = urlparse(self.params['url'])
        self.read_only = True
        self.session = requests.session()

        self.public_url = self.params['url']
        self.base_path = PurePosixPath(urlparse(self.public_url).path or '/')

    @classmethod
    def cli_options(cls):
        opts = super(HttpStorageBackend, cls).cli_options()
        opts.extend([
            click.Option(['--url'], metavar='URL', required=True),
        ])
        return opts

    @classmethod
    def cli_create(cls, data):
        result = super(HttpStorageBackend, cls).cli_create(data)
        result.update({
            'url': data['url'],
        })
        return result

    def make_url(self, path: PurePosixPath, is_dir=False) -> str:
        """
        Convert a Path to resource URL.
        """

        full_path = str(self.base_path / path)

        if is_dir:
            # Ensure that directory requests have trailing slash
            # as not every webserver will reply with missing trailing slash
            full_path += '/'

        return urljoin(self.public_url, quote(full_path))

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[PurePosixPath, Attr]]:
        url = self.make_url(path, is_dir=True)
        resp = self.session.request(
            method='GET',
            url=url,
            headers={
                'Accept': 'text/html',
            }
        )

        # Special handling for 403 Forbidden
        if resp.status_code == 403 or not resp.content:
            raise PermissionError(f'Could not list requested directory [{path}]')

        # For all other cases throw a joint HTTPError
        resp.raise_for_status()

        parser = etree.HTMLParser()
        tree = etree.parse(BytesIO(resp.content), parser)
        for a_element in tree.findall('.//a'):
            try:
                href = a_element.attrib['href']
            except KeyError:
                continue

            parsed_href = urlparse(href)

            # Skip urls to external resources (non-relative paths)
            if parsed_href.netloc:
                continue

            # Skip apache sorting links
            if parsed_href.path.startswith('?C='):
                continue

            # Skip apache directory listing's "Parent Directory" entry
            if parsed_href.path.startswith('/'):
                continue

            # Skip our backends directory listing's "Parent Directory" entry ("../")
            if parsed_href.path.startswith('..'):
                continue

            try:
                size = int(a_element.attrib['data-size'])
            except (KeyError, ValueError):
                size = 0

            try:
                timestamp = int(a_element.attrib['data-timestamp'])
            except (KeyError, ValueError):
                timestamp = 0

            if parsed_href.path.endswith('/'):
                attr = Attr.dir(size, timestamp)
            else:
                attr = Attr.file(size, timestamp)
            yield path / parsed_href.path, attr

    def getattr(self, path: PurePosixPath) -> Attr:
        try:
            attr = super().getattr(path)
        except PermissionError:
            logger.debug('Could not list directory for [%s]. '
                        'Falling back to the file directly.', str(path))
            url = self.make_url(path)
            attr = self._get_single_file_attr(url)

        return attr

    def open(self, path: PurePosixPath, _flags: int) -> PagedHttpFile:
        attr = self.getattr(path)
        url = self.make_url(path, is_dir=attr.is_dir())
        return PagedHttpFile(self.session, url, attr)

    def _get_single_file_attr(self, url: str) -> Attr:
        resp = self.session.request(
            method='HEAD',
            url=url,
            headers={
                'Accept': '*/*',
            }
        )
        resp.raise_for_status()

        size = int(resp.headers['Content-Length'])
        timestamp = int(datetime.strptime(
            resp.headers['Last-Modified'], "%a, %d %b %Y %X %Z"
        ).timestamp())

        return Attr.file(size, timestamp)
