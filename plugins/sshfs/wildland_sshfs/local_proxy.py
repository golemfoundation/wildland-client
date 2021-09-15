# Wildland Project
#
# The contents of this file is primarily inspired by
# Pawel Peregud's work on encrypted backend.

"""
Definition of LocalProxy storage backend base class.
"""

import abc
import uuid

from os import rmdir
from tempfile import mkdtemp
from typing import Optional
from pathlib import PurePosixPath
from wildland.storage_backends.base import StorageBackend, File
from wildland.storage_backends.local import LocalStorageBackend
from wildland.log import get_logger

logger = get_logger('local-proxy')


class LocalProxy(StorageBackend):
    """
    An abstract base class for implementation of proxy backends
    which expose exposing locally mounted filesystems
    as Wildland storage.
    """

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.inner_mount_point: Optional[PurePosixPath] = None
        self.local: Optional[StorageBackend] = None
        self.owner = self.params['owner']

    def open(self, path: PurePosixPath, flags: int) -> File:
        assert self.local
        return self.local.open(path, flags)

    def create(self, path: PurePosixPath, flags: int, mode: int=0o666):
        assert self.local
        return self.local.create(path, flags, mode)

    def mount(self):
        """
        mount the file system
        """
        # Ensure mount point for inner file system
        mountid = str(uuid.uuid4())
        self.inner_mount_point = PurePosixPath(mkdtemp(suffix=mountid))

        backend_params = { 'location': self.inner_mount_point,
                           'type': 'local',
                           'owner': self.owner,
                           # This backend just exposes "inner filesystem"
                           # which will be mounted by `mount_inner_fs()`
                           # call. Whether user can access the data
                           # depends on the access rules of actual
                           # filesystem being mounted, so the below setting
                           # is safe.
                           'is-local-owner': True,
                           'backend-id': str(uuid.uuid4())
                          }
        self.local = LocalStorageBackend(params=backend_params)

        # and do actually mount it
        self.mount_inner_fs(self.inner_mount_point)

        self.local.request_mount()
        logger.debug("inner file system mounted at: %s",
                     self.inner_mount_point)

    def unmount(self):
        """
        unmount the file system
        """
        assert self.inner_mount_point
        logger.debug("unmounting inner filesystem at: %s",
                     self.inner_mount_point)
        assert self.local
        self.local.request_unmount()
        self.unmount_inner_fs(self.inner_mount_point)
        rmdir(self.inner_mount_point)


    @abc.abstractmethod
    def mount_inner_fs(self, path: PurePosixPath) -> None:
        """
        Called to mount inner filesystem at given path.
        """

    @abc.abstractmethod
    def unmount_inner_fs(self, path: PurePosixPath) -> None:
        """
        Called to unmount inner filesystem.
        """

    def getattr(self, path: PurePosixPath):
        assert self.local
        return self.local.getattr(path)

    def readdir(self, path: PurePosixPath):
        assert self.local
        return self.local.readdir(path)

    def truncate(self, path: PurePosixPath, length: int) -> None:
        assert self.local
        return self.local.truncate(path, length)

    def unlink(self, path: PurePosixPath):
        assert self.local
        return self.local.unlink(path)

    def mkdir(self, path: PurePosixPath, mode: int = 0o777) -> None:
        assert self.local
        return self.local.mkdir(path, mode)

    def rmdir(self, path: PurePosixPath) -> None:
        assert self.local
        return self.local.rmdir(path)

    def chmod(self, path: PurePosixPath, mode: int) -> None:
        assert self.local
        return self.local.chmod(path, mode)

    def chown(self, path: PurePosixPath, uid: int, gid: int) -> None:
        assert self.local
        return self.local.chown(path, uid, gid)

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        assert self.local
        return self.local.rename(move_from, move_to)

    def utimens(self, path: PurePosixPath, atime, mtime) -> None:
        assert self.local
        return self.local.utimens(path, atime, mtime)
