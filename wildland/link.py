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
from wildland.wildland_object.wildland_object import WildlandObject
from .storage_driver import StorageDriver
from .exc import WildlandError
from .manifest.schema import Schema


class Link(WildlandObject, obj_type=WildlandObject.Type.LINK):
    """Wildland Link helper object"""

    SCHEMA = Schema({"$ref": "/schemas/types.json#linked-file"})

    def __init__(self,
                 file_path: Union[str, PurePosixPath],
                 storage=None,
                 storage_backend=None,
                 storage_driver=None,
                 file_bytes: Optional[bytes] = None):
        super().__init__()
        assert storage or storage_backend or storage_driver
        if storage_driver:
            self.storage_driver = storage_driver
        elif storage:
            self.storage_driver = StorageDriver.from_storage(storage=storage)
        else:
            self.storage_driver = StorageDriver(storage_backend=storage_backend)
        self.file_path = PurePosixPath(file_path)
        self.file_bytes = file_bytes

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest=None, **kwargs):
        # this method is currently unused, due to manual handling of Link objects
        storage = client.load_object_from_dict(WildlandObject.Type.STORAGE, fields['storage'],
                                               container_path='/')
        storage_driver = StorageDriver.from_storage(storage)
        return cls(
            file_path=PurePosixPath(fields['file']),
            storage_driver=storage_driver,
            file_bytes=None
        )

    @classmethod
    def from_manifest(cls, manifest, client,
                      object_type=None, **kwargs):
        raise WildlandError('Link object cannot be an independent manifest')

    def to_manifest_fields(self, inline: bool):
        return {
            'object': 'link',
            'storage': self.storage_driver.storage_backend.params,
            'file': str(self.file_path)
        }

    def get_target_file(self) -> bytes:
        """
        Returns a (potentially) cached bytes of the target file object.
        """
        if self.file_bytes is None:
            with self.storage_driver:
                self.file_bytes = self.storage_driver.read_file(self.file_path.relative_to('/'))
        return self.file_bytes
