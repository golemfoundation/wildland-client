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
# pylint: disable=too-many-lines
"""
Superclass for PathRemounter and SubcontainerRemounter.
"""

from pathlib import PurePosixPath
from typing import List, Optional, Tuple, Iterable, Dict

from wildland.client import Client
from wildland.container import Container
from wildland.exc import WildlandError
from wildland.fs_client import WildlandFSClient, WatchEvent
from wildland.storage import Storage
from wildland.storage_backends.watch import FileEventType


class Remounter:
    """
    A class for watching changes and remounting if necessary.
    """

    def __init__(self, client: Client, fs_client: WildlandFSClient, logger):
        self.client = client
        self.fs_client = fs_client

        # Queued operations
        self.to_mount: List[Tuple[Container,
                                  Iterable[Storage],
                                  Iterable[Iterable[PurePosixPath]],
                                  Optional[Container]]] = []
        self.to_unmount: List[int] = []

        # manifest path -> main container path
        self.main_paths: Dict[PurePosixPath, PurePosixPath] = {}

        self.logger = logger

    def handle_event(self, event: WatchEvent):
        """
        Handle a single file change event. Queue mount/unmount operations in
        self.to_mount and self.to_unmount.
        """

        self.logger.info('Event %s: %s', event.event_type, event.path)

        # Handle delete: unmount if the file was mounted.
        if event.event_type == FileEventType.DELETE:
            # Find out if we've already seen the file, and can match it to an mounted storage.
            storage_id: Optional[int] = None
            pseudo_storage_id: Optional[int] = None

            if event.path in self.main_paths:
                storage_id = self.fs_client.find_storage_id_by_path(self.main_paths[event.path])
                pseudo_storage_id = self.fs_client.find_storage_id_by_path(
                    self.main_paths[event.path] / '.manifest.wildland.yaml')

            if storage_id is not None:
                assert pseudo_storage_id is not None
                self.logger.info('  (unmount %d)', storage_id)
                self.to_unmount += [storage_id, pseudo_storage_id]
            else:
                self.logger.info('  (not mounted)')

            # Stop tracking the file
            if event.path in self.main_paths:
                del self.main_paths[event.path]

        # Handle create/modify:
        if event.event_type in [FileEventType.CREATE, FileEventType.MODIFY]:
            container = self.load_container(event)

            # Start tracking the file
            self.main_paths[event.path] = self.fs_client.get_user_container_path(
                container.owner, container.paths[0])
            self.handle_changed_container(container)

    def load_container(self, event):
        """
        Load container to (re)mount from WatchEvent.
        """
        raise NotImplementedError()

    def handle_changed_container(self, container: Container):
        """
        Queue mount/remount of a container. This considers both new containers and
        already mounted containers, including changes in storages

        :param container: container to (re)mount
        :return:
        """
        user_paths = self.client.get_bridge_paths_for_user(container.owner)
        storages = self.client.get_storages_to_mount(container)
        if self.fs_client.find_primary_storage_id(container) is None:
            self.logger.info('  new: %s', str(container))
            self.to_mount.append((container, storages, user_paths, None))
        else:
            storages_to_remount = []

            for path in self.fs_client.get_orphaned_container_storage_paths(container, storages):
                storage_id = self.fs_client.find_storage_id_by_path(path)
                pseudo_storage_id = self.fs_client.find_storage_id_by_path(
                    path / '.manifest.wildland.yaml')
                assert storage_id is not None
                assert pseudo_storage_id is not None
                self.logger.info('  (removing orphan storage %s @ id: %d)', path, storage_id)
                self.to_unmount += [storage_id, pseudo_storage_id]

            for storage in storages:
                if self.fs_client.should_remount(container, storage, user_paths):
                    self.logger.info('  (remounting: %s)', storage.backend_id)
                    storages_to_remount.append(storage)
                else:
                    self.logger.info('  (not changed: %s)', storage.backend_id)

            if storages_to_remount:
                self.to_mount.append((container, storages_to_remount, user_paths, None))

    def unmount_pending(self):
        """
        Unmount queued containers.
        """

        for storage_id in self.to_unmount:
            try:
                self.fs_client.unmount_storage(storage_id)
            except WildlandError as e:
                self.logger.error('failed to unmount storage %d: %s', storage_id, e)
        self.to_unmount.clear()

    def mount_pending(self):
        """
        Mount queued containers.
        """

        try:
            self.fs_client.mount_multiple_containers(self.to_mount, remount=True)
        except WildlandError as e:
            self.logger.error('failed to mount some storages: %s', e)
        self.to_mount.clear()
