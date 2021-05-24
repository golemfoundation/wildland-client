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
Bridge manifest object
"""

from pathlib import PurePosixPath
from typing import Optional, List, Iterable, Union
from copy import deepcopy

from wildland.container import Container
from wildland.manifest.manifest import Manifest
from wildland.wildland_object.wildland_object import WildlandObject
from wildland.manifest.schema import Schema
from wildland.exc import WildlandError


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

    def to_placeholder_container(self) -> Container:
        """
        Create a placeholder container that shows how to mount the target user's forest.
        """

        return Container(
            owner=self.user_id,
            paths=[PurePosixPath('/')],
            backends=[{
                'type': 'static',
                'content': {
                    'WILDLAND-FOREST.txt': \
                        f'This directory holds forest of user {self.user_id}.\n'
                        f'Use \'wl forest mount\' command to get access to it.\n',
                }
            }],
            client=self.client
        )

    def __repr__(self):
        return f'<Bridge: {self.owner}: {", ".join([str(p) for p in self.paths])}>'

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
