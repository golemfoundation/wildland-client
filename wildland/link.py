# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Helper link object.
"""

from typing import Union, Optional
from pathlib import PurePosixPath
from wildland.wildland_object.wildland_object import WildlandObject
from .storage_driver import StorageDriver
from .exc import WildlandError
from .manifest.manifest import Manifest
from .manifest.schema import Schema


class Link(WildlandObject, obj_type=WildlandObject.Type.LINK):
    """Wildland Link helper object"""

    SCHEMA = Schema({"$ref": "/schemas/types.json#linked-file"})

    def __init__(self,
                 file_path: Union[str, PurePosixPath],
                 client,
                 storage=None,
                 storage_owner=None,
                 storage_backend=None,
                 storage_driver=None,
                 file_bytes: Optional[bytes] = None):
        super().__init__()
        self.file_path = PurePosixPath(file_path)
        self.client = client
        self.storage_owner = storage_owner
        assert storage or storage_backend or storage_driver
        if storage_driver:
            self.storage_driver = storage_driver
        elif storage:
            self.storage_driver = StorageDriver.from_storage(storage=storage)
        else:
            self.storage_driver = StorageDriver(storage_backend=storage_backend)
        self.file_bytes = file_bytes

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr = [
            f"file_path={fields['file']}"
        ]
        if fields.get('storage', None):
            array_repr += [f"storage={fields['storage']}"]
        str_repr = "link(" + ", ".join(array_repr) + ")"
        return str_repr

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest=None, **kwargs):
        if not isinstance(fields['storage'], dict):
            raise ValueError('Incorrect Link object format')
        if 'version' not in fields['storage']:
            fields['storage']['version'] = Manifest.CURRENT_VERSION
        storage_obj = client.load_object_from_dict(
            WildlandObject.Type.STORAGE, fields['storage'],
            owner=fields.get("owner", None) or fields.get("storage-owner", None) \
                or kwargs.get('expected_owner', None),
            expected_owner=fields.get("storage-owner", None) or kwargs.get('expected_owner', None)
        )
        storage_driver = StorageDriver.from_storage(storage_obj)

        return cls(
            file_path=PurePosixPath(fields['file']),
            client=client,
            storage_owner=fields.get("storage-owner", None),
            storage=storage_obj,
            storage_driver=storage_driver,
            file_bytes=None
        )

    @classmethod
    def from_manifest(cls, manifest, client, object_type=None, **kwargs):
        raise WildlandError('Link object cannot be an independent manifest')

    def to_manifest_fields(self, inline: bool, str_repr_only: bool = False):
        if self.storage_driver.storage:
            params = self.storage_driver.storage.to_manifest_fields(inline=True)
        elif str_repr_only:
            params = self.storage_driver.storage_backend.params
        else:
            raise WildlandError('Link object not initialized with Storage')

        if params.get("access"):
            params["access"] = self.client.load_pubkeys_from_field(
                params["access"], '@default-owner')
        fields = {
            'object': 'link',
            'file': str(self.file_path),
            'storage': params
        }
        if self.storage_owner:
            fields["storage-owner"] = self.storage_owner
        return fields

    def to_repr_fields(self, include_sensitive: bool = False) -> dict:
        """
        This function provides filtered sensitive and unneeded fields for representation
        """
        fields = self.to_manifest_fields(inline=True, str_repr_only=True)
        if not include_sensitive:
            del fields['storage']
        elif self.storage_driver.storage_backend:
            fields['storage'] = \
                self.storage_driver.storage_backend.to_str(include_sensitive)
        return fields

    def get_target_file(self) -> bytes:
        """
        Returns a (potentially) cached bytes of the target file object.
        """
        if self.file_bytes is None:
            with self.storage_driver:
                self.file_bytes = self.storage_driver.read_file(self.file_path.relative_to('/'))
        return self.file_bytes
