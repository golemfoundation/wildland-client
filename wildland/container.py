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
from pathlib import Path

from .storage.base import AbstractStorage
from .manifest.manifest import Manifest, ManifestError
from .manifest.loader import ManifestLoader
from .manifest.schema import Schema


class Container:
    '''Wildland container'''
    SCHEMA = Schema('container')

    def __init__(self, manifest: Manifest):
        self.manifest = manifest
        #: list of paths, under which this container should be mounted
        self.signer = manifest.fields['signer']
        self.paths = [Path(p) for p in manifest.fields['paths']]

    def select_storage(self, loader: ManifestLoader) -> Manifest:
        '''
        Select a storage that we can use for this container.
        Returns a storage manifest.
        '''

        # TODO: currently just file URLs
        urls = self.manifest.fields['backends']['storage']

        for url in urls:
            with open(url, 'rb') as f:
                storage_manifest_content = f.read()

            storage_manifest = loader.parse_manifest(
                storage_manifest_content)
            if not AbstractStorage.is_manifest_supported(storage_manifest):
                logging.info('skipping unsupported manifest: %s', url)

            if storage_manifest.fields['signer'] != self.manifest.fields['signer']:
                raise ManifestError(
                    '{}: signer field mismatch: storage {}, container {}'.format(
                        url,
                        storage_manifest.fields['signer'],
                        self.manifest.fields['signer']))
            if storage_manifest.fields['container_path'] not in self.manifest.fields['paths']:
                raise ManifestError(
                    '{}: unrecognized container path for storage: {}, {}'.format(
                        url,
                        storage_manifest.fields['container_path'],
                        self.manifest.fields['paths']))

            return storage_manifest

        raise ManifestError('no supported storage manifest')
