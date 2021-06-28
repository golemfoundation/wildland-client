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
Bridge manifest object
"""

from pathlib import PurePosixPath
from typing import Optional, List, Iterable, Union
from copy import deepcopy
from uuid import UUID, uuid5

from wildland.container import Container
from wildland.manifest.manifest import Manifest
from wildland.wildland_object.wildland_object import WildlandObject
from wildland.manifest.schema import Schema
from wildland.exc import WildlandError

# An arbitrary UUID namespace, used to generate deterministic UUID of a bridge
# placeholder container. See `Bridge.to_placeholder_container()` below.
BRIDGE_PLACEHOLDER_UUID_NS = UUID('4a9a69d0-6f32-4ab5-8d4e-c198bf582554')


class Bridge(WildlandObject, obj_type=WildlandObject.Type.BRIDGE):
    """
    Bridge object: a wrapper for user manifests.
    """

    SCHEMA = Schema("bridge")

    def __init__(self,
                 owner: str,
                 user_location: Union[str, dict],
                 user_pubkey: str,
                 user_id: str,
                 paths: Iterable[PurePosixPath],
                 client,
                 manifest: Manifest = None):
        super().__init__()
        self.owner = owner
        self.user_location = deepcopy(user_location)
        self.user_pubkey = user_pubkey
        self.user_id = user_id
        self.paths: List[PurePosixPath] = list(paths)
        self.manifest = manifest
        self.client = client

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest: Optional[Manifest] = None, **kwargs):
        return cls(
                owner=fields['owner'],
                user_location=fields['user'],
                user_pubkey=fields['pubkey'],
                user_id=client.session.sig.fingerprint(fields['pubkey']),
                paths=[PurePosixPath(p) for p in fields['paths']],
                client=client,
                manifest=manifest
            )

    def to_manifest_fields(self, inline: bool) -> dict:
        if inline:
            raise WildlandError('Bridge manifest cannot be inlined.')
        result = {
            "object": WildlandObject.Type.BRIDGE.value,
            "owner": self.owner,
            "user": deepcopy(self.user_location),
            "pubkey": self.user_pubkey,
            "paths": [str(p) for p in self.paths],
            "version": Manifest.CURRENT_VERSION
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
            del fields["user"]
        return fields

    def to_placeholder_container(self) -> Container:
        """
        Create a placeholder container that shows how to mount the target user's forest.
        """
        uuid = uuid5(BRIDGE_PLACEHOLDER_UUID_NS, self.user_id)
        return Container(
            owner=self.user_id,
            paths=[PurePosixPath('/.uuid/' + str(uuid)), PurePosixPath('/')],
            backends=[{
                'type': 'static',
                'backend-id': str(uuid),
                'content': {
                    'WILDLAND-FOREST.txt': \
                        f'This directory holds forest of user {self.user_id}.\n'
                        f'Use \'wl forest mount\' command to get access to it.\n',
                }
            }],
            client=self.client
        )

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

    def __eq__(self, other):
        if not isinstance(other, Bridge):
            return NotImplemented
        return (self.owner == other.owner and
                self.user_pubkey == other.user_pubkey and
                set(self.paths) == set(other.paths) and
                self.user_location == other.user_location)

    def __hash__(self):
        return hash((
            self.owner,
            self.user_pubkey,
            frozenset(self.paths),
            repr(self.user_location),
        ))

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr = [
            f"owner={fields['owner']!r}",
            f"paths={[str(p) for p in fields['paths']]}"
        ]
        str_repr = "bridge(" + ", ".join(array_repr) + ")"
        return str_repr
