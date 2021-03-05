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
The container
"""
from copy import deepcopy
from pathlib import PurePosixPath, Path
import uuid
from typing import Optional, List, Union
import itertools

from .manifest.manifest import Manifest
from .manifest.schema import Schema


class Container:
    """Wildland container"""
    SCHEMA = Schema('container')

    def __init__(self, *,
                 owner: str,
                 paths: List[PurePosixPath],
                 backends: List[Union[str, dict]],
                 title: Optional[str] = None,
                 categories: Optional[List[PurePosixPath]] = None,
                 local_path: Optional[Path] = None,
                 manifest: Manifest = None,
                 access: Optional[List[dict]] = None):
        self.owner = owner
        # make sure uuid path is first
        self.paths = sorted(paths,
                            key=lambda p: p.parent != PurePosixPath('/.uuid/'))
        self.backends = backends
        self.title = title
        self.categories = categories if categories else []
        self.local_path = local_path
        self._expanded_paths: Optional[List[PurePosixPath]] = None
        self.manifest = manifest
        self.access = access

    def ensure_uuid(self) -> str:
        """
        Find or create an UUID path for this container.
        """

        for path in self.paths:
            if path.parent == PurePosixPath('/.uuid/'):
                return path.name
        ident = str(uuid.uuid4())
        self.paths.insert(0, PurePosixPath('/.uuid/') / ident)
        return ident

    def __str__(self):
        """Friendly text representation of the container"""
        local_str = ''
        if self.local_path:
            local_str = f' ({self.local_path})'
        return f'{self.owner}:{[str(p) for p in self.paths]}' + local_str

    @classmethod
    def from_manifest(cls, manifest: Manifest, local_path=None) -> 'Container':
        """
        Construct a Container instance from a manifest.
        """

        manifest.apply_schema(cls.SCHEMA)
        return cls(
            owner=manifest.fields['owner'],
            paths=[PurePosixPath(p) for p in manifest.fields['paths']],
            backends=manifest.fields['backends']['storage'],
            title=manifest.fields.get('title', None),
            categories=[Path(p) for p in manifest.fields.get('categories', [])],
            local_path=local_path,
            manifest=manifest,
            access=manifest.fields.get('access', None)
        )

    def to_unsigned_manifest(self) -> Manifest:
        """
        Create a manifest based on Container's data.
        Has to be signed separately.
        """

        # remove redundant fields from inline manifest
        cleaned_backends = deepcopy(self.backends)
        for backend in cleaned_backends:
            if not isinstance(backend, dict):
                continue
            if 'owner' in backend:
                del backend['owner']
            if 'container-path' in backend:
                del backend['container-path']
            if 'object' in backend:
                del backend['object']

        fields = {
            "object": type(self).__name__.lower(),
            "owner": self.owner,
            "paths": [str(p) for p in self.paths],
            "backends": {'storage': cleaned_backends},
            "title": self.title,
            "categories": [str(cat) for cat in self.categories],
            "version": Manifest.CURRENT_VERSION}
        if self.access:
            fields['access'] = self.access

        manifest = Manifest.from_fields(fields)
        manifest.apply_schema(self.SCHEMA)
        return manifest

    @property
    def expanded_paths(self):
        """
        Paths expanded by the set of paths generated from title and categories (if provided)

        This method MUST NOT change the order of paths so that /.uuid/{container_uuid} path remains
        first in the list.
        """
        if self._expanded_paths:
            return self._expanded_paths
        paths = self.paths.copy()
        if self.title:
            for path in self.categories:
                paths.append(path / self.title)
            for p1, p2 in itertools.permutations(self.categories, 2):
                subpath = PurePosixPath('@' + str(p2.relative_to(p2.anchor)))
                paths.append(p1 / subpath / self.title)
        self._expanded_paths = paths
        return self._expanded_paths
