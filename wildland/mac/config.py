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
Mac/Darwin implementation of Config
"""
from pathlib import Path
from ..config import Config


class MacConfig(Config):
    """
    A Config specialization for Darwin OS
    """

    __instance = None

    @staticmethod
    def shared():
        """
        Return (instantiate if neccessary) a singleton
        configuration object.
        """
        if MacConfig.__instance is None:
            MacConfig.__instance = MacConfig()
        return MacConfig.__instance

    def __init__(self):
        super().__init__(None, Path("."), dict(), dict())
        basecfg = Config.load()
        self.base_dir = basecfg.base_dir
        self.path = basecfg.path
        self.default_fields = basecfg.default_fields
        self.file_fields = basecfg.file_fields
