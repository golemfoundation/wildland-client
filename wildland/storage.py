# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Paweł Marczewski <pawel@invisiblethingslab.com>,
#                    Wojtek Porczyk <woju@invisiblethingslab.com>
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
Storage class
"""
from pathlib import PurePosixPath
from typing import Dict, Any, Optional, List
from copy import deepcopy

from wildland.wildland_object.wildland_object import WildlandObject
from .storage_backends.base import StorageBackend
from .manifest.manifest import Manifest, ManifestError
from .manifest.schema import Schema
from .container import Container


class Storage(WildlandObject, obj_type=WildlandObject.Type.STORAGE):
    """
    A data transfer object representing Wildland storage.
    """

    BASE_SCHEMA = Schema('storage')

    def __init__(self,
                 owner: str,
                 storage_type: str,
                 container_path: PurePosixPath,
                 trusted: bool,
                 params: Dict[str, Any],
                 client,
                 public_url: Optional[str] = None,
                 manifest: Manifest = None,
                 access: Optional[List[dict]] = None):
        super().__init__()
        self.owner = owner
        self.storage_type = storage_type
        self.container_path = container_path
        self.params = deepcopy(params)
        self.trusted = trusted
        self.public_url = public_url
        self.manifest = manifest
        self.access = deepcopy(access)
        self.primary = self.params.get('primary', False)
        self.client = client
        if 'backend-id' not in params:
            self.params['backend-id'] = StorageBackend.generate_hash(params)

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr = []
        for field in ['owner', 'storage-type', 'backend-id', 'container-path', 'trusted',
                      'container-path', 'public-url', 'local-path', 'access', 'location',
                      'read-only']:
            if fields.get(field, None):
                array_repr += [f"{field}={fields[field]!r}"]
        str_repr = "storage(" + ", ".join(array_repr) + ")"
        return str_repr

    @property
    def backend_id(self):
        """
        Returns backend_id param.
        """
        return self.params['backend-id']

    @property
    def is_writeable(self) -> bool:
        """
        Returns False if read-only param was set to True.
        """
        return not self.params.get('read-only', False)

    @property
    def is_primary(self) -> bool:
        """
        Returns primary param.
        """
        return self.primary

    def get_mount_path(self, container: Container) -> PurePosixPath:
        # pylint: disable=unused-argument
        """
        Return unique mount path for this storage.
        The path is rooted in the container's owner forest root.
        """
        return PurePosixPath(f'/.backends/{container.uuid}/{self.backend_id}')

    def validate(self):
        """
        Validate storage assuming it's of a known type.
        This is not done automatically because we might want to load an
        unrecognized storage.
        """
        manifest = Manifest.from_fields(self.to_manifest_fields(inline=False))
        if not StorageBackend.is_type_supported(self.storage_type):
            raise ManifestError(f'Unrecognized storage type: {self.storage_type}')
        backend = StorageBackend.types()[self.storage_type]
        manifest.apply_schema(backend.SCHEMA)

    def promote_to_primary(self):
        """
        Sets primary param to True.
        """
        self.primary = True

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest: Optional[Manifest] = None, **kwargs):
        params = fields
        cls.BASE_SCHEMA.validate(params)
        storage_type = params['type']

        if 'reference-container' in params:
            referenced_path_and_storage_params = client.select_reference_storage(
                params['reference-container'],
                params['owner'],
                params.get('trusted', False))
            if referenced_path_and_storage_params:
                referenced_path, params['storage'] = referenced_path_and_storage_params

        storage_cls = StorageBackend.types()[storage_type]

        if storage_cls.MOUNT_REFERENCE_CONTAINER:
            assert referenced_path
            storage_path = str(client.fs_client.mount_dir / referenced_path.relative_to('/'))
            params['storage-path'] = storage_path

        if 'local_owners' in kwargs and kwargs['local_owners']:
            params['is-local-owner'] = params['owner'] in kwargs['local_owners']
        else:
            params['is-local-owner'] = False

        return cls(
            owner=params['owner'],
            storage_type=storage_type,
            container_path=PurePosixPath(params['container-path']),
            trusted=params.get('trusted', False),
            public_url=params.get('public-url'),
            params=params,
            client=client,
            manifest=manifest,
            access=params.get('access')
        )

    def to_manifest_fields(self, inline: bool) -> dict:
        fields: Dict[str, Any] = {
            **self.params,
            'object': 'storage',
            'owner': self.owner,
            'type': self.storage_type,
            'container-path': str(self.container_path),
            'version': Manifest.CURRENT_VERSION
        }

        if self.trusted:
            fields['trusted'] = True
        if self.public_url:
            fields['public-url'] = self.public_url
        if self.access:
            fields['access'] = deepcopy(self.access)

        self.BASE_SCHEMA.validate(fields)

        if inline:
            del fields['owner']
            del fields['container-path']
            del fields['version']

        if 'is-local-owner' in fields:
            del fields['is-local-owner']
        return fields

    def to_repr_fields(self, include_sensitive: bool = False) -> dict:
        """
        This function provides filtered sensitive and unneeded fields for representation
        """
        nonsensitive_storage_fields = ["owner", "type", "version", "backend-id"]

        fields = {}
        manifest_fields = self.to_manifest_fields(inline=True)
        if not include_sensitive:
            for field in nonsensitive_storage_fields:
                if manifest_fields.get(field, None):
                    fields[field] = manifest_fields[field]
        else:
            fields = manifest_fields
        return fields

    def copy(self, old_uuid, new_uuid):
        """
        Copy this storage to a new object, replacing its container uuid
        from old_uuid to new_uuid
        """
        new_params = deepcopy(self.params)
        del new_params['backend-id']
        new_storage = Storage(
            container_path=PurePosixPath(str(self.container_path).replace(
                old_uuid, new_uuid)),
            storage_type=self.storage_type,
            owner=self.owner,
            params=new_params,
            client=self.client,
            trusted=self.trusted)
        return new_storage
