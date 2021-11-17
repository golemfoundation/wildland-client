# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#    Piotr K. Isajew  <piotr@wildland.io>
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
Environment provider for Wildland. This class provides several
objects representing to Wildland its runtime environment in
platform independent way, so that the rest of core code can
rely on this rather than assuming a specific OS on its own.
"""
from typing import Optional

from .wlenv import WLEnv


class EnvProvider:
    """
    Provider class for platform specific environment data.
    """

    __instance: Optional[WLEnv] = None

    @staticmethod
    def shared():
        """
        return shared instance of platform-specific
        environment object.
        """
        if EnvProvider.__instance is None:
            EnvProvider.__instance = WLEnv()
        return EnvProvider.__instance
