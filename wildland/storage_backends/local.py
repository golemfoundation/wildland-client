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
Local storage, similar to :command:`mount --bind`
'''

import os
import time
from pathlib import Path, PurePosixPath
import logging
import threading
from typing import Optional, List, Dict, Tuple
import select
import inotify_simple

import click

from .base import StorageBackend, File, Attr
from ..fuse_utils import flags_to_mode
from ..manifest.schema import Schema
from .watch import StorageWatcher, FileEvent

__all__ = ['LocalStorageBackend']


def to_attr(st: os.stat_result) -> Attr:
    '''
    Convert os.stat_result to Attr.
    '''

    return Attr(
        mode=st.st_mode,
        size=st.st_size,
        timestamp=int(st.st_mtime),
    )


class LocalFile(File):
    '''A file on disk

    (does not need to be a regular file)
    '''

    def __init__(self, path, realpath, flags, mode=0, ignore_callback=None):
        self.path = path
        self.realpath = realpath
        self.ignore_callback = ignore_callback
        self.changed = False

        self.file = os.fdopen(
            os.open(realpath, flags, mode),
            flags_to_mode(flags))
        self.lock = threading.Lock()

    # pylint: disable=missing-docstring

    def release(self, flags):
        if self.changed and self.ignore_callback:
            self.ignore_callback('modify', self.path)
        return self.file.close()

    def fgetattr(self):
        '''...

        Without this method, at least :meth:`read` does not work.
        '''
        with self.lock:
            st = to_attr(os.fstat(self.file.fileno()))
            # Make sure to return the correct size.
            # TODO: Unfortunately this is not enough, as fstat() causes FUSE to
            # call getattr(), not fgetattr():
            # https://github.com/libfuse/libfuse/issues/62
            st.size = self.file.seek(0, 2)
        return st

    def read(self, length, offset):
        with self.lock:
            self.file.seek(offset)
            return self.file.read(length)

    def write(self, data, offset):
        with self.lock:
            self.file.seek(offset)
            written_data = self.file.write(data)
            self.changed = True
            return written_data

    def ftruncate(self, length):
        with self.lock:
            self.file.truncate(length)
            self.changed = True

    def flush(self) -> None:
        self.file.flush()


class LocalStorageBackend(StorageBackend):
    '''Local, file-based storage'''
    SCHEMA = Schema({
        "type": "object",
        "required": ["location"],
        "properties": {
            "location": {
                "$ref": "types.json#abs-path",
                "description": "Path in the local filesystem"
            }
        }
    })
    TYPE = 'local'

    def __init__(self, *, relative_to=None, **kwds):
        super().__init__(**kwds)
        location_path = Path(self.params['location'])
        if relative_to is not None:
            location_path = relative_to / location_path
        location_path = location_path.resolve()
        if not location_path.is_dir():
            logging.warning('LocalStorage root does not exist: %s', location_path)
        self.root = location_path

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--location'], metavar='PATH',
                         help='path in local filesystem',
                         required=True)
        ]

    @classmethod
    def cli_create(cls, data):
        return {'location': data['location']}

    def _path(self, path: PurePosixPath) -> Path:
        '''Given path inside filesystem, calculate path on disk, relative to
        :attr:`self.root`

        Args:
            path (pathlib.PurePosixPath): the path
        Returns:
            pathlib.Path: path relative to :attr:`self.root`
        '''
        ret = (self.root / path).resolve()
        ret.relative_to(self.root) # this will throw ValueError if not relative
        return ret

    # pylint: disable=missing-docstring

    def open(self, path, flags):
        if self.ignore_own_events and self.watcher_instance:
            return LocalFile(path, self._path(path), flags,
                             ignore_callback=self.watcher_instance.ignore_event)
        return LocalFile(path, self._path(path), flags)

    def create(self, path, flags, mode=0o666):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('create', path)
            return LocalFile(path, self._path(path), flags, mode,
                             ignore_callback=self.watcher_instance.ignore_event)
        return LocalFile(path, self._path(path), flags, mode)

    def getattr(self, path):
        return to_attr(os.lstat(self._path(path)))

    def readdir(self, path):
        return os.listdir(self._path(path))

    def truncate(self, path, length):
        return os.truncate(self._path(path), length)

    def unlink(self, path):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('delete', path)
        return os.unlink(self._path(path))

    def mkdir(self, path, mode=0o777):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('create', path)
        return os.makedirs(self._path(path), mode, exist_ok=True)

    def rmdir(self, path):
        if self.ignore_own_events and self.watcher_instance:
            self.watcher_instance.ignore_event('delete', path)
        return os.rmdir(self._path(path))

    def watcher(self):
        """
        If manifest explicitly specifies a watcher-interval, use default implementation. If not,
        we can use the smarter LocalStorageWatcher.
        """
        default_watcher = super().watcher()
        if not default_watcher:
            return LocalStorageWatcher(self)
        return default_watcher

    def get_file_token(self, path: PurePosixPath) -> Optional[int]:
        try:
            current_timestamp = os.stat(self._path(path)).st_mtime
        except NotADirectoryError:
            # can occur due to extreme file conflicts across storages
            return None
        if abs(time.time() - current_timestamp) < 0.001:
            # due to filesystem lack of resolution, two changes less than 1 millisecond apart
            # can have the same mtime. We assume 1 millisecond, as it's correct for EXT4,
            # but be warned: it can go as low as 2 seconds for FAT16/32
            return None
        return int(current_timestamp * 1000)


class LocalStorageWatcher(StorageWatcher):
    """
    Watches for changes in local storage, using inotify.
    Known issues: on subdirectory creation, some events may be lost, because files appear
    before the watcher can add watches. It's unfortunately a known inotify issue.
    """
    def __init__(self, backend: StorageBackend):
        super().__init__()
        self.path = getattr(backend, 'root', None)
        self.clear_cache = backend.clear_cache
        self.watches: Dict[int, str] = {}
        self.watch_flags = inotify_simple.flags.CREATE | inotify_simple.flags.DELETE | \
            inotify_simple.flags.MOVED_TO | inotify_simple.flags.MOVED_FROM | \
            inotify_simple.flags.CLOSE_WRITE

        self.lock = threading.Lock()

        self.ignore_list: List[Tuple[str, str]] = []

    def ignore_event(self, event_type: str, path: PurePosixPath):
        # path should be the relative path
        with self.lock:
            self.ignore_list.append((event_type, str(path)))

    def _watch_dir(self, path):
        for root, dirs, _files in os.walk(path):
            if root not in self.watches.values():
                wd = self.inotify.add_watch(root, self.watch_flags)
                self.watches[wd] = root
            for directory in dirs:
                dir_path = os.path.join(root, directory)
                wd = self.inotify.add_watch(dir_path, self.watch_flags)
                self.watches[wd] = dir_path

    def init(self) -> None:
        # pylint: disable=attribute-defined-outside-init
        self.inotify = inotify_simple.INotify()
        self._watch_dir(self.path)
        self._stop_pipe_read, self._stop_pipe_write = os.pipe()

    def stop(self):
        os.write(self._stop_pipe_write, b's')
        super().stop()

    def shutdown(self) -> None:
        os.close(self._stop_pipe_write)
        os.close(self._stop_pipe_read)
        for wd in self.watches:
            self.inotify.rm_watch(wd)
        self.inotify.close()

    def wait(self) -> Optional[List[FileEvent]]:
        result = select.select([self._stop_pipe_read, self.inotify], [], [])
        if self._stop_pipe_read in result[0]:
            return []
        events = self.inotify.read(timeout=1, read_delay=250)
        results = []

        for event in events:
            event_flags = inotify_simple.flags.from_mask(event.mask)

            if inotify_simple.flags.IGNORED in event_flags:
                continue

            path = os.path.join(self.watches[event.wd], event.name)

            if inotify_simple.flags.CREATE in event_flags or \
                    inotify_simple.flags.MOVED_TO in event_flags:
                if inotify_simple.flags.ISDIR in event_flags:
                    self._watch_dir(path)
                event_type = 'create'
            elif inotify_simple.flags.DELETE in event_flags or \
                    inotify_simple.flags.MOVED_FROM in event_flags:
                if inotify_simple.flags.ISDIR in event_flags:
                    self.watches = {key: val for key, val in self.watches.items() if val != path}
                event_type = 'delete'
            elif inotify_simple.flags.CLOSE_WRITE in event_flags:
                event_type = 'modify'
            else:
                continue

            relative_path = PurePosixPath(path).relative_to(self.path)

            with self.lock:
                ev = (event_type, str(relative_path))
                if ev in self.ignore_list:
                    self.ignore_list.remove(ev)
                    continue

            results.append(FileEvent(path=relative_path, type=event_type))
        self.clear_cache()
        return results
