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
# pylint: disable=too-many-lines
"""
Monitor container manifests for changes and remount if necessary
"""

import os
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple, Iterable, Dict
import logging

from wildland.client import Client
from wildland.container import Container
from wildland.fs_client import WildlandFSClient, WatchEvent
from wildland.storage import Storage


logger = logging.getLogger('remounter')


class Remounter:
    """
    A class for watching files and remounting if necessary.
    """

    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 container_names: List[str], additional_patterns: Optional[List[str]] = None):
        self.client = client
        self.fs_client = fs_client

        self.patterns: List[str] = []
        if additional_patterns:
            self.patterns.extend(additional_patterns)
        for name in container_names:
            path = Path(os.path.expanduser(name)).resolve()
            relpath = path.relative_to(self.fs_client.mount_dir)
            self.patterns.append(str(PurePosixPath('/') / relpath))

        # Queued operations
        self.to_mount: List[Tuple[Container,
                                  Iterable[Storage],
                                  Iterable[PurePosixPath],
                                  Optional[Container]]] = []
        self.to_unmount: List[int] = []

        # manifest path -> main container path
        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

    def run(self):
        """
        Run the main loop.
        """

        logger.info('Using patterns: %r', self.patterns)
        for events in self.fs_client.watch(self.patterns, with_initial=True):
            for event in events:
                try:
                    self.handle_event(event)
                except Exception:
                    logger.exception('error in handle_event')

            self.unmount_pending()
            self.mount_pending()

    def handle_event(self, event: WatchEvent):
        """
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        """

        logger.info('Event %s: %s', event.event_type, event.path)

        # Find out if we've already seen the file, and can match it to a
        # mounted storage.
        storage_id: Optional[int] = None
        if event.path in self.main_paths:
            storage_id = self.fs_client.find_storage_id_by_path(
                self.main_paths[event.path])

        # Handle delete: unmount if the file was mounted.
        if event.event_type == 'delete':
            # Stop tracking the file
            if event.path in self.main_paths:
                del self.main_paths[event.path]

            if storage_id is not None:
                logger.info('  (unmount %d)', storage_id)
                self.to_unmount.append(storage_id)
            else:
                logger.info('  (not mounted)')

        # Handle create/modify:
        if event.event_type in ['create', 'modify']:
            local_path = self.fs_client.mount_dir / event.path.relative_to('/')
            container = self.client.load_container_from_path(local_path)

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_path(
                container.owner, container.paths[0])


            user_paths = self.client.get_bridge_paths_for_user(container.owner)
            storages = self.client.get_storages_to_mount(container)

            if self.fs_client.find_primary_storage_id(container) is None:
                logger.info('  new: %s', str(container))
                self.to_mount.append((container, storages, user_paths, None))
            else:
                storages_to_remount = []

                for path in self.fs_client.get_orphaned_container_storage_paths(
                        container, storages):
                    storage_id = self.fs_client.find_storage_id_by_path(path)
                    assert storage_id is not None
                    logger.info('  (removing orphan %s @ id: %d)', path, storage_id)
                    self.fs_client.unmount_storage(storage_id)

                for storage in storages:
                    if self.fs_client.should_remount(container, storage, user_paths):
                        logger.info('  (remounting: %s)', storage.backend_id)
                        storages_to_remount.append(storage)
                    else:
                        logger.info('  (not changed: %s)', storage.backend_id)

                self.to_mount.append((container, storages_to_remount, user_paths, None))

    def unmount_pending(self):
        """
        Unmount queued containers.
        """

        for storage_id in self.to_unmount:
            self.fs_client.unmount_storage(storage_id)
        self.to_unmount.clear()

    def mount_pending(self):
        """
        Mount queued containers.
        """

        self.fs_client.mount_multiple_containers(self.to_mount, remount=True)
        self.to_mount.clear()
