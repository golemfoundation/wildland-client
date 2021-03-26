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
from pathlib import PurePosixPath, Path
from typing import Dict, Any, Optional, List

from .storage_backends.base import StorageBackend
from .manifest.manifest import Manifest, ManifestError
from .manifest.schema import Schema
from .container import Container

class Storage:
    """
    A data transfer object representing Wildland storage.
    """

    BASE_SCHEMA = Schema('storage')

    DEFAULT_MANIFEST_PATTERN = {'type': 'glob', 'path': '/*.yaml'}

    def __init__(self,
                 owner: str,
                 storage_type: str,
                 container_path: PurePosixPath,
                 trusted: bool,
                 params: Dict[str, Any],
                 manifest_pattern: Optional[Dict[str, Any]] = None,
                 base_url: Optional[str] = None,
                 local_path: Optional[Path] = None,
                 manifest: Manifest = None,
                 access: Optional[List[dict]] = None):

        self.owner = owner
        self.storage_type = storage_type
        self.container_path = container_path
        self.params = params
        self.trusted = trusted
        self.local_path = local_path
        self.manifest_pattern = manifest_pattern
        self.base_url = base_url
        self.manifest = manifest
        self.access = access
        self.primary = self.params.get('primary', False)
        if 'backend-id' not in params:
            self.params['backend-id'] = StorageBackend.generate_hash(params)


    def __repr__(self):
        return (f'{type(self).__name__}('
                f'owner={self.owner!r}, '
                f'storage_type={self.storage_type!r}, '
                f'container_path={self.container_path!r}, '
                f'trusted={self.trusted!r}, '
                f'manifest_pattern={self.manifest_pattern!r}, '
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
        return PurePosixPath(f'/.backends/{container.ensure_uuid()}/{self.backend_id}')

    def validate(self):
        """
        Validate storage assuming it's of a known type.
        This is not done automatically because we might want to load an
        unrecognized storage.
        """

        manifest = self.to_unsigned_manifest()
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
    def from_manifest(cls, manifest: Manifest,
                      local_path=None,
                      local_owners: Optional[List[str]] = None) -> 'Storage':
        """
        Construct a Storage instance from a manifest.
        """

        manifest.apply_schema(cls.BASE_SCHEMA)
        params = manifest.fields
        if local_owners is not None:
            params['is-local-owner'] = manifest.fields['owner'] in local_owners
        return cls(
            owner=manifest.fields['owner'],
            storage_type=manifest.fields['type'],
            container_path=PurePosixPath(manifest.fields['container-path']),
            trusted=manifest.fields.get('trusted', False),
            manifest_pattern=manifest.fields.get('manifest-pattern'),
            base_url=manifest.fields.get('base-url'),
            params=manifest.fields,
            local_path=local_path,
            manifest=manifest,
            access=manifest.fields.get('access', None)
        )

    def _get_manifest_fields(self) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            **self.params,
            'object': type(self).__name__.lower(),
            'owner': self.owner,
            'type': self.storage_type,
            'container-path': str(self.container_path),
            'version': Manifest.CURRENT_VERSION
        }
        if self.trusted:
            fields['trusted'] = True
        if self.manifest_pattern:
            fields['manifest-pattern'] = self.manifest_pattern
        if self.base_url:
            fields['base-url'] = self.base_url
        if self.access:
            fields['access'] = self.access
        if 'is-local-owner' in fields:
            del fields['is-local-owner']
        return fields

    def to_unsigned_manifest(self) -> Manifest:
        """
        Create a manifest based on Storage's data.
        Has to be signed separately.
        """

        manifest = Manifest.from_fields(self._get_manifest_fields())
        manifest.apply_schema(self.BASE_SCHEMA)
        return manifest
