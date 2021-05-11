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
from typing import Optional, List, Union, Any
import itertools

from .manifest.manifest import Manifest, WildlandObjectType, ManifestError
from .manifest.schema import Schema
from .wlpath import WildlandPath


class Container:
    """Wildland container"""
    SCHEMA = Schema('container')
    OBJECT_TYPE = WildlandObjectType.CONTAINER

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
        self.ensure_uuid()

    def ensure_uuid(self) -> str:
        """
        Get the UUID of this container, create if necessary.
        """
        return self.get_uuid_path().name

    def get_uuid_path(self) -> PurePosixPath:
        """
        Find or create an UUID path for this container.
        """
        for path in self.paths:
            if path.parent == PurePosixPath('/.uuid/'):
                return path
        path = PurePosixPath('/.uuid/') / str(uuid.uuid4())
        self.paths.insert(0, path)
        return path

    def __str__(self):
        """Friendly text representation of the container."""
        local_str = ''
        if self.local_path:
            local_str = f' ({self.local_path})'
        return f'{self.owner}:{[str(p) for p in self.paths]}' + local_str

    def __repr__(self):
        return (f'{self.OBJECT_TYPE.value}('
                f'owner={self.owner!r}, '
                f'paths={self.paths!r}, '
                f'backends={self.backends!r}, '
                f'title={self.title!r}, '
                f'categories={self.categories!r}, '
                f'local_path={self.local_path!r}, '
                f'manifest={self.manifest!r}, '
                f'access={self.access!r})')

    def __eq__(self, other):
        if not isinstance(other, Container):
            return NotImplemented
        return (self.owner == other.owner and
                set(self.paths) == set(other.paths) and
                self.title == other.title and
                set(self.categories) == set(other.categories))

    def __hash__(self):
        return hash((
            self.owner,
            frozenset(self.paths),
            self.title,
            frozenset(self.categories),
        ))

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
            categories=[PurePosixPath(p)
                for p in manifest.fields.get('categories', [])],
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
        cleaned_backends = []

        for backend in deepcopy(self.backends):
            if isinstance(backend, dict):
                backend_manifest = Manifest.from_fields(backend)
                backend_manifest.remove_redundant_inline_manifest_keys()
                backend_manifest.skip_verification()
                cleaned_backends.append(backend_manifest.fields)
            else:
                cleaned_backends.append(backend)

        fields: dict[str, Any] = {
            "object": self.OBJECT_TYPE.value,
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
        Paths expanded by the set of paths generated from title and categories (if provided).

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


class ContainerStub:
    """
    Helper Wildland Object, representing a subcontainer that has not yet been completely filled
    with data from parent container.
    """
    def __init__(self, fields: dict):
        self.fields = fields

    @classmethod
    def from_manifest(cls, manifest: Manifest):
        """
        Create ContainerStub from verified manifest.
        """
        return cls(manifest.fields)

    def get_container(self, parent_container: Container) -> Container:
        """
        Fill container fields with data from parent_container and construct a complete Container.
        """
        if 'owner' in self.fields and self.fields['owner'] != parent_container.owner:
            raise ManifestError(f'Unexpected owner for subcontainer. Expected '
                                f'{parent_container.owner}, received {self.fields["owner"]}')
        self.fields['object'] = 'container'
        self.fields['owner'] = parent_container.owner
        self.fields['version'] = Manifest.CURRENT_VERSION
        if 'backends' not in self.fields or 'storage' not in self.fields['backends']:
            backends = []
        else:
            backends = self.fields['backends']['storage']
        for sub_storage in backends:
            if not isinstance(sub_storage, dict) or \
                    sub_storage.get('object', 'storage') != 'storage':
                continue
            sub_storage['object'] = 'storage'
            sub_storage['owner'] = parent_container.owner
            self.fields['version'] = Manifest.CURRENT_VERSION
            sub_storage['container-path'] = self.fields['paths'][0]
            if isinstance(sub_storage.get('reference-container'), str) and \
                    WildlandPath.match(sub_storage['reference-container']):
                sub_storage['reference-container'] = \
                    sub_storage['reference-container'].replace(
                        ':@parent-container:', f':{parent_container.paths[0]}:')

        manifest = Manifest.from_fields(self.fields)
        manifest.skip_verification()
        return Container.from_manifest(manifest)
