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

'''
Storage class
'''
import hashlib
import uuid
from pathlib import PurePosixPath, Path
from typing import Dict, Any, Optional

import yaml

from .storage_backends.base import StorageBackend
from .manifest.manifest import Manifest, ManifestError
from .manifest.schema import Schema


class Storage:
    '''
    A data transfer object representing Wildland storage.
    '''

    BASE_SCHEMA = Schema('storage')

    DEFAULT_MANIFEST_PATTERN = {'type': 'glob', 'path': '/{path}.yaml'}

    def __init__(self,
                 owner: str,
                 storage_type: str,
                 container_path: PurePosixPath,
                 trusted: bool,
                 params: Dict[str, Any],
                 manifest_pattern: Optional[Dict[str, Any]] = None,
                 local_path: Optional[Path] = None):
        self.owner = owner
        self.storage_type = storage_type
        self.container_path = container_path
        self.params = params
        self.trusted = trusted
        self.local_path = local_path
        self.manifest_pattern = manifest_pattern
        if 'backend-id' not in params:
            hasher = hashlib.md5()
            # skip 'storage' object if present, it is derived from reference-container
            params_for_hash = dict((k, v) for (k, v) in params.items()
                                   if k != 'storage')
            hasher.update(yaml.dump(params_for_hash, sort_keys=True).encode('utf-8'))
            self.params['backend-id'] = str(uuid.UUID(hasher.hexdigest()))

    def __repr__(self):
        return (f'{type(self).__name__}('
            f'owner={self.owner!r}, '
            f'storage_type={self.storage_type!r}, '
            f'container_path={self.container_path!r}, '
            f'trusted={self.trusted!r}, '
            f'manifest_pattern={self.manifest_pattern!r}, '
            f'local_path={self.local_path!r})')

    def validate(self):
        '''
        Validate storage assuming it's of a known type.
        This is not done automatically because we might want to load an
        unrecognized storage.
        '''

        manifest = self.to_unsigned_manifest()
        if not StorageBackend.is_type_supported(self.storage_type):
            raise ManifestError(f'Unrecognized storage type: {self.storage_type}')
        backend = StorageBackend.types()[self.storage_type]
        manifest.apply_schema(backend.SCHEMA)

    @classmethod
    def from_manifest(cls, manifest: Manifest, local_path=None) -> 'Storage':
        '''
        Construct a Storage instance from a manifest.
        '''

        manifest.apply_schema(cls.BASE_SCHEMA)
        return cls(
            owner=manifest.fields['owner'],
            storage_type=manifest.fields['type'],
            container_path=PurePosixPath(manifest.fields['container-path']),
            trusted=manifest.fields.get('trusted', False),
            manifest_pattern=manifest.fields.get('manifest-pattern'),
            params=manifest.fields,
            local_path=local_path,
        )

    def _get_manifest_fields(self) -> Dict[str, Any]:
        fields: Dict[str, Any] = {
            **self.params,
            'object': type(self).__name__.lower(),
            'owner': self.owner,
            'type': self.storage_type,
            'container-path': str(self.container_path),
        }
        if self.trusted:
            fields['trusted'] = True
        if self.manifest_pattern:
            fields['manifest-pattern'] = self.manifest_pattern
        return fields

    def to_unsigned_manifest(self) -> Manifest:
        '''
        Create a manifest based on Storage's data.
        Has to be signed separately.
        '''

        manifest = Manifest.from_fields(self._get_manifest_fields())
        manifest.apply_schema(self.BASE_SCHEMA)
        return manifest
