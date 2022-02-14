# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
#                    Piotr Bartman <prbartman@invisiblethingslab.com>
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
Wildland Filesystem
"""

import abc
from dataclasses import dataclass
from typing import List, Dict, Set, Callable, Iterable

from .control_server import ControlHandler
from .log import get_logger
from .storage_backends.watch import FileEvent, StorageWatcher, FileEventType

logger = get_logger('fs_watchers')


@dataclass
class Watch:
    """
    A watch added by a connected user.
    """

    id: int
    storage_id: int
    pattern: str
    handler: ControlHandler

    def __str__(self):
        return f'{self.storage_id}:{self.pattern}'


class FSWatchers(metaclass=abc.ABCMeta):
    """
    A base abstract class that manages storage's watchers.

    To create subclass `_start_watcher` and `_stop_watcher` have to be implemented.
    """

    def __init__(self, fs):
        self.fs = fs

        self.watches: Dict[int, Watch] = {}
        self.storage_watches: Dict[int, Set[int]] = {}
        self.watchers: Dict[int, StorageWatcher] = {}
        self.watch_counter = 1

    def notify_storage_watches(self, event_type: FileEventType, relpath, storage_id):
        """
        Send the event to all watches of the storage if the storage has no watcher registered.
        """
        with self.fs.mount_lock:
            if storage_id not in self.storage_watches:
                return

            if storage_id in self.watchers:
                return
            watches = [self.watches[watch_id]
                       for watch_id in self.storage_watches[storage_id]]

        if not watches:
            return

        event = FileEvent(event_type, relpath)
        for watch in watches:
            self._notify_watch(watch, [event])

    def add_watch(self, storage_id: int, pattern: str, handler: ControlHandler,
                  ignore_own: bool = False):
        """
        Add watch of the storage.

        If no other watch exists, start a watch thread, but only if the storage provides `watcher`
        method.
        """

        assert self.fs.mount_lock.locked()

        watch = Watch(
            id=self.watch_counter,
            storage_id=storage_id,
            pattern=pattern,
            handler=handler,
        )
        logger.debug('adding watch: %s', watch)
        self.watches[watch.id] = watch
        if storage_id not in self.storage_watches:
            self.storage_watches[storage_id] = set()

        self.storage_watches[storage_id].add(watch.id)
        self.watch_counter += 1

        handler.on_close(lambda: self._cleanup_watch(watch.id))

        # Start a watch thread, but only if the storage provides watcher() method
        if len(self.storage_watches[storage_id]) == 1:

            def watch_handler(events):
                self._watch_handler(storage_id, events)

            watcher = self._start_watcher(storage_id, watch_handler, ignore_own)

            if watcher:
                logger.debug('starting watcher for storage %d', storage_id)
                self.watchers[storage_id] = watcher

        return watch.id

    def remove_watches(self, storage_id: int):
        """
        Remove all watches of the storage and remove watcher if exists.
        """
        if storage_id in self.storage_watches:
            for watch_id in list(self.storage_watches[storage_id]):
                self._remove_watch(watch_id)

    @abc.abstractmethod
    def _start_watcher(
            self,
            storage_id: int,
            watch_handler: Callable[[Iterable[FileEventType]], None],
            ignore_own: bool
    ):
        """
        Start and return the watcher.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def _stop_watcher(self, storage_id: int):
        """
        Stop the watcher.
        """
        raise NotImplementedError()

    def _watch_handler(self, storage_id: int, events: List[FileEvent]):
        logger.debug('events from %d: %s', storage_id, events)
        watches = [self.watches[watch_id]
                   for watch_id in self.storage_watches.get(storage_id, [])]

        for watch in watches:
            self._notify_watch(watch, events)

    @staticmethod
    def _notify_watch(watch: Watch, events: List[FileEvent]):
        events = [event for event in events
                  if event.path.match(watch.pattern)]
        if not events:
            return

        logger.debug('notify watch: %s: %s', watch, events)
        data = [{
            'type': event.type.name,
            'path': str(event.path),
            'watch-id': watch.id,
            'storage-id': watch.storage_id,
        } for event in events]
        watch.handler.send_event(data)

    def _cleanup_watch(self, watch_id: int):
        with self.fs.mount_lock:
            # Could be removed earlier, when unmounting storage.
            if watch_id in self.watches:
                self._remove_watch(watch_id)

    def _remove_watch(self, watch_id: int):
        assert self.fs.mount_lock.locked()

        watch = self.watches[watch_id]
        logger.debug('removing watch: %s', watch)

        if (len(self.storage_watches[watch.storage_id]) == 1 and
                watch.storage_id in self.watchers):
            logger.debug('stopping watcher for storage: %s', watch.storage_id)
            self._stop_watcher(watch.storage_id)
            del self.watchers[watch.storage_id]

        self.storage_watches[watch.storage_id].remove(watch_id)
        del self.watches[watch_id]


class FileWatchers(FSWatchers):
    """
    A subclass of `FSWatchers` that manages storage's file watchers.
    """

    def _start_watcher(self, storage_id, watch_handler, ignore_own):
        return self.fs.storages[storage_id].start_watcher(watch_handler, ignore_own)

    def _stop_watcher(self, storage_id):
        self.fs.storages[storage_id].stop_watcher()


class ChildrenWatchers(FSWatchers):
    """
    A subclass of `FSWatchers` that manages storage's children watchers.
    """

    def _start_watcher(self, storage_id, watch_handler, _ignore_own):
        return self.fs.storages[storage_id].start_subcontainer_watcher(watch_handler)

    def _stop_watcher(self, storage_id):
        self.fs.storages[storage_id].stop_subcontainer_watcher()
