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
from typing import List, Optional, Union
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
                 owner: str,
                 pubkeys: List[str],
                 paths: List[PurePosixPath],
                 containers: List[Union[str, dict]],
                 local_path: Optional[Path] = None):
        self.owner = owner
        self.paths = paths
        self.containers = containers
        self.local_path = local_path
        self.pubkeys = pubkeys

    @classmethod
    def from_manifest(cls, manifest: Manifest, pubkey, local_path=None) -> 'User':
        '''
        Construct a User instance from a manifest.
        Requires public key for backwards compatibility.
        '''

        # TODO: local_path should be also part of Manifest?

        owner = manifest.fields['owner']
        manifest.apply_schema(cls.SCHEMA)

        if 'containers' in manifest.fields:
            logger.warning("deprecated 'containers' field in user manifest "
                           "(renamed to 'infrastructures'), ignoring")

        pubkeys = manifest.fields.get('pubkeys', [])
        if pubkey not in pubkeys:
            pubkeys = [pubkey] + pubkeys

        return cls(
            owner=owner,
            pubkeys=pubkeys,
            paths=[PurePosixPath(p) for p in manifest.fields['paths']],
            containers=manifest.fields.get('infrastructures', []),
            local_path=local_path,
        )

    def to_unsigned_manifest(self) -> Manifest:
        '''
        Create a manifest based on User's data.
        Has to be signed separately.
        '''

        manifest = Manifest.from_fields({
            'object': type(self).__name__.lower(),
            'owner': self.owner,
            'paths': [str(p) for p in self.paths],
            'infrastructures': self.containers,
            'pubkeys': self.pubkeys,
        })
        manifest.apply_schema(self.SCHEMA)
        return manifest

    def add_user_keys(self, sig_context):
        """
        Add all user keys (primary key and any keys listed in "pubkeys" field) to the given
        sig_context.
        """
        sig_context.add_pubkey(self.pubkeys[0])
        for additional_pubkey in self.pubkeys[1:]:
            sig_context.add_pubkey(additional_pubkey, self.owner)
