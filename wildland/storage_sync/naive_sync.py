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

import threading
import hashlib
import os
from typing import List, Dict, Iterable, Optional
from functools import partial
from pathlib import PurePosixPath, Path
from contextlib import suppress

from wildland.storage import StorageBackend
from wildland.storage_backends.watch import FileEvent, StorageWatcher, FileEventType
from wildland.storage_backends.base import OptionalError, HashMismatchError
from wildland.storage_sync.base import BaseSyncer, SyncConflict, SyncState,  SyncConflictEvent, \
    SyncErrorEvent
from wildland.log import get_logger

BLOCK_SIZE = 1024 ** 2

logger = get_logger('naive-sync')


class NaiveSyncer(BaseSyncer):
    """
    Naive syncer mechanism - assumes zero special capabilities of storage backends.
    """

    SYNCER_NAME = "NaiveSyncer"
    SOURCE_TYPES = ["*"]
    TARGET_TYPES = ["*"]
    CONTINUOUS = True
    ONE_SHOT = True  # this syncer is capable of performing a one-shot sync
    UNIDIRECTIONAL = True  # this syncer is capable of performing unidirectional sync
    REQUIRES_MOUNT = False  # this syncer does not require mount

    def __init__(self,
                 source_storage: StorageBackend,
                 target_storage: StorageBackend,
                 log_prefix: str,
                 source_mnt_path: Optional[Path] = None,
                 target_mnt_path: Optional[Path] = None):
        super().__init__(source_storage, target_storage, log_prefix,
                         source_mnt_path, target_mnt_path)
        self.storage_watchers: Dict[StorageBackend, StorageWatcher] = {}
        self.storage_hashes: Dict[StorageBackend, Dict[PurePosixPath, Optional[str]]] = {}
        self.lock = threading.Lock()
        self.conflicts: List[SyncConflict] = []

    def start_sync(self, unidirectional: bool = False):
        """
        Initialize watchers.
        """
        logger.debug("%s: starting file syncing.", self.log_prefix)
        # store in db what are found container/backend matches
        storages = [self.source_storage]
        if not unidirectional:
            storages.append(self.target_storage)
        with self.lock:
            for backend in storages:
                event_handler = partial(self._handle_events, backend)
                backend.request_mount()
                watcher = backend.start_watcher(handler=event_handler, ignore_own_events=True)
                self.storage_watchers[backend] = watcher

                logger.debug("%s: added watcher for storage %s.",
                             self.log_prefix, backend.backend_id)

            self.one_shot_sync(unidirectional)

    def _handle_conflict(self, storage_1, storage_2, path):
        """
        Handle conflict between two storages; currently only informs the user of a conflict.
        """
        logger.warning("%s: conflict between storages detected: storages %s and %s "
                       "differ on file %s.",
                       self.log_prefix, storage_1.backend_id, storage_2.backend_id, path)
        conflict = SyncConflict(Path(path), self.source_storage.backend_id,
                                self.target_storage.backend_id)
        self.conflicts.append(conflict)
        self.notify_event(SyncConflictEvent(str(conflict)))

    def one_shot_sync(self, unidirectional: bool = False):
        """
        Initialize watcher state, especially hashes of all objects in watched storages.
        """
        storage_dirs: Dict[StorageBackend, List[PurePosixPath]] = {}

        self.state = SyncState.ONE_SHOT
        for storage in [self.source_storage, self.target_storage]:
            self.storage_hashes[storage] = {}
            storage_dirs[storage] = []
            for path, attr in storage.walk():
                if attr.is_dir():
                    storage_dirs[storage].append(path)
                else:
                    self.storage_hashes[storage][path] = storage.get_hash(path)

        storages = [(self.source_storage, self.target_storage)]
        if not unidirectional:
            storages.append((self.target_storage, self.source_storage))

        # sync directory structure
        for backend1, backend2 in storages:
            storage_dirs1 = storage_dirs[backend1]
            storage_dirs2 = storage_dirs[backend2]

            missing_dirs = (path for path in storage_dirs1 if path not in storage_dirs2)
            for path in missing_dirs:
                logger.debug("%s: creating directory %s in storage %s",
                             self.log_prefix, path, backend2.backend_id)
                try:
                    backend2.mkdir(path)
                except (FileExistsError, NotADirectoryError):
                    self._handle_conflict(backend1, backend2, path)

        # find conflicting files
        storage_hashes_src = self.storage_hashes[self.source_storage]
        storage_hashes_tg = self.storage_hashes[self.target_storage]

        different = (path for path in storage_hashes_src
                     if path in storage_hashes_tg
                     and storage_hashes_tg[path] != storage_hashes_src[path])
        for path in different:
            self._handle_conflict(self.source_storage, self.target_storage, path)

        # find missing files
        for backend1, backend2 in storages:
            storage_hashes1 = self.storage_hashes[backend1]
            storage_hashes2 = self.storage_hashes[backend2]

            for path in storage_hashes1:
                if path not in storage_hashes2:
                    last_known_hash = backend2.retrieve_hash(path)
                    if last_known_hash and last_known_hash == storage_hashes1[path]:
                        # this file was deleted while offline, we can safely delete it in the other
                        # backend too
                        try:
                            logger.debug("%s: removing file %s in backend %s",
                                         self.log_prefix, path, backend1.backend_id)
                            backend1.unlink(path)
                        except (FileNotFoundError, OptionalError, PermissionError) as ex:
                            logger.warning(
                                "%s: cannot remove file %s in backend %s, error: %s",
                                self.log_prefix, path, backend1.backend_id, str(ex))
            missing_files = (path for path in storage_hashes1 if path not in storage_hashes2)
            for path in missing_files:
                self._sync_file(backend1, backend2, path)

        # this won't overwrite an ERROR state, see the property setter
        self.state = SyncState.SYNCED

    def _sync_file(self, source_storage: StorageBackend, target_storage: StorageBackend,
                   path: PurePosixPath):
        """
        Sync a file at path from source_storage to target_storage.
        """
        logger.debug("%s: attempting to sync file %s in storages %s and %s",
                     self.log_prefix, path, source_storage.backend_id,
                     target_storage.backend_id)
        try:
            source_hash = source_storage.get_hash(path)
        except (FileNotFoundError, IsADirectoryError):
            # file deleted before we managed to get to it or someone quickly changed the file we
            # wanted to copy into a directory; abort, let the create directory event handle this
            if path in self.storage_hashes[source_storage]:
                del self.storage_hashes[source_storage][path]
            return
        old_source_hash = self.storage_hashes[source_storage].get(path)
        self.storage_hashes[source_storage][path] = source_hash

        try:
            target_hash = target_storage.get_hash(path)
        except FileNotFoundError:
            target_hash = None
        except IsADirectoryError:
            # Attempting to sync a file with a dir. This can never go well.
            self._handle_conflict(source_storage, target_storage, path)
            return

        old_target_hash = self.storage_hashes[target_storage].get(path)

        logger.debug("%s: file %s in source storage %s has hash %.10s, previous known "
                     "hash %.10s; in target storage %s has hash %.10s, previous known hash %.10s",
                     self.log_prefix, path, source_storage.backend_id, source_hash,
                     old_source_hash, target_storage.backend_id, target_hash, old_target_hash)

        if old_target_hash and old_source_hash and \
                old_target_hash != old_source_hash and target_hash is not None:
            logger.warning("%s: known conflict on file %s in storages %s and %s "
                           "prevents syncing.",
                           self.log_prefix, path, source_storage.backend_id,
                           target_storage.backend_id)
            return

        if target_hash == source_hash:
            logger.debug("%s: syncing of file %s in storages %s and %s unnecessary, "
                         "as file already exists",
                         self.log_prefix, path, source_storage.backend_id,
                         target_storage.backend_id)
            return

        if old_target_hash and target_hash and target_hash != old_target_hash:
            self._handle_conflict(source_storage, target_storage, path)
            return

        hasher = hashlib.sha256()

        if not target_hash:
            try:
                target_file_obj = target_storage.create(path, os.O_CREAT | os.O_WRONLY)
            except OptionalError:
                logger.warning("%s: cannot sync file %s to storage %s. "
                               "Operation not supported by storage backend.",
                               self.log_prefix, path, target_storage.backend_id)
                return
            except NotADirectoryError:
                # Can occur if there's a file/directory conflict and we are trying to sync a file
                # located in a directory that's a file in another storage
                self._handle_conflict(source_storage, target_storage, path)
                return
        else:
            try:
                target_file_obj = target_storage.open_for_safe_replace(path, os.O_RDWR, target_hash)
            except OptionalError:
                try:
                    target_file_obj = target_storage.open(path, os.O_WRONLY)
                except OptionalError:
                    logger.warning("%s: cannot sync file %s to storage %s. "
                                   "Operation not supported by storage backend.",
                                   self.log_prefix, path, target_storage.backend_id)
                    return
            except HashMismatchError:
                logger.warning("%s: unexpected hash for object %s in storage %s found, "
                               "cannot sync.", self.log_prefix, path, target_storage.backend_id)
                return

        try:
            with target_file_obj, source_storage.open(path, os.O_RDONLY) as source_file_obj:

                target_file_obj.ftruncate(0)
                offset = 0

                while True:
                    data = source_file_obj.read(BLOCK_SIZE, offset)
                    if not data:
                        break
                    write_len = target_file_obj.write(data, offset)
                    offset += write_len
                    hasher.update(data[:write_len])
        except HashMismatchError:
            logger.warning("%s: unexpected hash for object %s in storage %s found, "
                           "cannot sync.", self.log_prefix, path, target_storage.backend_id)
            return

        resulting_hash = hasher.hexdigest()

        self.storage_hashes[source_storage][path] = resulting_hash
        self.storage_hashes[target_storage][path] = resulting_hash

    def _sync_dir(self, source_storage: StorageBackend, target_storage: StorageBackend,
                  path: PurePosixPath):
        """
        Sync whole directory at path and its contents from source_storage to target_storage.
        """
        logger.debug("%s: attempting to sync directory %s in storages %s "
                     "and %s", self.log_prefix, path, source_storage.backend_id,
                     target_storage.backend_id)
        for file_path, attr in source_storage.walk(path):
            if attr.is_dir():
                with suppress(FileExistsError):
                    target_storage.mkdir(file_path)
            else:
                self._sync_file(source_storage, target_storage, file_path)

    def _remove_whole_dir(self, storage: StorageBackend, dir_path):
        """
        Recursively remove whole directory, its contents and corresponding hashes.
        """
        logger.debug("%s: attempting to remove directory %s in storages %s",
                     self.log_prefix, dir_path, storage.backend_id)
        paths_to_remove = sorted(
            [(path, attr.is_dir()) for path, attr in storage.walk(dir_path)],
            key=lambda x: x[0], reverse=True)
        for path, is_dir in paths_to_remove:
            if is_dir:
                storage.rmdir(path)
            else:
                target_hash = storage.get_hash(path)
                if target_hash != self.storage_hashes[storage][path]:
                    logger.warning("%s: unexpected hash for object %s in storage %s "
                                   "found, not removing.", self.log_prefix, path,
                                   storage.backend_id)
                    return
                storage.unlink(path)
            if path in self.storage_hashes[storage]:
                del self.storage_hashes[storage][path]

        storage.rmdir(dir_path)

    def _remove_subdir_paths(self, storage: StorageBackend, path: PurePosixPath):
        """
        Helper function: removed from hash dictionary hashes of all subdirectory objects,
        if for some reason we did not receive separate event for each and every one of them on
        delete.
        """
        if path in self.storage_hashes[storage]:
            del self.storage_hashes[storage][path]
        sub_objects = [p for p in self.storage_hashes[storage] if
                       str(p).startswith(str(path) + '/')]
        for p in sub_objects:
            del self.storage_hashes[storage][p]

    def _already_removed(self, target_storage: StorageBackend, path: PurePosixPath):
        """
        Helper for cleanup of already removed objects.
        """
        logger.warning("%s: removal of %s from storage %s failed: file already"
                       " removed.", self.log_prefix, path, target_storage.backend_id)
        self._remove_subdir_paths(target_storage, path)
        if path in self.storage_hashes[target_storage]:
            del self.storage_hashes[target_storage][path]

    def _remove_object(self, source_storage: StorageBackend, target_storage: StorageBackend,
                       path: PurePosixPath, source_is_dir: bool, old_source_hash=None):
        """
        Remove an object (dir or file) in path in target_storage, if it is the object
        the syncer expected to find there (based on hash).
        Must give source_storage so that conflict handling knows where the conflict is and
        must pass source_is_dir boolean parameter, because there's no way to guess what was in
        source_storage before it was deleted.
        To avoid problems with syncing multiple containers, should provide old source hash.
        """
        logger.debug("%s: attempting to sync file %s removed from storage %s in "
                     "storage %s", self.log_prefix, path,
                     source_storage.backend_id, target_storage.backend_id)
        self._remove_subdir_paths(source_storage, path)
        try:
            target_is_dir = target_storage.getattr(path).is_dir()
        except FileNotFoundError:
            self._already_removed(target_storage, path)
            return

        if target_is_dir != source_is_dir:
            self._handle_conflict(source_storage, target_storage, path)
            return

        if target_is_dir:
            self._remove_whole_dir(target_storage, path)
        else:
            try:
                target_hash = target_storage.get_hash(path)
            except FileNotFoundError:
                self._already_removed(target_storage, path)
                return

            source_hash = old_source_hash if old_source_hash else \
                self.storage_hashes[target_storage][path]

            if target_hash != source_hash:
                self._handle_conflict(source_storage, target_storage, path)
                return

            try:
                target_storage.unlink(path)
            except FileNotFoundError:
                self._already_removed(target_storage, path)
                return

            if path in self.storage_hashes[target_storage]:
                del self.storage_hashes[target_storage][path]
            return

    def _create_object(self, source_storage: StorageBackend, target_storage: StorageBackend,
                       path: PurePosixPath):
        """
        Create an object (file or dir) in path in target_storage, based on existing object in
        source_storage.
        """
        logger.debug("%s: attempting to sync file %s created in storage %s into "
                     "storage %s", self.log_prefix, path,
                     source_storage.backend_id, target_storage.backend_id)
        try:
            is_dir = source_storage.getattr(path).is_dir()
        except FileNotFoundError:
            # the source file was deleted before we managed to reference it; abort
            return
        if is_dir:
            try:
                target_storage.mkdir(path)
            except FileExistsError:
                logger.debug("%s: creation of directory %s in storage %s failed: file "
                             "already exists.", self.log_prefix, path,
                             target_storage.backend_id)
            self._sync_dir(source_storage, target_storage, path)
        else:
            self._sync_file(source_storage, target_storage, path)

    def _handle_events(self, source_storage: StorageBackend, events: List[FileEvent]):
        """
        Process storage events originating from a given source_storage.
        """
        self.state = SyncState.RUNNING
        with self.lock:
            for event in events:
                try:
                    logger.debug("%s: handling event %s for object %s occurring in "
                                 "storage %s", self.log_prefix, event.type, event.path,
                                 source_storage.backend_id)

                    obj_path = event.path

                    if event.type == FileEventType.DELETE:
                        old_source_hash = self.storage_hashes[source_storage].get(obj_path)
                        is_dir = obj_path not in self.storage_hashes[source_storage]

                        for target_storage in self.storage_watchers:
                            if target_storage == source_storage:
                                continue

                            old_target_hash = self.storage_hashes[target_storage].get(obj_path)

                            if old_source_hash == old_target_hash:
                                self._remove_object(source_storage, target_storage, obj_path,
                                                    is_dir, old_source_hash)
                            else:
                                logger.warning(
                                    "%s: conflict resolved via removal of file at %s from "
                                    "storage %s; version from %s is now authoritative.",
                                    self.log_prefix, obj_path,
                                    source_storage.backend_id, target_storage.backend_id)
                                self._create_object(target_storage, source_storage, obj_path)
                    else:
                        for target_storage in self.storage_watchers:
                            if target_storage == source_storage:
                                continue
                            if event.type == FileEventType.CREATE:
                                self._create_object(source_storage, target_storage, obj_path)
                            elif event.type == FileEventType.MODIFY:
                                self._sync_file(source_storage, target_storage, obj_path)
                except Exception as e:
                    self.notify_event(SyncErrorEvent(str(e)))
                    self.state = SyncState.ERROR
                    break

        # this won't overwrite an ERROR state, see the property setter
        self.state = SyncState.SYNCED

    def stop_sync(self):
        """
        Stop all watchers cleanly.
        """
        logger.debug("%s: stopping file syncing.", self.log_prefix)
        for backend in self.storage_watchers:
            backend.stop_watcher()
            backend.request_unmount()
        self.conflicts.clear()
        self.storage_watchers.clear()
        logger.debug("%s: file syncing stopped.", self.log_prefix)
        self.state = SyncState.STOPPED

    def iter_conflicts(self) -> Iterable[SyncConflict]:
        for conflict in self.conflicts:
            yield conflict

    def iter_conflicts_force(self) -> Iterable[SyncConflict]:
        for path, attr in self.source_storage.walk():
            try:
                attr2 = self.target_storage.getattr(path)
            except (FileNotFoundError, NotADirectoryError):
                continue

            if attr.is_dir() != attr2.is_dir():
                yield SyncConflict(Path(path), self.source_storage.backend_id,
                                   self.target_storage.backend_id)

            if attr.is_dir():
                continue

            if self.source_storage.get_hash(path) != self.target_storage.get_hash(path):
                yield SyncConflict(Path(path), self.source_storage.backend_id,
                                   self.target_storage.backend_id)
