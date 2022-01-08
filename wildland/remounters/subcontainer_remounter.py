# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                   Piotr Bartman <prbartman@invisiblethingslab.com>
#                   Maja Kostacinska <maja@wildland.io>
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
Monitor subcontainer for changes and remount if necessary
"""
from typing import Dict

from wildland.client import Client
from wildland.container import Container
from wildland.fs_client import WildlandFSClient
from wildland.log import get_logger
from wildland.remounters.remounter import Remounter
from wildland.storage import Storage

logger = get_logger('subcontainer_remounter')


class SubcontainerRemounter(Remounter):
    """
    A class for watching subcontainers and remounting if necessary.

    This works by registering watches in WL (FUSE) daemon for requested storages.
    When subcontainer change is reported, the container in question is loaded and then
    compared with mounted state (same as the ``wl container mount`` does - either
    mount it new, or remount relevant storages).
    """

    def __init__(self, client: Client, fs_client: WildlandFSClient,
                 containers_storage: Dict[Container, Storage]):
        super().__init__(client, fs_client, logger)

        self.containers_storage = containers_storage

    def run(self):
        """
        Run the main loop.
        """

        while True:
            for events in self.fs_client.watch_subcontainers(
                    self.client, self.containers_storage, with_initial=True):
                for event in events:
                    try:
                        self.handle_event(event)
                    except Exception as e:
                        logger.error(f'error in handle_subcontainer_event: {str(e)}')
                self.unmount_pending()
                self.mount_pending()

    def load_container(self, event):
        assert event.subcontainer is not None
        container = self.client.load_subcontainer_object(
            event.container, event.storage, event.subcontainer)
        assert isinstance(container, Container)
        return container
