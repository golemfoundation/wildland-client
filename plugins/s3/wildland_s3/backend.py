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
S3 storage backend
'''

from pathlib import PurePosixPath
from io import BytesIO
from typing import Iterable, Tuple, Set, List
import mimetypes
import logging
from urllib.parse import urlparse
import os
import errno
import html
import stat
import threading
import time

import boto3
import botocore
import click

from wildland.storage_backends.base import StorageBackend, Attr, StaticSubcontainerStorageMixin
from wildland.storage_backends.buffered import File, FullBufferedFile, PagedFile
from wildland.storage_backends.cached import CachedStorageMixin
from wildland.manifest.schema import Schema


logger = logging.getLogger('storage-s3')


class S3FileAttr(Attr):
    """
    File attributes, include S3 E-Tag
    """
    def __init__(self, size: int, timestamp: int, etag: str):
        self.etag = etag
        self.mode = stat.S_IFREG | 0o644
        self.size = size
        self.timestamp = timestamp

    @classmethod
    def from_s3_object(cls, obj):
        '''
        Convert S3's object summary, as returned by list_objects_v2 or
        head_object.
        '''
        etag = obj['ETag'].strip('\"')

        timestamp = int(obj['LastModified'].timestamp())
        if 'Size' in obj:
            size = obj['Size']
        else:
            size = obj['ContentLength']

        return cls(size, timestamp, etag)


class S3File(FullBufferedFile):
    '''
    A buffered S3 file.
    '''

    def __init__(self, client, bucket, key, content_type, attr, clear_cache_callback):
        super().__init__(attr, clear_cache_callback)
        self.client = client
        self.bucket = bucket
        self.key = key
        self.content_type = content_type

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


class PagedS3File(PagedFile):
    '''
    A read-only paged S3 file.
    '''

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


class S3StorageBackend(StaticSubcontainerStorageMixin, CachedStorageMixin, StorageBackend):
    '''
    Amazon S3 storage.
    '''

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
                    {"$ref": "types.json#http-url"},
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
                "description": "Maintain index.html files with directory listings",
            },
            "subcontainers" : {
                "type": "array",
                "items": {
                    "$ref": "types.json#rel-path",
                }
            }
        }
    })
    TYPE = 's3'

    INDEX_NAME = 'index.html'

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
            endpoint_url=self.params.get('endpoint_url', None),
        )

        s3_url = urlparse(self.params['s3_url'])
        assert s3_url.scheme == 's3'

        self.bucket = s3_url.netloc
        self.base_path = PurePosixPath(s3_url.path)

        # Persist created directories. This is because S3 doesn't have
        # information about directories, and we might want to create/remove
        # them manually.
        self.s3_dirs_lock = threading.Lock()
        self.s3_dirs: Set[PurePosixPath] = {PurePosixPath('.')}

        mimetypes.init()

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--endpoint-url'], metavar='URL',
                         help='Override default AWS S3 URL with the given URL.'),
            click.Option(['--s3-url'], metavar='URL', required=True,
                         help='S3 url to access the resource in s3://<bucket_name>/path format'),
            click.Option(['--with-index'], is_flag=True,
                         help='Maintain index.html files with directory listings'),
        ]

    @classmethod
    def cli_create(cls, data):
        click.echo('Resolving AWS credentials...')
        session = botocore.session.Session()
        resolver = botocore.credentials.create_credential_resolver(session)
        credentials = resolver.load_credentials()
        if not credentials:
            raise click.ClickException(
                "AWS not configured, run 'aws configure' first")
        click.echo(f'Credentials found by method: {credentials.method}')

        return {
            's3_url': data['s3_url'],
            'endpoint_url': data['endpoint_url'],
            'credentials': {
                'access-key': credentials.access_key,
                'secret-key': credentials.secret_key,
            },
            'with-index': data['with_index'],
        }

    def mount(self):
        '''
        Regenerate index files on mount.
        '''

        if self.with_index and not self.read_only:
            self.refresh()
            with self.s3_dirs_lock:
                s3_dirs = list(self.s3_dirs)
            for path in s3_dirs:
                self._update_index(path)

    def key(self, path: PurePosixPath) -> str:
        '''
        Convert path to S3 object key.
        '''
        return str((self.base_path / path).relative_to('/'))

    def url(self, path: PurePosixPath) -> str:
        '''
        Convert path to relative S3 URL.
        '''
        return str(self.base_path / path)

    @staticmethod
    def _stat(obj) -> Attr:
        return S3FileAttr.from_s3_object(obj)

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        new_s3_dirs = set()

        token = None
        while True:
            if token:
                resp = self.client.list_objects_v2(
                    Bucket=self.bucket,
                    ContinuationToken=token,
                )
            else:
                resp = self.client.list_objects_v2(
                    Bucket=self.bucket,
                )

            for summary in resp.get('Contents', []):

                full_path = PurePosixPath('/') / summary['Key']
                try:
                    obj_path = full_path.relative_to(self.base_path)
                except ValueError:
                    continue

                if not (self.with_index and obj_path.name == self.INDEX_NAME):
                    yield obj_path, self._stat(summary)

                # Add path to s3_dirs even if we just see index.html.
                for parent in obj_path.parents:
                    new_s3_dirs.add(parent)

            if resp['IsTruncated']:
                token = resp['NextContinuationToken']
            else:
                break

        # In case we haven't found any files
        new_s3_dirs.add(PurePosixPath('.'))

        with self.s3_dirs_lock:
            self.s3_dirs.update(new_s3_dirs)
            all_s3_dirs = list(self.s3_dirs)

        for dir_path in all_s3_dirs:
            yield dir_path, Attr.dir()

    @staticmethod
    def get_content_type(path: PurePosixPath) -> str:
        '''
        Guess the right content type for given path.
        '''

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
                    content_type, attr, self.clear_cache)

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
        self.clear_cache()
        self._update_index(path.parent)
        return S3File(self.client, self.bucket, self.key(path),
                      content_type, attr, self.clear_cache)

    def unlink(self, path: PurePosixPath):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        self.client.delete_object(
            Bucket=self.bucket,
            Key=self.key(path))
        self.clear_cache()
        self._update_index(path.parent)

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        self.s3_dirs.add(path)
        self.clear_cache()
        self._update_index(path)
        self._update_index(path.parent)

    def rmdir(self, path: PurePosixPath):
        if not path.parts:
            raise IOError(errno.EPERM, str(path))

        self.s3_dirs.remove(path)
        self.clear_cache()
        self._remove_index(path)
        self._update_index(path.parent)

    def truncate(self, path: PurePosixPath, length: int):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        if length > 0:
            raise NotImplementedError()
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(path),
            ContentType=self.get_content_type(path))
        self.clear_cache()

    def get_file_token(self, path: PurePosixPath) -> int:
        s3attr = self.getattr(path)

        # TODO In the future the hash won't have to be an int (see #103)
        return int(s3attr.etag[0:15], 16)

    def _remove_index(self, path):
        if self.read_only or not self.with_index:
            return

        self.client.delete_object(
            Bucket=self.bucket,
            Key=self.key(path / self.INDEX_NAME))

    def _update_index(self, path):
        if self.read_only or not self.with_index:
            return

        entries = self._get_index_entries(path)
        data = self._generate_index(path, entries)

        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(path / self.INDEX_NAME),
            Body=BytesIO(data.encode()),
            ContentType='text/html')

    def _get_index_entries(self, path):
        # (name, url, is_dir)
        entries: List[Tuple[str, str, bool]] = []
        if path != PurePosixPath('.'):
            entries.append(('..', self.url(path.parent), Attr.dir()))

        try:
            names = list(self.readdir(path))
        except IOError:
            return entries

        for name in names:
            try:
                attr = self.getattr(path / name)
            except IOError:
                continue
            entry = (name, self.url(path / name), attr)
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
                if url != '/':
                    url += '/'
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

    def release(self, _path: PurePosixPath, flags: int, obj: File) -> None:
        super().release(_path, flags, obj)
        if isinstance(obj, S3File):
            self._update_index(obj.parent)
