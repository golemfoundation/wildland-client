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
Watching for changes.
'''

from typing import Optional, List, Callable
from pathlib import PurePosixPath
import threading
import logging
from dataclasses import dataclass
import abc


@dataclass
class FileEvent:
    '''
    File change event.
    '''

    type: str  # 'create', 'delete', 'modify'
    path: PurePosixPath


class StorageWatcher(metaclass=abc.ABCMeta):
    '''
    An object that watches for changes on a separate thread.
    '''

    def __init__(self):
        self.handler = None
        self.stop_event = threading.Event()
        self.thread = threading.Thread(name='Watch', target=self._run)

    def start(self, handler: Callable[[List[FileEvent]], None]):
        '''
        Start the watcher on a separate thread.
        '''

        self.handler = handler
        self.init()
        self.thread.start()

    def _run(self):
        assert self.handler
        try:
            while not self.stop_event.is_set():
                events = self.wait()
                if events:
                    self.handler(events)
        except Exception:
            logging.exception('error in watcher')

    def stop(self):
        '''
        Stop the watching thread.
        '''

        self.stop_event.set()
        self.thread.join()
        self.shutdown()

    @abc.abstractmethod
    def init(self) -> None:
        '''
        Initialize the watcher. This will be called synchronously (before
        starting a separate thread).
        '''

    @abc.abstractmethod
    def wait(self) -> Optional[List[FileEvent]]:
        '''
        Wait for a list of change events. This should return as soon as
        self.stop_event is set.
        '''

    @abc.abstractmethod
    def shutdown(self) -> None:
        '''
        Clean up.
        '''
