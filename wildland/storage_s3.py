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

    def __init__(self, obj, uid, gid):
        self.obj = obj
        self.uid = uid
        self.gid = gid
        self.buf = None
        self.modified = False

    # pylint: disable=missing-docstring

    def load(self):
        if not self.buf:
            self.buf = BytesIO()
            self.obj.download_fileobj(self.buf)

    def release(self, _flags):
        if self.modified:
            self.buf.seek(0)
            logging.info('Uploading: %s', self.buf.getvalue())
            self.obj.upload_fileobj(self.buf)
            self.obj.reload()

    def fgetattr(self):
        return s3_stat(self.obj, self.uid, self.gid)

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


def s3_stat(obj, uid, gid):
    '''Construct a stat entry for given S3 object.'''

    return fuse.Stat(
        st_mode=stat.S_IFREG | 0o644,
        st_nlink=1,
        st_uid=uid,
        st_gid=gid,
        st_size=obj.content_length
    )

class S3Storage(AbstractStorage, FileProxyMixin):
    '''
    Amazon S3 storage.

    Currently expects the access keys to be configured globally:
    install ``awscli``, and run ``aws configure``.
    '''

    SCHEMA = Schema('storage-s3')
    TYPE = 's3'

    def __init__(self, *, manifest, uid, gid, **kwds):
        super().__init__(**kwds)
        self.manifest = manifest
        self.uid = uid
        self.gid = gid

        s3 = boto3.resource('s3')
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

        for obj in self.bucket.objects.all():
            obj_path = Path(obj.key)
            self.files[obj_path] = self.bucket.Object(obj.key)
            for parent in obj_path.parents:
                self.dirs.add(parent)

        logging.info('dirs: %s', self.dirs)
        logging.info('files: %s', self.files)

    def open(self, path, flags):
        return S3File(self.files[path], self.uid, self.gid)

    def create(self, path, flags, mode):
        obj = self.bucket.put_object(Key=str(path))
        self.refresh()
        return S3File(obj, self.uid, self.gid)

    def release(self, _path, flags, obj):
        # pylint: disable=missing-docstring
        try:
            return obj.release(flags)
        finally:
            self.refresh()

    def getattr(self, path):
        path = Path(path)
        if path in self.dirs:
            return fuse.Stat(
                st_mode=stat.S_IFDIR | 0o755,
                st_nlink=1, # TODO
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
        obj = self.files[path]
        assert length == 0  # TODO
        obj.upload_fileobj(BytesIO(b''))
        self.refresh()

    def unlink(self, path):
        obj = self.files[path]
        obj.delete()
        self.refresh()
