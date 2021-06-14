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
User manifest and user management
"""

from pathlib import PurePosixPath
from typing import List, Optional, Union
from copy import deepcopy

import logging

from wildland.wildland_object.wildland_object import WildlandObject
from .manifest.manifest import Manifest
from .manifest.schema import Schema
from .exc import WildlandError


logger = logging.getLogger('user')


class _CatalogCache:
    """Helper object to manage catalog cache"""
    def __init__(self, manifest, cached_object):
        self.manifest = manifest
        self.cached_object = cached_object

    def get(self, client, owner):
        """
        Retrieve a cached container object or construct it if needed (for construction it needs
        client and owner).
        """
        if not self.cached_object:
            try:
                self.cached_object = client.load_object_from_url_or_dict(
                    WildlandObject.Type.CONTAINER, self.manifest, owner)
            except (PermissionError, FileNotFoundError) as ex:
                # Those errors lead to different ways of coping with the error and are caught in
                # search.py
                logger.warning('User %s: cannot load manifests catalog entry: %s', owner, str(ex))
                raise ex
            except Exception as ex:  # pylint: disable=broad-except
                # All other errors should not cause WL to completely give up, and we cannot
                # anticipate all possible kinds of error
                logger.warning('User %s: cannot load manifests catalog entry: %s', owner, str(ex))
                raise WildlandError(f'Cannot load manifests catalog entry: {str(ex)}') from ex
        return self.cached_object

    def __eq__(self, other):
        return self.manifest == other.manifest


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
                 manifests_catalog: List[Union[str, dict]],
                 client,
                 manifest: Manifest = None):
        super().__init__()
        self.owner = owner
        self.paths = paths

        self._manifests_catalog = [_CatalogCache(manifest, None) for manifest in manifests_catalog]

        self.pubkeys = pubkeys
        self.manifest = manifest
        self.client = client

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

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

    def to_str(self):
        """
        Return string representation
        """
        array_repr = [
            f"owner={self.owner}",
            f"paths={[str(p) for p in self.paths]}"
        ]
        str_repr = "user(" + ", ".join(array_repr) + ")"
        return str_repr

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest: Optional[Manifest] = None, **kwargs):
        pubkey = kwargs.get('pubkey')
        if pubkey and pubkey not in fields['pubkeys']:
            fields['pubkeys'].insert(0, pubkey)

        return cls(
            owner=fields['owner'],
            pubkeys=fields['pubkeys'],
            paths=[PurePosixPath(p) for p in fields['paths']],
            manifests_catalog=deepcopy(fields.get('manifests-catalog', [])),
            manifest=manifest,
            client=client)

    @property
    def has_catalog(self) -> bool:
        """Checks if user has a manifest catalog defined"""
        return bool(self._manifests_catalog)

    def load_catalog(self):
        """Load and cache all of user's manifests catalog."""
        assert self.client
        for cached_object in self._manifests_catalog:
            try:
                container = cached_object.get(self.client, self.owner)
            except WildlandError:
                continue
            if container:
                yield container

    def get_catalog_descriptions(self):
        """Provide a human-readable descriptions of user's manifests catalog without loading
        them."""
        for cached_object in self._manifests_catalog:
            yield str(cached_object.manifest)

    def add_catalog_entry(self, path: str):
        """Add a path to a container to user's manifests catalog."""
        self._manifests_catalog.append(_CatalogCache(path, None))

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
                'manifests-catalog': [deepcopy(cached_object.manifest)
                                      for cached_object in self._manifests_catalog],
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
