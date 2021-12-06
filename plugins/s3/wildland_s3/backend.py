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
S3 storage backend
"""

from pathlib import PurePosixPath
from io import BytesIO
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import mimetypes

from urllib.parse import urlparse
import errno
import html
import os
import stat
import time

import boto3
import botocore
import click

from wildland.link import Link
from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.file_children import FileChildrenMixin
from wildland.storage_backends.buffered import File, FullBufferedFile, PagedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin
from wildland.manifest.schema import Schema
from wildland.exc import WildlandError
from wildland.log import get_logger


logger = get_logger('storage-s3')


class S3FileAttr(Attr):
    """
    File attributes, include S3 E-Tag.
    """
    def __init__(self, size: int, timestamp: int, etag: str):
        self.etag = etag
        self.mode = stat.S_IFREG | 0o644
        self.size = size
        self.timestamp = timestamp

    @classmethod
    def from_s3_object(cls, obj: Dict[str, Any]):
        """
        Convert S3's object summary, as returned by ``list_objects_v2`` or ``head_object``.
        """
        etag = obj['ETag'].strip('\"')

        timestamp = int(obj['LastModified'].timestamp())
        if 'Size' in obj:
            size = obj['Size']
        else:
            size = obj['ContentLength']

        return cls(size, timestamp, etag)


class S3File(FullBufferedFile):
    """
    A buffered S3 file.
    """

    def __init__(self,
                 client,
                 bucket: bytes,
                 key: str,
                 content_type: str,
                 attr: Attr,
                 update_cache: Callable[[PurePosixPath, Attr], None]):
        super().__init__(attr, self.__clear_cache)
        self.client = client
        self.bucket = bucket
        self.key = key
        self.content_type = content_type
        self.update_cache = update_cache

    def read_full(self) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=self.key,
        )
        return response['Body'].read()

    def write_full(self, data: bytes) -> int:
        # Set the Content-Type again, otherwise it will get overwritten with
        # application/octet-stream.
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key,
            Body=BytesIO(data),
            ContentType=self.content_type)
        return len(data)

    def __clear_cache(self):
        """
        Get the file info and update a single cache record instead of invalidating the entire cache.
        """
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=self.key,
        )
        path = PurePosixPath(self.key)
        attr = S3FileAttr.from_s3_object(response)
        self.update_cache(path, attr)


class PagedS3File(PagedFile):
    """
    A read-only paged S3 file.
    """

    def __init__(self, client, bucket, key, attr):
        super().__init__(attr)
        self.client = client
        self.bucket = bucket
        self.key = key

    def read_range(self, length, start) -> bytes:
        range_header = 'bytes={}-{}'.format(start, start+length-1)
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=self.key,
            Range=range_header,
        )
        return response['Body'].read()


class S3StorageBackend(FileChildrenMixin, DirectoryCachedStorageMixin, StorageBackend):
    """
    Amazon S3 storage.
    """

    SCHEMA = Schema({
        "title": "Storage manifest (S3)",
        "type": "object",
        "required": ["s3_url", "credentials"],
        "properties": {
            "s3_url": {
                "type": ["string", "null"],
                "description": "S3 URL, in the s3://bucket/path format",
                "pattern": "^s3://.*$"
            },
            "endpoint_url": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#http-url"},
                    {"type": "null"}
                ],
                "description": "Override default AWS S3 URL with the given URL."
            },
            "credentials": {
                "type": "object",
                "required": ["access-key", "secret-key"],
                "properties": {
                    "access-key": {"type": "string"},
                    "secret-key": {"type": "string"}
                },
                "additionalProperties": False
            },
            "with-index": {
                "type": "boolean",
                "description": "Maintain index.html files with directory listings (default: False)",
            },
            "manifest-pattern": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#pattern-glob"},
                    {"$ref": "/schemas/types.json#pattern-list"},
                ]
            }
        }
    })
    TYPE = 's3'
    LOCATION_PARAM = 'base_url'

    INDEX_NAME = '/'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.with_index = self.params.get('with-index', False)

        credentials = self.params['credentials']
        session = boto3.Session(
            aws_access_key_id=credentials['access-key'],
            aws_secret_access_key=credentials['secret-key'],
        )

        # S3 Client documentation:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client
        #
        # Note that the client is thread-safe:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/guide/resources.html
        # "Low-level clients *are* thread safe. When using a low-level client,
        # it is recommended to instantiate your client then pass that client
        # object to each of your threads."
        self.client = session.client(
            service_name='s3',
            endpoint_url=self.params.get('endpoint_url'),
        )

        # Security token services client allows to verify credentials before
        # executing any S3 operation on the bucket
        #
        # This service is AWS specific.
        if self.params.get('endpoint_url'):
            self.sts_client = None
        else:
            self.sts_client = session.client(service_name='sts')

        base_url = self.params.get('base_url', '/')
        s3_url = urlparse(self.params['s3_url']+base_url.lstrip('/'))
        assert s3_url.scheme == 's3'

        self.bucket = s3_url.netloc
        self.base_path = PurePosixPath(s3_url.path)

        mimetypes.init()

    @classmethod
    def cli_options(cls):
        opts = super(S3StorageBackend, cls).cli_options()
        opts.extend([
            click.Option(['--endpoint-url'], metavar='URL',
                         help='Override default AWS S3 URL with the given URL.'),
            click.Option(['--s3-url'], metavar='URL', required=True,
                         help='S3 url to access the resource in s3://<bucket_name>/path format'),
            click.Option(['--with-index'], is_flag=True,
                         help='Maintain index.html files with directory listings'),
            click.Option(['--access-key'], required=True,
                         help='S3 access key'),
            click.Option(['--secret-key'], required=True,
                         help='S3 secret key (omit for a prompt)',
                         prompt=True, hide_input=True),
        ])
        return opts

    @classmethod
    def cli_create(cls, data):
        result = super(S3StorageBackend, cls).cli_create(data)
        base_url = urlparse(data['s3_url']).path.lstrip('/')
        # ensuring that the s3_url entered by the user contains a trailing slash
        if not data['s3_url'].endswith('/'):
            data['s3_url'] = data['s3_url']+'/'
        result.update({
            's3_url': data['s3_url'],
            'base_url': base_url,
            'endpoint_url': data['endpoint_url'],
            'credentials': {
                'access-key': data['access_key'],
                'secret-key': data['secret_key'],
            },
            'with-index': data['with_index'],
        })
        return result

    def mount(self):
        """
        Regenerate index files on mount.
        """

        try:
            if self.sts_client:
                self.sts_client.get_caller_identity()
                # do this only once
                self.sts_client = None
        except botocore.exceptions.ClientError as ex:
            raise WildlandError(f"Could not connect to AWS with Exception: {ex}") from ex

    def key(self, path: PurePosixPath, is_dir: bool = False) -> str:
        """
        Convert path to S3 object key.
        """
        path = (self.base_path / path)

        if is_dir:
            return str(path.relative_to('/')) + '/'

        return str(path.relative_to('/'))

    @staticmethod
    def _index_entry_href(path: PurePosixPath, is_dir: bool = False) -> str:
        resolved_path = str(path)

        if is_dir:
            resolved_path += '/'

        return resolved_path

    @staticmethod
    def _stat(obj) -> Attr:
        return S3FileAttr.from_s3_object(obj)

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[PurePosixPath, Attr]]:
        """
        Retrieve information about files in a directory (readdir + getattr).
        """
        prefix = self.key(path, is_dir=True)
        if prefix == './':
            prefix = ''
        token = None
        while True:
            if token:
                resp = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=prefix,  # list only files/dirs in given 'subdir'/prefix
                    Delimiter='/',  # trick to list dir without subdirs
                    ContinuationToken=token,
                )
            else:
                resp = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    Prefix=prefix,
                    Delimiter='/',
                )

            # iterate files (Prefix and Delimiter in the list_objects_v2 request determine that
            # those are files only, and not dirs)
            for summary in resp.get('Contents', []):
                full_path = PurePosixPath('/') / summary['Key']

                try:
                    obj_path = full_path.relative_to(self.base_path)
                except ValueError:
                    logger.warning('Unable to get relative path [%s]', full_path)
                    continue

                # don't add '.' directory because it's added explicitly
                if obj_path == path:
                    continue

                if not (self.with_index and obj_path.name == self.INDEX_NAME):
                    fname = obj_path.relative_to(path)
                    yield PurePosixPath(fname), self._stat(summary)

            # iterate subdirectories
            for summary in resp.get('CommonPrefixes', []):
                key = summary['Prefix']
                assert key, f'Unexpected None key in {summary} for {path}'
                full_path = PurePosixPath('/') / key

                try:
                    obj_path = full_path.relative_to(self.base_path)
                except ValueError:
                    logger.warning('Unable to get relative path [%s]', full_path)
                    continue

                fname = obj_path.relative_to(path)
                yield PurePosixPath(fname), Attr.dir()

            if resp['IsTruncated']:
                token = resp['NextContinuationToken']
            else:
                break

    @property
    def can_have_children(self) -> bool:
        return True

    def get_children(
            self,
            client=None,
            query_path: PurePosixPath = PurePosixPath('*'),
            paths_only: bool = False
    ) -> Iterable[Tuple[PurePosixPath, Optional[Link]]]:

        for res_path, res_obj in super().get_children(query_path=query_path):
            if not paths_only:
                assert isinstance(res_obj, Link)
                assert res_obj.storage_driver.storage_backend is self
                # fast path to get the file, bypassing refreshing getattr cache
                response = self.client.get_object(
                    Bucket=self.bucket,
                    Key=self.key(res_obj.file_path.relative_to('/'))
                )
                res_obj.file_bytes = response['Body'].read()
                yield res_path, res_obj
            else:
                yield res_path, None

    @staticmethod
    def get_content_type(path: PurePosixPath) -> str:
        """
        Guess the right content type for given path.
        """

        content_type, _encoding = mimetypes.guess_type(path.name)
        return content_type or 'application/octet-stream'

    def open(self, path: PurePosixPath, flags: int) -> File:
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.ENOENT, str(path))

        try:
            head = self.client.head_object(
                Bucket=self.bucket,
                Key=self.key(path),
            )
            attr = self._stat(head)
            if flags & (os.O_WRONLY | os.O_RDWR):
                content_type = self.get_content_type(path)
                return S3File(
                    self.client, self.bucket, self.key(path),
                    content_type, attr, self.update_cache)

            return PagedS3File(self.client, self.bucket, self.key(path), attr)
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise FileNotFoundError(errno.ENOENT, str(path)) from e
            raise e

    def create(self, path: PurePosixPath, _flags: int, _mode: int = 0o666) -> File:
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        content_type = self.get_content_type(path)
        logger.debug('creating %s with content type %s', path, content_type)
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(path),
            ContentType=content_type)

        attr = Attr.file(size=0, timestamp=int(time.time()))
        self.update_cache(path, attr)
        self._update_index(path.parent)
        return S3File(self.client, self.bucket, self.key(path),
                      content_type, attr, self.update_cache)

    def unlink(self, path: PurePosixPath):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        self.client.delete_object(
            Bucket=self.bucket,
            Key=self.key(path))
        self.update_cache(path, None)
        self._update_index(path.parent)

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(path, is_dir=True))

        attr = Attr.dir()
        self.update_cache(path, attr)
        self._update_index(path)
        self._update_index(path.parent)

    def rmdir(self, path: PurePosixPath):
        if not path.parts:
            raise IOError(errno.EPERM, str(path))

        children = self.readdir(path)
        if len(list(children)) > 0:
            raise IOError(errno.ENOTEMPTY, str(path))

        self.client.delete_object(
            Bucket=self.bucket,
            Key=self.key(path, is_dir=True))
        self.update_cache(path, None)
        self._remove_index(path)
        self._update_index(path.parent)

    def chmod(self, path: PurePosixPath, mode: int):
        logger.debug("chmod dummy op %s mode %d", str(path), mode)

    def chown(self, path: PurePosixPath, uid: int, gid: int):
        logger.debug("chown dummy op %s uid %d gid %d", str(path), uid, gid)

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        """
        This method should be called if and only if the source and destination is
        within the same bucket.
        """
        self._rename(move_from, move_to)

        self._update_index(move_from.parent)
        self._update_index(move_to.parent)

    def _rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        """
        Internal recursive handler for rename()
        """
        if self.getattr(move_from).is_dir():
            for obj in self.readdir(move_from):
                self._rename(move_from / obj, move_to / obj)

            # in case of empty directories
            self.rmdir(move_from)
            self.mkdir(move_to)
        else:
            logger.debug('renaming %s to %s',
                         f"{self.bucket}/{self.key(move_from)}", self.key(move_to))

            # S3 doesn't support renaming. you *must* copy and delete an object
            # in order to rename
            self.client.copy_object(
                Bucket=self.bucket,
                Key=self.key(move_to),
                CopySource=f"{self.bucket}/{self.key(move_from)}",
            )
            self.update_cache(move_to, self.getattr_cache[move_from])
            self.unlink(move_from)

    def utimens(self, path: PurePosixPath, atime, mtime) -> None:
        logger.debug("utimens dummy op %s", str(path))

    def truncate(self, path: PurePosixPath, length: int):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        if length > 0:
            raise NotImplementedError()
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(path),
            ContentType=self.get_content_type(path))

        attr = Attr.file(size=0, timestamp=int(time.time()))
        self.update_cache(path, attr)

    def get_file_token(self, path: PurePosixPath) -> Optional[str]:
        attr = self.getattr(path)

        if attr.is_dir():
            return None

        if isinstance(attr, S3FileAttr):
            return attr.etag

        return None

    def start_bulk_writing(self) -> None:
        self.clear_cache()
        self.cache_timeout = float('inf')

    def stop_bulk_writing(self) -> None:
        self.clear_cache()

    def _remove_index(self, path):
        if self.read_only or not self.with_index:
            return

        self.client.delete_object(
            Bucket=self.bucket,
            Key=self.key(path / self.INDEX_NAME))

    def _update_index(self, path: PurePosixPath) -> None:
        if self.read_only or not self.with_index:
            return

        entries = self._get_index_entries(path)
        data = self._generate_index(path, entries)

        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(path, is_dir=True),
            Body=BytesIO(data.encode()),
            ContentType='text/html')

    def _get_index_entries(self, path: PurePosixPath):
        # (name, url, is_dir)
        entries: List[Tuple[str, str, Attr]] = []
        if path != PurePosixPath('.'):
            entries.append((
                '..',
                self._index_entry_href(PurePosixPath('..'), is_dir=True),
                Attr.dir())
            )

        try:
            names = list(self.readdir(path))
        except IOError:
            return entries

        for name in names:
            try:
                attr = self.getattr(path / name)
            except IOError:
                continue
            entry = (name, self._index_entry_href(PurePosixPath(name), attr.is_dir()), attr)
            entries.append(entry)

        # Sort directories first
        def key(entry):
            name, _url, attr = entry

            return (0 if attr.is_dir() else 1), name

        entries.sort(key=key)
        return entries

    @staticmethod
    def _generate_index(path, entries) -> str:
        title = str(PurePosixPath('/') / path)

        data = '''\
<!DOCTYPE html>
<style>
  main {
    font-size: 16px;
    font-family: monospace;
  }
  a { text-decoration: none; }
</style>'''
        data += '<title>Directory: {}</title>\n'.format(html.escape(title))
        data += '<h1>Directory: {}</h1>\n'.format(html.escape(title))
        data += '<main>\n'

        for name, url, attr in entries:
            if attr.is_dir():
                icon = '&#x1F4C1;'
                name += '/'
            else:
                icon = '&#x1F4C4;'

            data += (
                '<a data-size="{size}" data-timestamp="{timestamp}" '
                'href="{href}">{icon} {name}</a><br>\n'
            ).format(
                size=attr.size,
                timestamp=attr.timestamp,
                href=html.escape(url, quote=True),
                icon=icon,
                name=html.escape(name),
            )
        data += '</main>\n'

        return data

    def flush(self, path: PurePosixPath, obj: File) -> None:
        """
        Performance hack. Assumes the buffer is going to be dumped to the file,
        without sending get() request to the backend server to verify that the bytes
        were actually written. Situation like that should not happen though as if
        the dirty buffer failed to write to the backend, it should throw an exception.
        """
        attr = obj.fgetattr()
        super().flush(path, obj)

        self.update_cache(path, attr)
        self._update_index(path.parent)

    def release(self, path: PurePosixPath, flags: int, obj: File) -> None:
        """
        Same performance hack as in flush()
        """
        attr = obj.fgetattr()
        super().release(path, flags, obj)

        self.update_cache(path, attr)
        self._update_index(path.parent)
