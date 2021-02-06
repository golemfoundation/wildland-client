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
Indexed HTTP storage backend
'''

from datetime import datetime
from pathlib import PurePosixPath
from typing import Iterable, Tuple
from urllib.parse import urljoin, urlparse, quote
import logging
from io import BytesIO

import click
from lxml import etree
import requests

from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import PagedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.manifest.schema import Schema


logger = logging.getLogger('storage-s3')


class PagedHttpFile(PagedFile):
    '''
    A read-only paged HTTP file.
    '''

    def __init__(self,
                 url: str,
                 attr):
        super().__init__(attr)
        self.url = url

    def read_range(self, length, start) -> bytes:
        range_header = 'bytes={}-{}'.format(start, start+length-1)

        resp = requests.request(
            method='GET',
            url=self.url,
            headers={
                'Accept': '*/*',
                'Range': range_header
            }
        )
        resp.raise_for_status()
        return resp.content


class HttpIndexStorageBackend(DirectoryCachedStorageMixin, StorageBackend):
    '''
    A read-only HTTP storage that gets its information from directory listings.
    '''

    SCHEMA = Schema({
        "title": "Storage manifest (HTTP index)",
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "$ref": "/schemas/types.json#http-url",
                "description": "HTTP URL pointing to an index",
            },
        }
    })
    TYPE = 'http-index'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.url = urlparse(self.params['url'])
        self.read_only = True

        self.base_url = self.params['url']
        self.base_path = PurePosixPath(urlparse(self.base_url).path or '/')

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--url'], metavar='URL', required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'url': data['url'],
        }

    def make_url(self, path: PurePosixPath) -> str:
        '''
        Convert a Path to resource URL.
        '''

        full_path = self.base_path / path
        return urljoin(self.base_url, quote(str(full_path)))

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[str, Attr]]:
        url = self.make_url(path)
        resp = requests.request(
            method='GET',
            url=url,
            headers={
                'Accept': 'text/html',
            }
        )

        # Special handling for 403 Forbidden
        if resp.status_code == 403:
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

            if urlparse(href).netloc:
                continue

            # skip apache sorting links
            if href.startswith('?C='):
                continue

            # apache2 generates relative paths, S3StorageBackend - absolute
            abs_path = self.base_path / path / href
            try:
                rel_path = PurePosixPath(abs_path).relative_to(self.base_path)
            except ValueError:
                continue

            if rel_path.parent != path:
                continue

            try:
                size = int(a_element.attrib['data-size'])
            except (KeyError, ValueError):
                size = 0

            try:
                timestamp = int(a_element.attrib['data-timestamp'])
            except (KeyError, ValueError):
                timestamp = 0

            if href.endswith('/'):
                attr = Attr.dir(size, timestamp)
            else:
                attr = Attr.file(size, timestamp)

            yield rel_path.name, attr

    def getattr(self, path: PurePosixPath) -> Attr:
        try:
            attr = super().getattr(path)
        except PermissionError:
            logger.info('Could not list directory for [%s]. '
                        'Falling back to the file directly.', str(path))
            url = self.make_url(path)
            attr = self._get_single_file_attr(url)

        return attr

    def open(self, path: PurePosixPath, flags: int) -> PagedHttpFile:
        url = self.make_url(path)
        attr = self._get_single_file_attr(url)
        return PagedHttpFile(url, attr)

    @staticmethod
    def _get_single_file_attr(url: str) -> Attr:
        resp = requests.request(
            method='HEAD',
            url=url,
            headers={
                'Accept': '*/*',
            }
        )
        resp.raise_for_status()

        size = int(resp.headers['Content-Length'])
        timestamp = datetime.strptime(
            resp.headers['Last-Modified'], "%a, %d %b %Y %X %Z"
        ).strftime("%s")

        return Attr.file(size, timestamp)
