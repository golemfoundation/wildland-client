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
The container
'''

import logging
from pathlib import PurePosixPath, Path
import uuid
from typing import Optional, List

from .storage.base import AbstractStorage
from .manifest.manifest import Manifest, ManifestError
from .manifest.loader import ManifestLoader
from .manifest.schema import Schema
from .exc import WildlandError


class Container:
    '''Wildland container'''
    SCHEMA = Schema('container')

    def __init__(self, *,
                 signer: str,
                 paths: List[PurePosixPath],
                 backends: List[str],
                 local_path: Optional[Path] = None):
        self.signer = signer
        self.paths = paths
        self.backends = backends
        self.local_path = local_path

    def ensure_uuid(self) -> str:
        '''
        Find or create an UUID path for this container.
        '''

        for path in self.paths:
            if path.parent == PurePosixPath('/.uuid/'):
                return path.name
        ident = str(uuid.uuid4())
        self.paths.insert(0, PurePosixPath('/.uuid/') / ident)
        return ident

    @classmethod
    def from_manifest(cls, manifest: Manifest, local_path=None) -> 'Container':
        '''
        Construct a Container instance from a manifest.
        '''

        manifest.apply_schema(cls.SCHEMA)
        return cls(
            signer=manifest.fields['signer'],
            paths=[PurePosixPath(p) for p in manifest.fields['paths']],
            backends=manifest.fields['backends']['storage'],
            local_path=local_path,
        )

    def to_unsigned_manifest(self) -> Manifest:
        '''
        Create a manifest based on Container's data.
        Has to be signed separately.
        '''

        manifest = Manifest.from_fields(dict(
            signer=self.signer,
            paths=[str(p) for p in self.paths],
            backends={'storage': self.backends},
        ))
        manifest.apply_schema(self.SCHEMA)
        return manifest

    def select_storage(self, loader: ManifestLoader) -> Manifest:
        '''
        Select a storage that we can use for this container.
        Returns a storage manifest.
        '''

        # TODO: currently just file URLs
        for url in self.backends:
            try:
                storage_manifest = self.try_load_manifest(loader, url)
            except WildlandError:
                logging.exception('Error loading manifest: %s', url)
                continue

            return storage_manifest

        raise ManifestError('no supported storage manifest')

    def try_load_manifest(self, loader: ManifestLoader, url: str) -> Manifest:
        '''
        Try loading a storage manifest for this container.
        '''

        try:
            with open(url, 'rb') as f:
                storage_manifest_content = f.read()
        except IOError:
            raise ManifestError(f'Error loading uRL: {url}')

        storage_manifest = loader.parse_manifest(
            storage_manifest_content)
        if not AbstractStorage.is_type_supported(storage_manifest.fields['type']):
            raise ManifestError(f'Unsupported storage manifest: {url}')

        if storage_manifest.fields['signer'] != self.signer:
            raise ManifestError(
                '{}: signer field mismatch: storage {}, container {}'.format(
                    url,
                    storage_manifest.fields['signer'],
                    self.signer))

        container_path = PurePosixPath(storage_manifest.fields['container_path'])
        if container_path not in self.paths:
            raise ManifestError(
                '{}: unrecognized container path for storage: {}, {}'.format(
                    url,
                    container_path,
                    self.paths,
            ))

        return storage_manifest
