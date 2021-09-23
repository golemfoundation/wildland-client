# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Storage syncing.
"""
# pylint: disable=no-self-use
import abc
import json
from enum import Enum
from typing import Optional, Iterable, Dict, Type, List, Callable, Any
from pathlib import Path
from wildland.storage import StorageBackend
from ..storage_backends.base import OptionalError
from ..exc import WildlandError


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


class SyncState(Enum):
    """
    Current state of a syncer.
    """
    STOPPED = 1  # no sync running
    RUNNING = 2  # continuous sync running with pending events (storages are not synced)
    SYNCED = 3  # continuous sync running with no pending events (storages are synced)
    ONE_SHOT = 4  # one-shot sync running
    ERROR = 5  # error/exception occured during sync, process aborted

    def __str__(self):
        return str(self.name)


class SyncEvent(metaclass=abc.ABCMeta):
    """
    Base class for sync events.
    """
    type: str
    value: str
    job_id: Optional[str]

    @staticmethod
    def fromJSON(s: str) -> 'SyncEvent':
        """
        Deserialize from JSON.
        """
        obj = json.loads(s)
        event: SyncEvent
        if obj['type'] == SyncStateEvent.type:
            event = SyncStateEvent.fromJSON(s)
        elif obj['type'] == SyncConflictEvent.type:
            event = SyncConflictEvent.fromJSON(s)
        elif obj['type'] == SyncErrorEvent.type:
            event = SyncErrorEvent.fromJSON(s)
        else:
            raise WildlandError('Invalid sync event type')

        if 'job_id' in obj.keys():
            event.job_id = obj['job_id']

        return event

    def toJSON(self) -> str:
        """
        Serialize to JSON.
        """
        # can't use json.dumps(self.__dict__) because that misses fields not initialized
        # in __init__
        if self.job_id:
            return f'{{"type" : "{self.type}", "value": "{self.value}", "job_id": "{self.job_id}"}}'

        return f'{{"type" : "{self.type}", "value": "{self.value}"}}'

    def __repr__(self):
        if self.job_id:
            return f"<{self.type}: {self.value}> ({self.job_id})"

        return f"<{self.type}: {self.value}>"

    def __str__(self):
        return self.__repr__()

    def __eq__(self, other):
        if not issubclass(type(other), SyncEvent):
            return False

        if self.type != other.type:
            return False

        if self.value != other.value:
            return False

        if self.job_id and self.job_id != other.job_id:
            return False

        return True


class SyncStateEvent(SyncEvent):
    """
    State change event.
    """
    type = 'state'

    @staticmethod
    def fromJSON(s: str) -> 'SyncStateEvent':
        """
        Deserialize from JSON.
        """
        obj = json.loads(s)
        assert obj['type'] == SyncStateEvent.type
        return SyncStateEvent(SyncState[obj['value']])

    def __init__(self, state: SyncState, job_id: Optional[str] = None):
        self.state = state
        self.value = str(self.state.name)
        self.job_id = job_id


class SyncConflictEvent(SyncEvent):
    """
    New conflict.
    """
    type = 'conflict'

    @staticmethod
    def fromJSON(s: str) -> 'SyncConflictEvent':
        """
        Deserialize from JSON.
        """
        obj = json.loads(s)
        assert obj['type'] == SyncConflictEvent.type
        return SyncConflictEvent(obj['value'])

    def __init__(self, message: str, job_id: Optional[str] = None):
        self.value = message
        self.job_id = job_id


class SyncErrorEvent(SyncEvent):
    """
    Sync error event.
    """
    type = 'error'

    @staticmethod
    def fromJSON(s: str) -> 'SyncErrorEvent':
        """
        Deserialize from JSON.
        """
        obj = json.loads(s)
        assert obj['type'] == SyncErrorEvent.type
        return SyncErrorEvent(obj['value'])

    def __init__(self, message: str, job_id: Optional[str] = None):
        self.value = message
        self.job_id = job_id


class BaseSyncer(metaclass=abc.ABCMeta):
    """
    A class for watching changes in storages and synchronizing them across different backends.
    Syncer assumes that syncing is performed between two storages.
    """

    # SOURCE_TYPES AND TARGET_TYPES are lists of StorageBacked.TYPEs accepted as source/target
    # storage respectively. For "any storage type" use ["*"].
    SYNCER_NAME = ""
    SOURCE_TYPES: List[str] = []
    TARGET_TYPES: List[str] = []
    CONTINUOUS = False  # is this syncer capable of performing continuous sync?
    ONE_SHOT = False  # is this syncer capable of performing a one-shot sync?
    UNIDIRECTIONAL = False  # is this syncer capable of performing unidirectional sync?
    REQUIRES_MOUNT = False  # does this syncer require mounting the storages?

    _types: Dict[str, Type['BaseSyncer']] = {}

    @classmethod
    def find_syncer(cls, source_storage_type: str, target_storage_type: str,
                    one_shot: bool, continuous: bool, unidirectional: bool, requires_mount: bool):
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
        self._state = SyncState.STOPPED
        self._event_callback: Optional[Callable] = None
        self._event_context: Any = None

    def one_shot_sync(self, unidirectional: bool = False):
        """
        Perform a single (rsync-type) sync of given storages, optionally only in one direction.
        This has to be implemented if ONE_SHOT == True
        """
        raise OptionalError

    def start_sync(self, unidirectional: bool = False):
        """
        Start syncing given storages (register appropriate watchers etc.)
        This has to be implemented if CONTINUOUS == True
        """
        raise OptionalError

    def stop_sync(self):
        """
        Stop syncing given storages, de-register watchers etc.
        This has to be implemented if CONTINUOUS == True
        """
        raise OptionalError

    def state(self) -> SyncState:
        """
        Current state of the syncer.
        """
        return self._state

    def set_event_callback(self, callback: Callable[[SyncEvent, Any], None], context: Any = None):
        """
        Set a callback that will be notified of sync events.
        :param callback Handler that will be called on an event.
        :param context User data that will be passed to the callback along with the event.
        """
        self._event_callback = callback
        self._event_context = context

    def notify_event(self, event: SyncEvent):
        """
        Notifies registered event callback (if any).
        """
        if self._event_callback:
            self._event_callback(event, self._event_context)

    def set_state(self, state: SyncState):
        """
        Set syncer state and automatically notify registered event callback.
        """
        self._state = state
        self.notify_event(SyncStateEvent(state))

    @abc.abstractmethod
    def iter_errors(self) -> Iterable[SyncError]:
        """
        Iterate over discovered syncer errors.
        """

    @abc.abstractmethod
    def iter_conflicts(self) -> Iterable[SyncConflict]:
        """
        Iterate over discovered sync conflicts.
        """

    @classmethod
    def types(cls) -> Dict[str, Type['BaseSyncer']]:
        """
        Lazily initialized type -> storage class mapping.
        """
        if not cls._types:
            # pylint: disable=import-outside-toplevel,cyclic-import
            from .dispatch import get_storage_syncers
            cls._types = get_storage_syncers()

        return cls._types

    @classmethod
    def type_matches(cls, source_storage_type: str, target_storage_type: str,
                     one_shot: bool, continuous: bool, unidirectonal: bool,
                     can_require_mount: bool) -> bool:
        """
        Check if a given Syncer class fits given requirements.
        """
        if one_shot and not cls.ONE_SHOT:
            # if we require one-shot support, the class must support it
            return False
        if unidirectonal and not cls.UNIDIRECTIONAL:
            # if we require unidirectional sync, the class must support
            return False
        if continuous and not cls.CONTINUOUS:
            # if we require continuous sync, the class must support
            return False
        if not can_require_mount and cls.REQUIRES_MOUNT:
            # if we are unable to mount, the class must not require it
            return False
        if source_storage_type not in cls.SOURCE_TYPES and \
                cls.SOURCE_TYPES != ["*"]:
            return False
        if target_storage_type not in cls.TARGET_TYPES and \
                cls.TARGET_TYPES != ["*"]:
            return False
        return True

    @classmethod
    def from_storages(cls, source_storage: StorageBackend, target_storage: StorageBackend,
                      log_prefix: str, unidirectional: bool, one_shot: bool, continuous: bool,
                      can_require_mount: bool, source_mnt_path: Optional[Path] = None,
                      target_mnt_path: Optional[Path] = None) -> 'BaseSyncer':
        """
        Construct a Syncer object based on listed requirements and objects.
        :param source_storage: source storage object
        :param target_storage: target storage object
        :param log_prefix: prefix for logging sync events
        :param unidirectional: is unidirectional sync support required
        :param one_shot: is one-shot sync support required
        :param continuous: is continuous sync support required
        :param can_require_mount: can mounting storages be required
        :param source_mnt_path: path to source storage mount
        :param target_mnt_path: path to target storage mount
        :return: instantiated syncer class
        """
        candidate_classes: List[Type[BaseSyncer]] = []

        for syncer_class in cls.types().values():
            if syncer_class.type_matches(source_storage.TYPE, target_storage.TYPE,
                                         one_shot, continuous, unidirectional, can_require_mount):
                candidate_classes.append(syncer_class)

        if not candidate_classes:
            raise WildlandError('Failed to find a matching syncer. ')

        # prioritize classes with exact SOURCE/TARGET type match above those with wildcard ('*')
        # match
        candidate_classes.sort(key=lambda x: (x.SOURCE_TYPES + x.TARGET_TYPES).count('*'))
        return candidate_classes[0](source_storage=source_storage, target_storage=target_storage,
                                    log_prefix=log_prefix, source_mnt_path=source_mnt_path,
                                    target_mnt_path=target_mnt_path)
