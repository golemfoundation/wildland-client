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

import threading
import logging
import hashlib
import os
from typing import List, Dict, Iterable
from functools import partial
from itertools import combinations, permutations
from pathlib import PurePosixPath
from contextlib import suppress
from .storage import StorageBackend
from .storage_backends.watch import FileEvent, StorageWatcher
from .storage_backends.base import OptionalError, HashMismatchError

BLOCK_SIZE = 1024 ** 2

logger = logging.getLogger('sync')


class Syncer:
    """
    A class for watching changes in storages and synchronizing them across different backends.
    """
    def __init__(self, storages: Iterable[StorageBackend], container_name: str,
                 config_dir: str = None):
        self.storage_watchers: Dict[StorageBackend, StorageWatcher] = {}
        self.storage_hashes: Dict[StorageBackend, Dict[PurePosixPath, str]] = {}
        self.container_name = container_name
        self.storages = storages
        self.lock = threading.Lock()
        self.initial_syncing = True
        self.config_dir = config_dir

    def start_syncing(self):
        """
        Initialize watchers.
        """
        logger.debug("Container %s: starting file syncing.", self.container_name)
        # store in db what are found container/backend matches
        with self.lock:
            for backend in self.storages:
                if self.config_dir:
                    backend.set_config_dir(self.config_dir)
                event_handler = partial(self.sync_storages, backend)
                backend.request_mount()
                watcher = backend.start_watcher(handler=event_handler, ignore_own_events=True)
                self.storage_watchers[backend] = watcher

                logger.debug("Container %s: added watcher for storage %s.",
                             self.container_name, backend.backend_id)

            self.init_state()

    def handle_conflict(self, storage_1, storage_2, path):
        """
        Handle conflict between two storages; currently only informs the user of a conflict.
        """
        logger.warning("Container %s: conflict between storages detected: storages %s and %s "
                       "differ on file %s.",
                       self.container_name, storage_1.backend_id, storage_2.backend_id, path)

    def init_state(self):
        """
        Initialize watcher state, especially hashes of all objects in watched storages.
        """
        storage_dirs: Dict[StorageBackend, List[PurePosixPath]] = {}

        for storage in self.storage_watchers:
            self.storage_hashes[storage] = {}
            storage_dirs[storage] = []
            for path, attr in storage.walk():
                if attr.is_dir():
                    storage_dirs[storage].append(path)
                else:
                    self.storage_hashes[storage][path] = storage.get_hash(path)

        # sync directory structure
        for (backend1, storage_dirs1), (backend2, storage_dirs2) \
                in permutations(storage_dirs.items(), 2):
            missing_dirs = (path for path in storage_dirs1 if path not in storage_dirs2)
            for path in missing_dirs:
                logger.debug("Container %s: creating directory %s in storage %s",
                             self.container_name, path, backend2.backend_id)
                try:
                    backend2.mkdir(path)
                except (FileExistsError, NotADirectoryError):
                    self.handle_conflict(backend1, backend2, path)

        # find conflicting files
        for (backend_1, storage_hashes1), (backend_2, storage_hashes2) \
                in combinations(self.storage_hashes.items(), 2):
            different = (path for path in storage_hashes1
                         if path in storage_hashes2
                         and storage_hashes2[path] != storage_hashes1[path])
            for path in different:
                self.handle_conflict(backend_1, backend_2, path)

        # find missing files
        for (backend_1, storage_hashes1), (backend_2, storage_hashes2) \
                in permutations(self.storage_hashes.items(), 2):
            for path in storage_hashes1:
                if path not in storage_hashes2:
                    last_known_hash = backend_2.retrieve_hash(path)
                    if last_known_hash and last_known_hash == storage_hashes1[path]:
                        # this file was deleted while offline, we can safely delete it in the other
                        # backend too
                        try:
                            logger.debug("Container %s: removing file %s in backend %s",
                                         self.container_name, path, backend_1.backend_id)
                            backend_1.unlink(path)
                        except (FileNotFoundError, OptionalError, PermissionError) as ex:
                            logger.warning(
                                "Container %s: cannot remove file %s in backend %s, error: %s",
                                self.container_name, path, backend_1.backend_id, str(ex))
            missing_files = (path for path in storage_hashes1 if path not in storage_hashes2)
            for path in missing_files:
                self.sync_file(backend_1, backend_2, path)

    def sync_file(self, source_storage: StorageBackend, target_storage: StorageBackend,
                  path: PurePosixPath):
        """
        Sync a file at path from source_storage to target_storage.
        """
        logger.debug("Container %s: attempting to sync file %s in storages %s and %s",
                     self.container_name, path, source_storage.backend_id, target_storage.backend_id)
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
            self.handle_conflict(source_storage, target_storage, path)
            return

        old_target_hash = self.storage_hashes[target_storage].get(path)

        logger.debug("Container %s: file %s in source storage %s has hash %.10s, previous known "
                     "hash %.10s; in target storage %s has hash %.10s, previous known hash %.10s",
                     self.container_name, path, source_storage.backend_id, source_hash,
                     old_source_hash, target_storage.backend_id, target_hash, old_target_hash)

        if old_target_hash and old_source_hash and \
                old_target_hash != old_source_hash and target_hash is not None:
            logger.warning("Container %s: known conflict on file %s in storages %s and %s "
                           "prevents syncing.",
                           self.container_name, path, source_storage.backend_id, target_storage.backend_id)
            return

        if target_hash == source_hash:
            logger.debug("Container %s: syncing of file %s in storages %s and %s unnecessary, "
                         "as file already exists",
                         self.container_name, path, source_storage.backend_id, target_storage.backend_id)
            return

        if old_target_hash and target_hash and target_hash != old_target_hash:
            self.handle_conflict(source_storage, target_storage, path)
            return

        hasher = hashlib.sha256()

        if not target_hash:
            try:
                target_file_obj = target_storage.create(path, os.O_CREAT | os.O_WRONLY)
            except OptionalError:
                logger.warning("Container %s: cannot sync file %s to storage %s. "
                               "Operation not supported by storage backend.",
                               self.container_name, path, target_storage.backend_id)
            except NotADirectoryError:
                # Can occur if there's a file/directory conflict and we are trying to sync a file
                # located in a directory that's a file in another storage
                self.handle_conflict(source_storage, target_storage, path)
                return
        else:
            try:
                target_file_obj = target_storage.open_for_safe_replace(path, os.O_RDWR, target_hash)
            except OptionalError:
                try:
                    target_file_obj = target_storage.open(path, os.O_WRONLY)
                except OptionalError:
                    logger.warning("Container %s: cannot sync file %s to storage %s. "
                                   "Operation not supported by storage backend.",
                                   self.container_name, path, target_storage.backend_id)
                    return
            except HashMismatchError:
                logger.warning("Container %s: unexpected hash for object %s in storage %s found, "
                               "cannot sync.", self.container_name, path, target_storage.backend_id)
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
            logger.warning("Container %s: unexpected hash for object %s in storage %s found, "
                           "cannot sync.", self.container_name, path, target_storage.backend_id)
            return

        resulting_hash = hasher.hexdigest()

        self.storage_hashes[source_storage][path] = resulting_hash
        self.storage_hashes[target_storage][path] = resulting_hash

    def sync_dir(self, source_storage: StorageBackend, target_storage: StorageBackend,
                 path: PurePosixPath):
        """
        Sync whole directory at path and its contents from source_storage to target_storage.
        """
        logger.debug("Container %s: attempting to sync directory %s in storages %s "
                     "and %s", self.container_name, path, source_storage.backend_id, target_storage.backend_id)
        for file_path, attr in source_storage.walk(path):
            if attr.is_dir():
                with suppress(FileExistsError):
                    target_storage.mkdir(file_path)
            else:
                self.sync_file(source_storage, target_storage, file_path)

    def remove_whole_dir(self, storage: StorageBackend, dir_path):
        """
        Recursively remove whole directory, its contents and corresponding hashes.
        """
        logger.debug("Container %s: attempting to remove directory %s in storages %s",
                     self.container_name, dir_path, storage.backend_id)
        paths_to_remove = sorted(
            [(path, attr.is_dir()) for path, attr in storage.walk(dir_path)],
            key=lambda x: x[0], reverse=True)
        for path, is_dir in paths_to_remove:
            if is_dir:
                storage.rmdir(path)
            else:
                target_hash = storage.get_hash(path)
                if target_hash != self.storage_hashes[storage][path]:
                    logger.warning("Container %s: unexpected hash for object %s in storage %s "
                                   "found, not removing.", self.container_name, path, storage.backend_id)
                    return
                storage.unlink(path)
            if path in self.storage_hashes[storage]:
                del self.storage_hashes[storage][path]

        storage.rmdir(dir_path)

    def remove_subdir_paths(self, storage: StorageBackend, path: PurePosixPath):
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

    def remove_object(self, source_storage: StorageBackend, target_storage: StorageBackend,
                      path: PurePosixPath, source_is_dir: bool, old_source_hash=None):
        """
        Remove an object (dir or file) in path in target_storage, if it is the object
        the syncer expected to find there (based on hash).
        Must give source_storage so that conflict handling knows where the conflict is and
        must pass source_is_dir boolean parameter, because there's no way to guess what was in
        source_storage before it was deleted.
        To avoid problems with syncing multiple containers, should provide old source hash.
        """
        logger.debug("Container %s: attempting to sync file %s removed from storage %s in "
                     "storage %s", self.container_name, path,
                     source_storage.backend_id, target_storage.backend_id)
        self.remove_subdir_paths(source_storage, path)
        try:
            target_is_dir = target_storage.getattr(path).is_dir()
        except FileNotFoundError:
            logger.warning("Container %s: removal of %s from storage %s failed: file already"
                           " removed.", self.container_name, path, target_storage.backend_id)
            self.remove_subdir_paths(target_storage, path)
            return

        if target_is_dir != source_is_dir:
            self.handle_conflict(source_storage, target_storage, path)
            return

        if target_is_dir:
            self.remove_whole_dir(target_storage, path)
        else:
            target_hash = target_storage.get_hash(path)
            source_hash = old_source_hash if old_source_hash else \
                self.storage_hashes[target_storage][path]
            if target_hash != source_hash:
                self.handle_conflict(source_storage, target_storage, path)
                return
            target_storage.unlink(path)
            if path in self.storage_hashes[target_storage]:
                del self.storage_hashes[target_storage][path]
            return

    def create_object(self, source_storage: StorageBackend, target_storage: StorageBackend,
                      path: PurePosixPath):
        """
        Create an object (file or dir) in path in target_storage, based on existing object in
        source_storage.
        """
        logger.debug("Container %s: attempting to sync file %s created in storage %s into "
                     "storage %s", self.container_name, path,
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
                logger.debug("Container %s: creation of file %s in storage %s failed: file "
                             "already exists.", self.container_name, path, target_storage.backend_id)
            self.sync_dir(source_storage, target_storage, path)
        else:
            self.sync_file(source_storage, target_storage, path)

    def sync_storages(self, source_storage: StorageBackend, events: List[FileEvent]):
        """
        Process storage events originating from a given source_storage.
        """
        with self.lock:
            for event in events:
                logger.debug("Container %s: handling event %s for object %s occurring in "
                             "storage %s", self.container_name, event.type, event.path,
                             source_storage.backend_id)

                obj_path = event.path

                if event.type == 'delete':
                    old_source_hash = self.storage_hashes[source_storage].get(obj_path)
                    is_dir = obj_path not in self.storage_hashes[source_storage]

                    for target_storage in self.storage_watchers:
                        if target_storage == source_storage:
                            continue

                        old_target_hash = self.storage_hashes[target_storage].get(obj_path)

                        if old_source_hash == old_target_hash:
                            self.remove_object(source_storage, target_storage, obj_path,
                                               is_dir, old_source_hash)
                        else:
                            logger.warning(
                                "Container %s: conflict resolved via removal of file at %s from "
                                "storage %s; version from %s is now authoritative.",
                                self.container_name, obj_path,
                                source_storage.backend_id, target_storage.backend_id)
                            self.create_object(target_storage, source_storage, obj_path)
                else:
                    for target_storage in self.storage_watchers:
                        if target_storage == source_storage:
                            continue
                        if event.type == 'create':
                            self.create_object(source_storage, target_storage, obj_path)
                        elif event.type == 'modify':
                            self.sync_file(source_storage, target_storage, obj_path)

    def stop_syncing(self):
        """
        Stop all watchers cleanly.
        """
        logger.debug("Container %s: stopping file syncing.", self.container_name)
        for backend in self.storage_watchers:
            backend.stop_watcher()
            backend.request_unmount()
        logger.debug("Container %s: file syncing stopped.", self.container_name)


def list_storage_conflicts(storages):
    """
    Helper function to detect and return list of file conflicts for given storages.
    """
    conflicts = []
    for s1, s2 in combinations(storages, 2):
        for path, attr in s1.walk():
            try:
                attr2 = s2.getattr(path)
            except (FileNotFoundError, NotADirectoryError):
                continue

            if attr.is_dir() != attr2.is_dir():
                conflicts.append((str(path), s1.backend_id, s2.backend_id))
                continue

            if attr.is_dir():
                continue

            if s1.get_hash(path) != s2.get_hash(path):
                conflicts.append((str(path), s1.backend_id, s2.backend_id))

    return conflicts
