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
from io import BytesIO
from typing import Iterable, Tuple, Set

import boto3
import fuse

from .cached import CachedStorage, Info
from ..manifest.schema import Schema


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
        self.s3_dirs: Set[Path] = set()

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

    def backend_info_all(self) -> Iterable[Tuple[Path, Info]]:
        for obj_summary in self.bucket.objects.all():
            obj_path = Path(obj_summary.key)
            yield obj_path, self.info(obj_summary)
            for parent in obj_path.parents:
                self.s3_dirs.add(parent)

        for dir_path in self.s3_dirs:
            yield dir_path, Info(is_dir=True)

    def backend_create_file(self, path: Path) -> Info:
        obj = self.bucket.put_object(Key=str(path))
        return self.info(obj)

    def backend_create_dir(self, path: Path) -> Info:
        self.s3_dirs.add(path)
        return Info(is_dir=True)

    def backend_load_file(self, path: Path) -> bytes:
        buf = BytesIO()
        obj = self.bucket.Object(str(path))
        obj.download_fileobj(buf)
        return buf.getvalue()

    def backend_save_file(self, path: Path, data: bytes) -> Info:
        obj = self.bucket.Object(str(path))
        obj.upload_fileobj(BytesIO(data))
        return self.info(obj)

    def backend_delete_file(self, path: Path):
        self.bucket.Object(str(path)).delete()

    def backend_delete_dir(self, path: Path):
        self.s3_dirs.remove(path)
