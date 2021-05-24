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
User manifest and user management
"""

from pathlib import PurePosixPath
from typing import List, Optional, Union
from copy import deepcopy

import logging

from wildland.wildland_object.wildland_object import WildlandObject
from .manifest.manifest import Manifest, ManifestError
from .manifest.schema import Schema
from .exc import WildlandError


logger = logging.getLogger('user')


class _InfraCache:
    """Helper object to manage infrastructure cache"""
    def __init__(self, infrastructure, cached_infra):
        self.infrastructure = infrastructure
        self.cached_infra = cached_infra

    def get(self, client, owner):
        """
        Retrieve a cached storage object or construct it if needed (for construction it needs
        client and owner).
        """
        if not self.cached_infra:
            try:
                self.cached_infra = client.load_object_from_url_or_dict(
                    WildlandObject.Type.CONTAINER, self.infrastructure, owner)
            except (ManifestError, WildlandError) as ex:
                logger.warning('User %s: cannot load infrastructure: %s', owner, str(ex))
                return None
        return self.cached_infra

    def __eq__(self, other):
        return self.infrastructure == other.infrastructure


class User(WildlandObject, obj_type=WildlandObject.Type.USER):
    """
    A data transfer object representing Wildland user.
    Can be converted from/to a self-signed user manifest.
    """

    SCHEMA = Schema('user')

    def __init__(self,
                 owner: str,
                 pubkeys: List[str],
                 paths: List[PurePosixPath],
                 infrastructures: List[Union[str, dict]],
                 client,
                 manifest: Manifest = None):
        super().__init__()
        self.owner = owner
        self.paths = paths

        self._infrastructures = [_InfraCache(infra, None) for infra in infrastructures]

        self.pubkeys = pubkeys
        self.manifest = manifest
        self.client = client

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest: Optional[Manifest] = None, **kwargs):
        pubkey = kwargs.get('pubkey', None)
        if pubkey and pubkey not in fields['pubkeys']:
            fields['pubkeys'].insert(0, pubkey)

        return cls(
            owner=fields['owner'],
            pubkeys=fields['pubkeys'],
            paths=[PurePosixPath(p) for p in fields['paths']],
            infrastructures=deepcopy(fields.get('infrastructures', [])),
            manifest=manifest,
            client=client)

    def load_infrastractures(self):
        """Load and cache all of user's infrastructures."""
        assert self.client
        for infra_with_cache in self._infrastructures:
            infra = infra_with_cache.get(self.client, self.owner)
            if infra:
                yield infra

    def get_infrastructure_descriptions(self):
        """Provide a human-readable descriptions of user's infrastructures without loading them."""
        for infr in self._infrastructures:
            yield str(infr.infrastructure)

    def add_infrastructure(self, path: str):
        """Add a path to an infrastructure to user's infrastructures."""
        self._infrastructures.append(_InfraCache(path, None))

    @property
    def primary_pubkey(self):
        """Primary pubkey for signatures. User manifest needs to be signed with this key"""
        return self.pubkeys[0]

    def to_manifest_fields(self, inline: bool) -> dict:
        if inline:
            raise WildlandError('User manifest cannot be inlined.')
        result = {
                'object': 'user',
                'owner': self.owner,
                'paths': [str(p) for p in self.paths],
                'infrastructures': [deepcopy(infra_cache.infrastructure)
                                    for infra_cache in self._infrastructures],
                'pubkeys': self.pubkeys.copy(),
                'version': Manifest.CURRENT_VERSION
            }
        self.SCHEMA.validate(result)
        return result

    def add_user_keys(self, sig_context, add_primary=True):
        """
        Add user keys (primary key only if add_primary is True and any keys listed in "pubkeys"
        field) to the given sig_context.
        """
        if add_primary:
            sig_context.add_pubkey(self.pubkeys[0])
        for additional_pubkey in self.pubkeys[1:]:
            sig_context.add_pubkey(additional_pubkey, self.owner)

    def __eq__(self, other):
        if not isinstance(other, User):
            return NotImplemented
        return (self.owner == other.owner and
                set(self.pubkeys) == set(other.pubkeys))

    def __hash__(self):
        return hash((
            self.owner,
            frozenset(self.pubkeys)
        ))
