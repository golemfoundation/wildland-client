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
from .manifest.manifest import Manifest, ManifestDecryptionKeyUnavailableError
from .manifest.schema import Schema
from .exc import WildlandError


logger = logging.getLogger('user')


class _CatalogCache:
    """Helper object to manage catalog cache"""
    def __init__(self, manifest: Union[str, dict], cached_object=None):
        self.manifest = manifest
        self.cached_object = cached_object

    def get(self, client, owner: str):
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
            except ManifestDecryptionKeyUnavailableError as ex:
                raise ex
            except Exception as ex:  # pylint: disable=broad-except
                # All other errors should not cause WL to completely give up, and we cannot
                # anticipate all possible kinds of error
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

        self._manifests_catalog = [_CatalogCache(manifest) for manifest in manifests_catalog]

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

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr = [
            f"owner={fields['owner']}",
            f"paths={[str(p) for p in fields['paths']]}"
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

    def load_catalog(self, warn_about_encrypted_manifests: bool = True):
        """Load and cache all of user's manifests catalog."""
        assert self.client
        total_containers = 0
        undecryptable_containers = 0
        unknown_failure_containers = 0

        for cached_object in self._manifests_catalog:
            total_containers += 1

            try:
                container = cached_object.get(self.client, self.owner)
            except ManifestDecryptionKeyUnavailableError as e:
                undecryptable_containers += 1
                if warn_about_encrypted_manifests:
                    logger.warning('User %s: cannot load manifests catalog entry: %s', self.owner,
                                    str(e))
                continue
            except WildlandError as e:
                unknown_failure_containers += 1
                continue

            if container:
                yield container

        total_failures = undecryptable_containers + unknown_failure_containers

        if total_failures and total_containers == total_failures:
            logger.warning('User %s: failed to load all %d of the manifests catalog containers. '
                           '%d due to lack of decryption key and %d due to unknown errors)',
                           self.owner, total_failures, undecryptable_containers,
                           unknown_failure_containers)

    def get_catalog_descriptions(self):
        """Provide a human-readable descriptions of user's manifests catalog without loading
        them."""
        for cached_object in self._manifests_catalog:
            yield str(cached_object.manifest)

    def add_catalog_entry(self, path: str):
        """Add a path to a container to user's manifests catalog."""
        self._manifests_catalog.append(_CatalogCache(path))

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

    def to_repr_fields(self, include_sensitive: bool = False) -> dict:
        """
        This function provides filtered sensitive and unneeded fields for representation
        """
        fields = self.to_manifest_fields(inline=True)
        if not include_sensitive:
            # Remove sensitive fields
            del fields["manifests-catalog"]
        return fields

    def add_user_keys(self, sig_context, add_primary=True):
        """
        Add user keys (primary key only if add_primary is True and any keys listed in "pubkeys"
        field) to the given sig_context.
        """
        if add_primary:
            sig_context.add_pubkey(self.pubkeys[0])
        for additional_pubkey in self.pubkeys[1:]:
            sig_context.add_pubkey(additional_pubkey, self.owner)
