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
Wildland environment for Linux systems.
"""
from .config import Config

class WLEnv:
    """
    Base environment for Wildland.
    """

    #pylint: disable=no-self-use
    def load_config(self, params: dict = None) -> Config:
        """
        load an instance of Config object, optionally
        using passed params to initialize it in a
        platform-specific way.
        """

        base_dir = None
        if params:
            base_dir = params.get('base_dir', None)
        return Config.load(base_dir)
