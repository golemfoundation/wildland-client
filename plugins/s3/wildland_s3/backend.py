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
import stat
import html

import boto3
import botocore
import click
import fuse

from wildland.storage_backends.util import simple_file_stat, simple_dir_stat
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.buffered import FullBufferedFile, PagedFile
from wildland.storage_backends.cached import CachedStorageMixin
from wildland.manifest.schema import Schema


logger = logging.getLogger('storage-s3')


class S3File(FullBufferedFile):
    '''
    A buffered S3 file.
    '''

    def __init__(self, obj, content_type, attr):
        super().__init__(attr)
        self.obj = obj
        self.content_type = content_type

    def read_full(self) -> bytes:
        buf = BytesIO()
        self.obj.download_fileobj(buf)
        return buf.getvalue()

    def write_full(self, data: bytes) -> int:
        # Set the Content-Type again, otherwise it will get overwritten with
        # application/octet-stream.
        self.obj.upload_fileobj(
            BytesIO(data),
            ExtraArgs={'ContentType': self.content_type})
        return len(data)


class PagedS3File(PagedFile):
    '''
    A read-only paged S3 file.
    '''

    def __init__(self, obj, attr, page_size, max_pages):
        super().__init__(attr, page_size, max_pages)
        self.obj = obj

    def read_range(self, length, start) -> bytes:
        range_header = 'bytes={}-{}'.format(start, start+length-1)
        response = self.obj.get(Range=range_header)
        return response['Body'].read()


class S3StorageBackend(CachedStorageMixin, StorageBackend):
    '''
    Amazon S3 storage.
    '''

    SCHEMA = Schema({
        "title": "Storage manifest (S3)",
        "type": "object",
        "required": ["url", "credentials"],
        "properties": {
            "url": {
                "type": "string",
                "description": "S3 URL, in the s3://bucket/path format",
                "pattern": "^s3://.*$"
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
        s3 = session.resource('s3')

        url = urlparse(self.params['url'])
        assert url.scheme == 's3'

        bucket_name = url.netloc
        # pylint: disable=no-member
        self.bucket = s3.Bucket(bucket_name)
        self.base_path = PurePosixPath(url.path)

        # Persist created directories. This is because S3 doesn't have
        # information about directories, and we might want to create/remove
        # them manually.
        self.s3_dirs: Set[PurePosixPath] = {PurePosixPath('.')}

        mimetypes.init()

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--url'], metavar='URL', required=True),
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
            'url': data['url'],
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
            print(self.s3_dirs)
            for path in list(self.s3_dirs):
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
    def _stat(obj) -> fuse.Stat:
        '''
        Convert Amazon's Obj or ObjSummary to Info.
        '''
        timestamp = int(obj.last_modified.timestamp())
        if hasattr(obj, 'size'):
            size = obj.size
        else:
            size = obj.content_length
        return simple_file_stat(size, timestamp)

    def info_all(self) -> Iterable[Tuple[PurePosixPath, fuse.Stat]]:
        for obj_summary in self.bucket.objects.all():
            full_path = PurePosixPath('/') / obj_summary.key
            try:
                obj_path = full_path.relative_to(self.base_path)
            except ValueError:
                continue

            if not (self.with_index and obj_path.name == self.INDEX_NAME):
                yield obj_path, self._stat(obj_summary)

            # Add path to s3_dirs even if we just see index.html.
            for parent in obj_path.parents:
                self.s3_dirs.add(parent)

        # In case we haven't found any files
        self.s3_dirs.add(PurePosixPath('.'))

        for dir_path in self.s3_dirs:
            yield dir_path, simple_dir_stat()

    @staticmethod
    def get_content_type(path: PurePosixPath) -> str:
        '''
        Guess the right content type for given path.
        '''

        content_type, _encoding = mimetypes.guess_type(path.name)
        return content_type or 'application/octet-stream'

    def open(self, path: PurePosixPath, flags: int) -> S3File:
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.ENOENT, str(path))

        obj = self.bucket.Object(self.key(path))
        attr = self._stat(obj)
        if flags & (os.O_WRONLY | os.O_RDWR):
            content_type = self.get_content_type(path)
            return S3File(obj, content_type, attr)

        page_size = 8 * 1024 * 1024
        max_pages = 8
        return PagedS3File(obj, attr, page_size, max_pages)

    def create(self, path: PurePosixPath, _flags: int, _mode: int) -> S3File:
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        content_type = self.get_content_type(path)
        logger.debug('creating %s with content type %s', path, content_type)
        obj = self.bucket.put_object(Key=self.key(path),
                                     ContentType=content_type)
        attr = self._stat(obj)
        self.clear_cache()
        self._update_index(path.parent)
        return S3File(obj, content_type, attr)

    def unlink(self, path: PurePosixPath):
        if self.with_index and path.name == self.INDEX_NAME:
            raise IOError(errno.EPERM, str(path))

        self.bucket.Object(self.key(path)).delete()
        self.clear_cache()
        self._update_index(path.parent)

    def mkdir(self, path: PurePosixPath, _mode: int):
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
        obj = self.bucket.Object(self.key(path))
        obj.upload_fileobj(
            BytesIO(b''),
            ExtraArgs={'ContentType': self.get_content_type(path)})
        self.clear_cache()

    def _remove_index(self, path):
        if not self.with_index:
            return

        obj = self.bucket.Object(self.key(path / self.INDEX_NAME))
        obj.delete()

    def _update_index(self, path):
        if not self.with_index:
            return

        obj = self.bucket.Object(self.key(path / self.INDEX_NAME))

        entries = self._get_index_entries(path)
        data = self._generate_index(path, entries)

        obj.upload_fileobj(
            BytesIO(data.encode()),
            ExtraArgs={'ContentType': 'text/html'})

    def _get_index_entries(self, path):
        # (name, url, is_dir)
        entries: List[Tuple[str, str, bool]] = []
        if path != PurePosixPath('.'):
            entries.append(('..', self.url(path.parent), True))

        try:
            names = list(self.readdir(path))
        except IOError:
            return entries

        for name in names:
            try:
                is_dir = stat.S_ISDIR(self.getattr(path / name).st_mode)
            except IOError:
                continue
            entry = (name, self.url(path / name), is_dir)
            entries.append(entry)

        # Sort directories first
        def key(entry):
            name, _url, is_dir = entry
            return (0 if is_dir else 1), name

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

        for name, url, is_dir in entries:
            if is_dir:
                icon = '&#x1F4C1;'
                name += '/'
                if url != '/':
                    url += '/'
            else:
                icon = '&#x1F4C4;'

            data += '<a href="{}">{} {}</a><br>\n'.format(
                html.escape(url, quote=True),
                icon,
                html.escape(name),
            )
        data += '</main>\n'

        return data
