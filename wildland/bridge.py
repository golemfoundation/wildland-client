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

from .manifest.manifest import Manifest
from .manifest.schema import Schema


class Bridge:
    """
    Bridge object: a wrapper for user manifests.
    """

    SCHEMA = Schema("bridge")

    def __init__(self, *,
                 owner: str,
                 user_location: Union[str, dict],
                 user_pubkey: str,
                 paths: Iterable[PurePosixPath],
                 local_path: Optional[Path] = None,
                 manifest: Manifest = None):
        self.owner = owner
        self.user_location = user_location
        self.user_pubkey = user_pubkey
        self.paths: List[PurePosixPath] = list(paths)
        self.local_path = local_path
        self.manifest = manifest

    @classmethod
    def from_manifest(cls, manifest: Manifest, local_path=None) -> "Bridge":
        """
        Construct a Container instance from a manifest.
        """

        manifest.apply_schema(cls.SCHEMA)
        return cls(
            owner=manifest.fields['owner'],
            user_location=manifest.fields['user'],
            user_pubkey=manifest.fields['pubkey'],
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
            "object": type(self).__name__.lower(),
            "owner": self.owner,
            "user": self.user_location,
            "pubkey": self.user_pubkey,
            "paths": [str(p) for p in self.paths],
            "version": Manifest.CURRENT_VERSION
        })
        manifest.apply_schema(self.SCHEMA)
        return manifest

    def __repr__(self):
        return f'<Bridge: {self.owner}: {", ".join([str(p) for p in self.paths])}>'
