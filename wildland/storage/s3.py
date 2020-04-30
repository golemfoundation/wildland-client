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
from typing import Iterable, Tuple, Set
import mimetypes
import logging

import boto3

from .cached import CachedStorage, Info
from ..manifest.schema import Schema


logger = logging.getLogger('storage-s3')


class S3Storage(CachedStorage):
    '''
    Amazon S3 storage.
    '''

    SCHEMA = Schema('storage-s3')
    TYPE = 's3'

    def __init__(self, *, manifest, **kwds):
        super().__init__(manifest=manifest, **kwds)

        credentials = manifest.fields['credentials']
        session = boto3.Session(
            aws_access_key_id=credentials['access_key'],
            aws_secret_access_key=credentials['secret_key'],
        )
        s3 = session.resource('s3')
        # pylint: disable=no-member
        self.bucket = s3.Bucket(manifest.fields['bucket'])

        # Persist created directories between refreshes. This is because S3
        # doesn't have information about directories, andwe might want to
        # create/remove them manually.
        self.s3_dirs: Set[PurePosixPath] = set()

        mimetypes.init()

    @staticmethod
    def info(obj) -> Info:
        '''
        Convert Amazon's Obj or ObjSummary to Info.
        '''
        timestamp = int(obj.last_modified.timestamp())
        if hasattr(obj, 'size'):
            size = obj.size
        else:
            size = obj.content_length
        return Info(is_dir=False, size=size, timestamp=timestamp)

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        for obj_summary in self.bucket.objects.all():
            obj_path = PurePosixPath(obj_summary.key)
            yield obj_path, self.info(obj_summary)
            for parent in obj_path.parents:
                self.s3_dirs.add(parent)

        for dir_path in self.s3_dirs:
            yield dir_path, Info(is_dir=True)

    @staticmethod
    def get_content_type(path: PurePosixPath) -> str:
        '''
        Guess the right content type for given path.
        '''

        content_type, _encoding = mimetypes.guess_type(path.name)
        return content_type or 'application/octet-stream'

    def backend_create_file(self, path: PurePosixPath) -> Info:
        content_type = self.get_content_type(path)
        logger.debug('creating %s with content type %s', path, content_type)
        obj = self.bucket.put_object(Key=str(path), ContentType=content_type)
        return self.info(obj)

    def backend_create_dir(self, path: PurePosixPath) -> Info:
        self.s3_dirs.add(path)
        return Info(is_dir=True)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        buf = BytesIO()
        obj = self.bucket.Object(str(path))
        obj.download_fileobj(buf)
        return buf.getvalue()

    def backend_save_file(self, path: PurePosixPath, data: bytes) -> Info:
        # Set the Content-Type again, otherwise it will get overwritten with
        # application/octet-stream.
        content_type = self.get_content_type(path)
        obj = self.bucket.Object(str(path))
        obj.upload_fileobj(BytesIO(data),
                           ExtraArgs={'ContentType': content_type})
        return self.info(obj)

    def backend_delete_file(self, path: PurePosixPath):
        self.bucket.Object(str(path)).delete()

    def backend_delete_dir(self, path: PurePosixPath):
        self.s3_dirs.remove(path)
