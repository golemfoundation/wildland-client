# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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

"""
Helper link object.
"""

from typing import Union, Optional
from pathlib import PurePosixPath
from .storage_driver import StorageDriver


class Link:
    """Wildland Link helper object"""

    def __init__(self, storage_backend,
                 file_path: Union[str, PurePosixPath], file_bytes: Optional[bytes] = None):
        self.storage_backend = storage_backend
        self.storage_driver = StorageDriver(storage_backend=self.storage_backend)
        self.file_path = PurePosixPath(file_path)
        self.file_bytes = file_bytes

    def get_target_file(self) -> bytes:
        """
        Returns a (potentially) cached bytes of the target file object.
        """
        if self.file_bytes is None:
            with self.storage_driver:
                self.file_bytes = self.storage_driver.read_file(self.file_path.relative_to('/'))
        return self.file_bytes
