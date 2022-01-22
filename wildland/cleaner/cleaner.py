# Wildland Project
#
# Copyright (C) 2022 Golem Foundation
#
# Authors:
#           Aleksandr Birukov <aleksandr.birukov@besidethepark.com>,
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
Module for cleaning up created files in the failure case.
"""

from pathlib import Path
from typing import Set


class Cleaner:
    """
    Class` for cleaning up created files
    """
    _paths: Set[Path] = set()

    def __init__(self, debug_fn=print, warn_fn=print):
        self.debug_fn = debug_fn
        self.warn_fn = warn_fn

    def add_path(self, path: Path):
        """
        Memorises the file path for the future cleaning up.
        """
        self._paths.add(path)

    def clean_up(self):
        """
        Removes all memorised files.
        """
        if not self._paths:
            return

        self.debug_fn('Removing created files.')
        while self._paths:
            path = self._paths.pop()
            try:
                path.unlink()
            except Exception as err:
                self.warn_fn(f'Can\'t remove file {path}: {err}')
