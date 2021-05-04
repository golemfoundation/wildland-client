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

from pathlib import PurePosixPath, Path
from typing import Optional, List, Iterable, Union

from .container import Container
from .manifest.manifest import Manifest, WildlandObjectType
from .manifest.schema import Schema
from .manifest.sig import SigContext


class Bridge:
    """
    Bridge object: a wrapper for user manifests.
    """

    SCHEMA = Schema("bridge")
    OBJECT_TYPE = WildlandObjectType.BRIDGE

    def __init__(self, *,
                 owner: str,
                 user_location: Union[str, dict],
                 user_pubkey: str,
                 user_id: str,
                 paths: Iterable[PurePosixPath],
                 local_path: Optional[Path] = None,
                 manifest: Manifest = None):
        self.owner = owner
        self.user_location = user_location
        self.user_pubkey = user_pubkey
        self.user_id = user_id
        self.paths: List[PurePosixPath] = list(paths)
        self.local_path = local_path
        self.manifest = manifest

    @classmethod
    def from_manifest(cls, manifest: Manifest, sig_context: SigContext,
                      local_path=None) -> "Bridge":
        """
        Construct a Container instance from a manifest.
        """

        manifest.apply_schema(cls.SCHEMA)
        return cls(
            owner=manifest.fields['owner'],
            user_location=manifest.fields['user'],
            user_pubkey=manifest.fields['pubkey'],
            user_id=sig_context.fingerprint(manifest.fields['pubkey']),
            paths=[PurePosixPath(p) for p in manifest.fields['paths']],
            local_path=local_path,
            manifest=manifest
        )

    def to_unsigned_manifest(self) -> Manifest:
        """
        Create a manifest based on Bridge's data.
        Has to be signed separately.
        """

        manifest = Manifest.from_fields({
            "object": self.OBJECT_TYPE.value,
            "owner": self.owner,
            "user": self.user_location,
            "pubkey": self.user_pubkey,
            "paths": [str(p) for p in self.paths],
            "version": Manifest.CURRENT_VERSION
        })
        manifest.apply_schema(self.SCHEMA)
        return manifest

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
            }]
        )

    def __repr__(self):
        return f'<Bridge: {self.owner}: {", ".join([str(p) for p in self.paths])}>'
