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
Darwin OS environment for Wildland.
"""

from ..wlenv import WLEnv
from .config import MacConfig


class MacEnv(WLEnv):
    """
    A WLEnv specialization for macOS/Darwin environment.
    """

    def load_config(self, params: dict = None) -> MacConfig:
        """
        mac specific config provider
        """
        return MacConfig.shared()
