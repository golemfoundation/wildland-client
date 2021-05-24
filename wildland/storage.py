# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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
                 base_url: Optional[str] = None,
                 manifest: Manifest = None,
                 access: Optional[List[dict]] = None):
        super().__init__()
        self.owner = owner
        self.storage_type = storage_type
        self.container_path = container_path
        self.params = deepcopy(params)
        self.trusted = trusted
        self.base_url = base_url
        self.manifest = manifest
        self.access = deepcopy(access)
        self.primary = self.params.get('primary', False)
        self.client = client
        if 'backend-id' not in params:
            self.params['backend-id'] = StorageBackend.generate_hash(params)

    def __repr__(self):
        return (f'storage('
                f'owner={self.owner!r}, '
                f'storage_type={self.storage_type!r}, '
                f'container_path={self.container_path!r}, '
                f'trusted={self.trusted!r}, '
                f'base_url={self.base_url!r}, '
                f'local_path={self.local_path!r}, '
                f'access={self.access!r}, '
                f'backend_id={self.params["backend-id"]!r})')

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
        cls.BASE_SCHEMA.validate(fields)
        params = fields

        if 'local_owners' in kwargs and kwargs['local_owners'] is not None:
            params['is-local-owner'] = fields['owner'] in kwargs['local_owners']
        else:
            params['is-local-owner'] = False
        return cls(
            owner=fields['owner'],
            storage_type=fields['type'],
            container_path=PurePosixPath(fields['container-path']),
            trusted=fields.get('trusted', False),
            base_url=fields.get('base-url'),
            params=params,
            client=client,
            manifest=manifest,
            access=fields.get('access', None)
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
        if self.base_url:
            fields['base-url'] = self.base_url
        if self.access:
            fields['access'] = deepcopy(self.access)

        self.BASE_SCHEMA.validate(fields)

        if inline:
            del fields['owner']
            del fields['container-path']
            del fields['version']
            del fields['object']

        if 'is-local-owner' in fields:
            del fields['is-local-owner']
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
