# Wildland project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Piotr K. Isajew <piotr@wildland.io>
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
Wildland filesystem implementation intended to work as part of embedded Python
installation on Apple platform.
"""

import os
from pathlib import Path
from .apple_log import apple_log
from ..fs_base import WildlandFSBase
from ..log import get_logger

logger = get_logger('fs')


class WildlandMacFS(WildlandFSBase):
    """
    This class is primarily used within the specialized NFS server
    designed primarily for usage on Apple platform. Rather than assuming
    specific filesystem interface, like FUSE, we abstract out the needed
    functionality to an abstract driver, injected by hosting application,
    which provides the supported interface.
    """

    def __init__(self, socket_path: Path):
        super().__init__()
        self.socket_path = Path(socket_path)

    def start(self):
        """
        Called to start file system operation.
        """
        apple_log.configure()
        self.uid, self.gid = os.getuid(), os.getgid()
        logger.info('Wildland is starting, control socket: %s',
                        self.socket_path)
        self.control_server.start(self.socket_path)
