# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Watching for changes.
"""
from enum import Enum
from typing import Optional, List, Callable, Dict
from pathlib import PurePosixPath
import threading
from dataclasses import dataclass
import abc
import os

from .base import StorageBackend, Attr
from ..log import get_logger

logger = get_logger('watch')


class FileEventType(Enum):
    """
    File change event type.
    """
    CREATE = 1
    DELETE = 2
    MODIFY = 3

    def __repr__(self):
        return str(self.name)

    def __str__(self):
        return self.__repr__()


@dataclass
class FileEvent:
    """
    File change event.
    """
    type: FileEventType
    path: PurePosixPath

    def __repr__(self):
        return f'{self.type.name} {self.path}'

    def __str__(self):
        return self.__repr__()


class StorageWatcher(metaclass=abc.ABCMeta):
    """
    An object that watches for changes on a separate thread.
    """

    def __init__(self):
        self.handler = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(name='Watch', target=self._run)

    def ignore_event(self, event_type: FileEventType, path):  # pylint: disable=unused-argument
        """
        Invoked by the backend to specify incoming ignorable event.
        """
        if not self.handler:
            return

    def start(self, handler: Callable[[List[FileEvent]], None], with_initial: bool = False):
        """
        Start the watcher on a separate thread.
        """

        self.handler = handler
        self.init(with_initial)
        self.thread.start()

    def _run(self):
        assert self.handler
        try:
            while not self.stop_event.is_set():
                events = self.wait()
                if events:
                    self.handler(events)
        except Exception:
            logger.exception('error in watcher')

    def stop(self):
        """
        Stop the watching thread.
        """
        self.stop_event.set()
        if self.thread != threading.current_thread():
            self.thread.join()
        self.shutdown()

    @abc.abstractmethod
    def init(self, with_initial: bool) -> None:
        """
        Initialize the watcher. This will be called synchronously (before
        starting a separate thread).
        """

    @abc.abstractmethod
    def wait(self) -> Optional[List[FileEvent]]:
        """
        Wait for a list of change events. This should return as soon as
        self.stop_event is set.
        """

    @abc.abstractmethod
    def shutdown(self) -> None:
        """
        Clean up.
        """


class SimpleStorageWatcher(StorageWatcher, metaclass=abc.ABCMeta):
    """
    An implementation of storage watcher that uses the backend to enumerate all
    files.

    Default implementation polls the storage every 10s for changes. To improve, override
    get_token() with something that will change when the storage needs to be examined again
    (such as last modification time of backing storage).
    """

    def __init__(self, backend: StorageBackend, interval: int = 10):
        super().__init__()
        self.backend = backend
        self.token = None
        self.info: Dict[PurePosixPath, Attr] = {}
        self.interval = interval
        self.counter = 0  # for naive implementation of get_token()

    def get_token(self):
        """
        Retrieve token to be compared, such as file modification info.
        """
        self.counter += 1
        return self.counter

    def init(self, _with_initial: bool = False):
        self.token = self.get_token()
        self.info = self._get_info()

    def wait(self) -> Optional[List[FileEvent]]:
        self.stop_event.wait(self.interval)
        new_token = self.get_token()
        if new_token != self.token:
            logger.debug('storage changed...')
            self.backend.clear_cache()
            new_info = self._get_info()
            result = list(self._compare_info(self.info, new_info))

            self.token = new_token
            self.info = new_info
            if result:
                logger.debug('file changes detected')
                return result
            logger.debug('file no changes detected')
            return None
        return None

    def shutdown(self):
        pass

    def _get_info(self) -> Dict[PurePosixPath, Attr]:
        return dict(self._walk(PurePosixPath('.')))

    def _walk(self, dir_path: PurePosixPath):
        try:
            names = list(self.backend.readdir(dir_path))
        except IOError:
            logger.exception('error in readdir %s', dir_path)
            return

        for name in names:
            file_path = dir_path / name
            try:
                attr = self.backend.getattr(file_path)
            except IOError:
                logger.exception('error in getattr %s', file_path)
                continue

            yield file_path, attr
            if attr.is_dir():
                yield from self._walk(file_path)

    @staticmethod
    def _compare_info(current_info, new_info):
        current_paths = set(current_info)
        new_paths = set(new_info)
        for path in current_paths - new_paths:
            yield FileEvent(FileEventType.DELETE, path)
        for path in new_paths - current_paths:
            yield FileEvent(FileEventType.CREATE, path)
        for path in current_paths & new_paths:
            if current_info[path] != new_info[path]:
                yield FileEvent(FileEventType.MODIFY, path)


@dataclass
class SubcontainerEvent:
    """
    Subcontainer change event.
    """
    type: FileEventType
    path: PurePosixPath

    def __repr__(self):
        return f'{self.type.name} {self.path}'

    def __str__(self):
        return self.__repr__()


class SubcontainerWatcher(StorageWatcher, metaclass=abc.ABCMeta):
    """
    TODO
    """

    def __init__(self, backend: StorageBackend, interval: int = 10):
        super().__init__()
        self.backend = backend
        self.token = None
        self.info: Dict[PurePosixPath, Attr] = {}
        self.interval = interval
        self.counter = 0  # for naive implementation of get_token()

    def get_token(self):
        """
        Retrieve token to be compared, such as file modification info.
        """
        self.counter += 1
        return self.counter

    def init(self, with_initial: bool = False):
        self.token = self.get_token()
        if not with_initial:
            self.info = self._get_info()

    def wait(self) -> Optional[List[SubcontainerEvent]]:
        self.stop_event.wait(self.interval)
        new_token = self.get_token()
        if new_token != self.token:
            logger.debug('storage changed...')
            self.backend.clear_cache()
            new_info = self._get_info()
            result = list(self._compare_info(self.info, new_info))

            self.token = new_token
            self.info = new_info
            if result:
                logger.debug('subcontainer changes detected')
                return result
            logger.debug('subcontainer no changes detected')
            return None
        return None

    def shutdown(self):
        pass

    def _get_info(self):
        to_return = []
        paths = self.backend.get_children(paths_only = True)
        for path in paths:
            mtime = os.path.getmtime(path)
            to_return.append((path, mtime))
        return to_return

    @staticmethod
    def _compare_info(current_info, new_info):
        current_paths = set(current_info)
        new_paths = set(new_info)
        for path in current_paths - new_paths:
            yield SubcontainerEvent(FileEventType.DELETE, path)
        for path in new_paths - current_paths:
            yield SubcontainerEvent(FileEventType.CREATE, path)
        for path, mtime in current_paths:
            for new_path, new_mtime in current_paths:
                if path == new_path and mtime != new_mtime:
                    yield SubcontainerEvent(FileEventType.MODIFY, path, new_info[path])
