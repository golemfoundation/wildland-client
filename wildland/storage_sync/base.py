# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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
"""
Storage syncing.
"""
# pylint: disable=no-self-use
import abc
from typing import Optional, Iterable
from pathlib import Path
from wildland.storage import StorageBackend
from ..storage_backends.base import OptionalError


class SyncError:
    """
    General class representing syncing errors.
    """


class SyncWriteError(SyncError):
    """
    Error representing write error while syncing.
    """


class SyncReadError(SyncError):
    """
    Error representing read error while syncing.
    """


class SyncConflict(SyncError):
    """
    Error representing file conflict encountered during sync.
    """
    def __init__(self, path: Path, backend1_id: str, backend2_id: str):
        self.path = path
        self.backend1_id = backend1_id
        self.backend2_id = backend2_id

    def __str__(self):
        return f'Conflict detected on {str(self.path)} in ' \
               f'storages {self.backend1_id} and {self.backend2_id}'

    def __eq__(self, other):
        if not isinstance(other, SyncConflict):
            return False

        if not self.path == other.path:
            return False

        return sorted([self.backend1_id, self.backend2_id]) ==\
            sorted([other.backend1_id, other.backend2_id])


class BaseSyncer(metaclass=abc.ABCMeta):
    """
    A class for watching changes in storages and synchronizing them across different backends.
    Syncer assumes that syncing is performed between two storages.
    """

    # TODO: any = ["*"]
    SYNCER_NAME = ""
    SOURCE_TYPES = [""]  # list of StorageBacked.TYPE s accepted as source storage
    TARGET_TYPES = [""]  # list of StorageBacked.TYPE s accepted as target storage
    ONE_SHOT = True  # is this syncer capable of performing a one-shot sync?
    UNIDIRECTIONAL = True  # is this syncer capable of performing unidirectional sync?
    REQUIRES_MOUNT = True  # does this syncer require mounting the storages?

    @classmethod
    def find_syncer(cls, source_storage_type: str, target_storage_type: str,
                    one_shot: bool, unidirectional: bool, requires_mount: bool):
        """
        Return a Syncer class that fulfills listed requirements.
        """

    def __init__(self, source_storage: StorageBackend,
                 target_storage: StorageBackend,
                 log_prefix: str,
                 source_mnt_path: Optional[Path] = None,
                 target_mnt_path: Optional[Path] = None
                 ):
        self.source_storage = source_storage
        self.target_storage = target_storage
        self.log_prefix = log_prefix
        self.source_mnt_path = source_mnt_path
        self.target_mnt_path = target_mnt_path

    def one_shot_sync(self, unidirectional: bool = False):
        """
        Perform a single (rsync-type) sync of given storages, optionally only in one direction.
        Optional.
        """
        raise OptionalError

    @abc.abstractmethod
    def start_sync(self, unidirectional: bool = False):
        """
        Start syncing given storages (register appropriate watchers etc.)
        """

    @abc.abstractmethod
    def stop_sync(self):
        """
        Stop syncing given storages, deregister watchers etc.
        """

    @abc.abstractmethod
    def is_running(self) -> bool:
        """
        Are the syncing watchers (or other processes required) running?
        """

    def is_synced(self):
        """
        Are the backends currently in sync?
        This may not be implemented by a given syncer.
        """
        raise OptionalError

    @abc.abstractmethod
    def iter_errors(self) -> Iterable[SyncError]:
        """
        Iterate over discovered syncer errors.
        """
