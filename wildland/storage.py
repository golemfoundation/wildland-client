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
import os
from pathlib import PurePosixPath
from typing import Dict, Any, Optional, List
from copy import deepcopy

from wildland.wildland_object.wildland_object import WildlandObject, PublishableWildlandObject
from .log import get_logger
from .exc import WildlandError
from .storage_backends.base import StorageBackend
from .manifest.manifest import Manifest, ManifestError
from .manifest.schema import Schema
from .container import Container

logger = get_logger('storage')


class Storage(PublishableWildlandObject, obj_type=WildlandObject.Type.STORAGE):
    """
    A data transfer object representing Wildland storage.
    """

    BASE_SCHEMA = Schema('storage')

    def __init__(self,
                 owner: str,
                 storage_type: str,
                 trusted: bool,
                 params: Dict[str, Any],
                 client,
                 container: Container = None,
                 manifest: Manifest = None,
                 access: Optional[List[dict]] = None):
        super().__init__()
        self.owner = owner
        self.storage_type = storage_type
        self.container = container
        self.params = deepcopy(params)
        self.trusted = trusted
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
        if self._str_repr:
            return self._str_repr
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr = []
        for field in ['owner', 'storage-type', 'backend-id', 'container-path', 'trusted',
                      'container-path', 'local-path', 'access', 'location',
                      'read-only']:
            if fields.get(field, None):
                array_repr += [f"{field}={fields[field]!r}"]
        self._str_repr = "storage(" + ", ".join(array_repr) + ")"
        return self._str_repr

    def get_unique_publish_id(self) -> str:
        assert self.container, 'Storages without Container are not publishable'

        return f'{self.container.get_unique_publish_id()}.{self.backend_id}'

    def get_primary_publish_path(self) -> PurePosixPath:
        return PurePosixPath('/.uuid/') / self.get_unique_publish_id()

    def get_publish_paths(self) -> List[PurePosixPath]:
        return [self.get_primary_publish_path()]

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

        if self.client.is_local_storage(self.storage_type):
            location = manifest.fields['location']
            # warn user if location doesn't point to existing directory
            if not os.path.isdir(location):
                logger.warning('Storage location "%s" does not point to existing directory',
                               location)

    def promote_to_primary(self):
        """
        Sets primary param to True.
        """
        self._str_repr = None
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

        # Create a dummy container that contains only information known to the Storage
        container = Container(
            owner=params['owner'],
            paths=[PurePosixPath(params['container-path'])],
            backends=[fields],
            client=client
        )

        return cls(
            owner=params['owner'],
            storage_type=storage_type,
            trusted=params.get('trusted', False),
            params=params,
            client=client,
            manifest=manifest,
            container=container,
            access=params.get('access')
        )

    def to_manifest_fields(self, inline: bool, str_repr_only: bool = False) -> dict:
        container_path = None

        if self.container:
            container_path = str(self.container.get_primary_publish_path())

        fields: Dict[str, Any] = {
            'version': Manifest.CURRENT_VERSION,
            'object': 'storage',
            'owner': self.owner,
            'type': self.storage_type,
            'container-path': container_path,
            **self.params,
        }

        if self.trusted:
            fields['trusted'] = True
        if self.access:
            fields['access'] = self.client.load_pubkeys_from_field(self.access, self.owner)

        self.BASE_SCHEMA.validate(fields)

        if inline:
            del fields['owner']
            del fields['container-path']
            del fields['version']

        if 'is-local-owner' in fields:
            del fields['is-local-owner']

        if 'storage' in fields:
            del fields['storage']

        return fields

    def to_repr_fields(self, include_sensitive: bool = False) -> dict:
        """
        This function provides filtered sensitive and unneeded fields for representation
        """
        nonsensitive_storage_fields = ["owner", "type", "version", "backend-id"]

        fields = {}
        manifest_fields = self.to_manifest_fields(inline=True, str_repr_only=True)
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
        del new_params['container-path']

        container: Optional[Container] = None

        if self.container:
            container_fields = self.container.to_manifest_fields(inline=False)
            container_fields['paths'][0] = PurePosixPath(
                str(self.container.get_primary_publish_path()).replace(old_uuid, new_uuid)
            )
            container = Container.parse_fields(container_fields, self.client)

        new_storage = Storage(
            storage_type=self.storage_type,
            owner=self.owner,
            params=new_params,
            client=self.client,
            trusted=self.trusted,
            container=container)
        return new_storage


def _get_storage_by_id_or_type(id_or_type: str, storages: List[Storage]) -> Storage:
    """
    Helper function to find a storage by listed id or type.
    """
    try:
        return [storage for storage in storages
                if id_or_type in (storage.backend_id, storage.params['type'])][0]
    except IndexError:
        # pylint: disable=raise-missing-from
        raise WildlandError(f'Storage {id_or_type} not found')
