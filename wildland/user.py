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
User manifest and user management
'''

from pathlib import Path, PurePosixPath
from typing import List, Optional
import logging

from .manifest.manifest import Manifest
from .manifest.schema import Schema


logger = logging.getLogger('user')


class User:
    '''
    A data transfer object representing Wildland user.
    Can be converted from/to a self-signed user manifest.
    '''

    SCHEMA = Schema('user')

    def __init__(self, *,
                 signer: str,
                 pubkey: str,
                 paths: List[PurePosixPath],
                 containers: List[str],
                 local_path: Optional[Path] = None):
        self.signer = signer
        self.pubkey = pubkey
        self.paths = paths
        self.containers = containers
        self.local_path = local_path

    @classmethod
    def from_manifest(cls, manifest: Manifest, pubkey: str, local_path=None) -> 'User':
        '''
        Construct a User instance from a manifest.
        A public key needs to be provided as well.
        '''

        # TODO: local_path should be also part of Manifest?

        signer = manifest.fields['signer']
        manifest.apply_schema(cls.SCHEMA)

        if 'containers' in manifest.fields:
            logger.warning("deprecated 'containers' field in user manifest "
                           "(renamed to 'infrastructure-containers'), ignoring")

        return cls(
            signer=signer,
            pubkey=pubkey,
            paths=[PurePosixPath(p) for p in manifest.fields['paths']],
            containers=manifest.fields.get('infrastructure-containers', []),
            local_path=local_path,
        )

    def to_unsigned_manifest(self) -> Manifest:
        '''
        Create a manifest based on User's data.
        Has to be signed separately.
        '''

        manifest = Manifest.from_fields({
            'signer': self.signer,
            'paths': [str(p) for p in self.paths],
            'infrastructure-containers': self.containers,
        })
        manifest.apply_schema(self.SCHEMA)
        return manifest
