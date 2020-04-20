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

from pathlib import Path
import stat
import errno
import logging
from io import BytesIO

import boto3
import fuse

from .storage import AbstractStorage, FileProxyMixin
from .manifest.schema import Schema



class S3File:
    '''
    A file in S3 bucket.
    '''

    def __init__(self, obj_summary, uid, gid):
        self.obj_summary = obj_summary
        self.uid = uid
        self.gid = gid

        self.loaded = False
        self.modified = False
        self.obj = None
        self.buf = None

    # pylint: disable=missing-docstring

    def load(self):
        if not self.loaded:
            self.buf = BytesIO()
            self.obj = self.obj_summary.Object()
            self.obj.download_fileobj(self.buf)
            self.loaded = True

    def release(self, _flags):
        if self.modified:
            assert self.loaded
            self.buf.seek(0)
            logging.info('Uploading: %s', self.buf.getvalue())
            self.obj.upload_fileobj(self.buf)
            self.obj_summary.load()

    def fgetattr(self):
        return s3_stat(self.obj_summary, self.uid, self.gid)

    def read(self, length, offset):
        self.load()
        self.buf.seek(offset)
        return self.buf.read(length)

    def write(self, buf, offset):
        self.load()
        self.modified = True
        self.buf.seek(offset)
        return self.buf.write(buf)

    def ftruncate(self, length):
        self.load()
        self.modified = True
        return self.buf.truncate(length)


def s3_stat(obj_summary, uid, gid):
    '''Construct a stat entry for given S3 ObjectSummary.'''

    # S3 remember only last_modified, no creation or access
    timestamp = int(obj_summary.last_modified.timestamp())

    return fuse.Stat(
        st_mode=stat.S_IFREG | 0o644,
        st_nlink=1,
        st_uid=uid,
        st_gid=gid,
        st_size=obj_summary.size,
        st_atime=timestamp,
        st_mtime=timestamp,
        st_ctime=timestamp,
    )

class S3Storage(AbstractStorage, FileProxyMixin):
    '''
    Amazon S3 storage.
    '''

    SCHEMA = Schema('storage-s3')
    TYPE = 's3'

    def __init__(self, *, manifest, uid, gid, **kwds):
        super().__init__(**kwds)
        self.manifest = manifest
        self.uid = uid
        self.gid = gid

        credentials = self.manifest.fields['credentials']
        session = boto3.Session(
            aws_access_key_id=credentials['access_key'],
            aws_secret_access_key=credentials['secret_key'],
        )
        s3 = session.resource('s3')
        # pylint: disable=no-member
        self.bucket = s3.Bucket(manifest.fields['bucket'])

        self.files = {}
        self.dirs = set()
        self.refresh()

    def refresh(self):
        '''
        Refresh the file list from S3.
        '''

        self.files.clear()
        self.dirs.clear()

        for obj_summary in self.bucket.objects.all():
            obj_path = Path(obj_summary.key)
            self.files[obj_path] = obj_summary
            for parent in obj_path.parents:
                self.dirs.add(parent)

        logging.info('dirs: %s', self.dirs)
        logging.info('files: %s', self.files)

    def open(self, path, flags):
        return S3File(self.files[path], self.uid, self.gid)

    def create(self, path, flags, mode):
        self.bucket.put_object(Key=path)
        self.refresh()
        return S3File(self.files[path], self.uid, self.gid)

    def getattr(self, path):
        path = Path(path)
        if path in self.dirs:
            return fuse.Stat(
                st_mode=stat.S_IFDIR | 0o755,
                st_nlink=1,
                st_uid=self.uid,
                st_gid=self.gid,
            )
        if path in self.files:
            return s3_stat(self.files[path], self.uid, self.gid)
        return -errno.ENOENT

    def readdir(self, path):
        path = Path(path)
        for file_path in self.files:
            if file_path.parent == path:
                yield file_path.name
        for dir_path in self.dirs:
            if dir_path != path and dir_path.parent == path:
                yield dir_path.name

    def truncate(self, path, length):
        obj_summary = self.files[path]
        assert length == 0  # TODO
        obj_summary.Object().upload_fileobj(BytesIO(b''))
        obj_summary.load()

    def unlink(self, path):
        obj_summary = self.files[path]
        obj_summary.delete()
        self.refresh()
