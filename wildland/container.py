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
The container
"""
from copy import deepcopy
from pathlib import PurePosixPath, Path
import uuid
from typing import Optional, List, Union, Any, Dict
import itertools

from wildland.wildland_object.wildland_object import WildlandObject, PublishableWildlandObject
from .manifest.manifest import Manifest, ManifestError
from .manifest.schema import Schema
from .wlpath import WildlandPath
from .exc import WildlandError
from .log import get_logger

logger = get_logger('user')


class _StorageCache:
    """
    Helper class representing a cached storage object.
    """

    def __init__(self, storage, container, cached_storage=None):
        self.storage = storage
        self.cached_backend = cached_storage
        self.container = container

    def get(self, client, owner):
        """
        Retrieve a cached storage object or construct it if needed (for construction it needs
        client and owner).
        """
        if not self.cached_backend:
            self.cached_backend = client.load_object_from_url_or_dict(
                WildlandObject.Type.STORAGE, self.storage, owner, container=self.container)
        return self.cached_backend

    def __eq__(self, other):
        return self.storage == other.storage


class Container(PublishableWildlandObject, obj_type=WildlandObject.Type.CONTAINER):
    """Wildland container"""
    SCHEMA = Schema('container')

    def __init__(self,
                 owner: str,
                 paths: List[PurePosixPath],
                 backends: List[Union[str, dict]],
                 client,
                 title: Optional[str] = None,
                 categories: Optional[List[PurePosixPath]] = None,
                 manifest: Manifest = None,
                 access: Optional[List[dict]] = None):
        super().__init__()
        self.owner = owner
        # make sure uuid path is first
        self.paths = sorted(paths, key=lambda p: p.parent != PurePosixPath('/.uuid/'))
        self.title = title
        self.categories = deepcopy(categories) if categories else []
        self.client = client
        self._expanded_paths: Optional[List[PurePosixPath]] = None
        self.manifest = manifest
        self.access = deepcopy(access)

        #: whether this container is a manifests catalog, loaded by iterating this
        #: manifests catalog itself; this property is set externally by the
        #: Search class, when loading a container by iterating a manifest catalog
        self.is_manifests_catalog = False

        self._uuid_path = self._ensure_uuid()
        self._storage_cache = [_StorageCache(self.fill_storage_fields(b), self)
                               for b in deepcopy(backends)]

    @property
    def uuid_path(self) -> PurePosixPath:
        """ The main UUID path for this container """
        return self._uuid_path

    @property
    def uuid(self) -> str:
        """ Container UUID"""
        return self.uuid_path.name

    @property
    def sync_id(self) -> str:
        """
        Return unique sync job ID for a container.
        """
        return self.owner + '|' + self.uuid

    def _ensure_uuid(self) -> PurePosixPath:
        """
        Find or create an UUID path for this container.
        """
        for path in self.paths:
            if path.parent == PurePosixPath('/.uuid/'):
                return path
        path = PurePosixPath('/.uuid/') / str(uuid.uuid4())
        self.paths.insert(0, path)
        return path

    def get_unique_publish_id(self) -> str:
        return self.uuid

    def get_primary_publish_path(self) -> PurePosixPath:
        return self.uuid_path

    def get_publish_paths(self) -> List[PurePosixPath]:
        return self.expanded_paths

    def __str__(self):
        return self.to_str()

    def __repr__(self):
        return self.to_str()

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

    def to_str(self, include_sensitive=False):
        """
        Return string representation
        """
        fields = self.to_repr_fields(include_sensitive=include_sensitive)
        array_repr: List[str] = []
        for field in ['owner', 'paths', 'local-path', 'backends', 'title', 'categories', 'access']:
            if fields.get(field, None):
                if field == 'paths':
                    array_repr += [f"paths={[str(p) for p in fields['paths']]}"]
                elif field == 'backends' and fields['backends'].get('storage', None):
                    array_repr += [
                        f"backends={fields['backends']['storage']}"
                    ]
                else:
                    array_repr += [f"{field}={fields[field]!r}"]
        str_repr = "container(" + ", ".join(array_repr) + ")"
        return str_repr

    @classmethod
    def parse_fields(cls, fields: dict, client, manifest: Optional[Manifest] = None, **kwargs):
        return cls(
            owner=fields['owner'],
            paths=[PurePosixPath(p) for p in fields['paths']],
            backends=fields['backends']['storage'],
            client=client,
            title=fields.get('title'),
            categories=[PurePosixPath(p) for p in fields.get('categories', [])],
            manifest=manifest,
            access=fields.get('access')
        )

    def to_manifest_fields(self, inline: bool) -> dict:
        cleaned_backends: List[Union[dict, str]] = []

        for cache in self._storage_cache:
            if isinstance(cache.storage, str):
                cleaned_backends.append(cache.storage)
                continue
            if isinstance(cache.storage, dict) and cache.storage.get('object') == \
                    WildlandObject.Type.LINK.value:
                cleaned_backends.append(deepcopy(cache.storage))
                continue
            try:
                backend_object = cache.get(self.client, self.owner)
                cleaned_backends.append(backend_object.to_manifest_fields(inline=True))
            except (ManifestError, WildlandError, AttributeError):
                # errors can occur due to impossible-to-decrypt backend or other failures, like
                # inaccessible backend
                cleaned_backends.append(deepcopy(cache.storage))

        fields: Dict[str, Any] = {
            "version": Manifest.CURRENT_VERSION,
            "object": WildlandObject.Type.CONTAINER.value,
            "owner": self.owner,
            "paths": [str(p) for p in self.paths],
            "title": self.title,
            "categories": [str(cat) for cat in self.categories],
            "access": self.access,
            "backends": {'storage': cleaned_backends},
        }
        if not self.access:
            del fields['access']
        else:
            fields["access"] = self.client.load_pubkeys_from_field(self.access, self.owner)
        self.SCHEMA.validate(fields)
        if inline:
            del fields['owner']
            del fields['version']
        return fields

    def to_repr_fields(self, include_sensitive: bool = False) -> dict:
        """
        This function provides filtered sensitive and unneeded fields for representation
        """
        fields = self.to_manifest_fields(inline=False)
        if self.local_path:
            fields.update({"local-path": str(self.local_path)})

        if not include_sensitive:
            # Remove sensitive fields
            # for backends, we only keep some useful info
            filtered_storages = []
            for storage in fields["backends"]["storage"]:
                if isinstance(storage, str):
                    filtered_storages.append(storage)
                else:
                    if 'encrypted' in storage:
                        filtered_storages.append('encrypted')
                        continue
                    filtered_storage_obj = None
                    try:
                        filtered_storage_obj = WildlandObject.from_fields(
                            self.fill_storage_fields(storage), self.client, container=self)
                    except WildlandError as e:
                        logger.error(str(e))
                    if filtered_storage_obj:
                        filtered_storages.append(filtered_storage_obj.to_repr_fields(
                            include_sensitive=False))

            fields["backends"]["storage"] = filtered_storages
        return fields

    @property
    def expanded_paths(self) -> List[PurePosixPath]:
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

    def fill_storage_fields(self, storage_dict):
        """
        Fill fields of a storage dict with data from this container. Returns the modified dict,
        or, if the dict was encrypted or not actually a dict, just the object received.
        """
        if not isinstance(storage_dict, dict) or 'type' not in storage_dict:
            return storage_dict
        if 'owner' not in storage_dict:
            storage_dict['owner'] = self.owner
        if 'version' not in storage_dict:
            storage_dict['version'] = Manifest.CURRENT_VERSION
        if 'object' not in storage_dict:
            storage_dict['object'] = 'storage'
        if 'container-path' not in storage_dict:
            storage_dict['container-path'] = str(self.uuid_path)
        return storage_dict

    def _backend_iterator(self, include_inline: bool = True, include_url: bool = True):
        """Iterate over backend caches, yield cache obj (not copied)"""
        for cache in self._storage_cache:
            if isinstance(cache.storage, str):
                if not include_url:
                    continue
            elif isinstance(cache.storage, dict) and \
                    cache.storage.get('object') == WildlandObject.Type.LINK:
                if not include_url:
                    continue
            elif not include_inline:
                continue
            yield cache

    def load_raw_backends(self, include_inline: bool = True, include_url: bool = True):
        """
        Load and return raw backends (copied, so that there will not be surprise side effects).
        :param include_inline: should inline storages be included?
        :param include_url: should url storages be included?
        """
        for cache in self._backend_iterator(include_inline, include_url):
            yield deepcopy(cache.storage)

    def load_storages(self, include_inline: bool = True, include_url: bool = True):
        """
        Load and return container storages. Returns Storage objects.
        :param include_inline: should inline storages be included?
        :param include_url: should url storages be included?
        """
        assert self.client
        for cache in self._backend_iterator(include_inline, include_url):
            try:
                storage = cache.get(self.client, self.owner)
                if 'reference-container' in storage.params and 'storage' not in storage.params:
                    logger.warning("Can't select reference storage: %s",
                                   storage.params['reference-container'])
                    continue
            except (ManifestError, WildlandError):
                continue
            yield storage

    def is_backend_in_use(self, path_or_id):
        """
        Check if a storage of a given id or url is used by this container.
        """
        for cache in self._storage_cache:
            if cache.storage == path_or_id:
                return True
            try:
                backend = cache.get(self.client, self.owner)
                if backend.backend_id == path_or_id:
                    return True
            except (ManifestError, WildlandError):
                continue
        return False

    def get_backends_description(self, only_inline: bool = False):
        """
        Get a readable description of own storage backends.
        """
        for cache in self._storage_cache:
            if isinstance(cache.storage, str):
                if not only_inline:
                    yield cache.storage
                continue
            if 'type' in cache.storage:
                result = f'type: {cache.storage["type"]}'
                if 'backend-id' in cache.storage:
                    result += f' backend_id: {cache.storage["backend-id"]}'
                if cache.storage['type'] in ['local', 'local-cached', 'local-dir-cached']:
                    result += f' location: {cache.storage["location"]}'
                yield result
            elif 'encrypted' in cache.storage:
                yield 'encrypted'
            elif not only_inline:
                yield 'Link object: ' + cache.storage['file']

    def del_storage(self, backend_id_or_path=None):
        """
        Remove a storage of a given backend_id or URL.
        Removes only first occurrence of a given storage.
        """
        backend_to_remove = None
        for cache in self._storage_cache:
            if cache.storage == str(backend_id_or_path):
                backend_to_remove = cache
                break
            backend = cache.get(self.client, self.owner)
            if backend.backend_id == backend_id_or_path:
                backend_to_remove = cache
                break

        if backend_to_remove:
            self._storage_cache.remove(backend_to_remove)

    def add_storage_from_obj(self, storage, inline: bool = True, storage_name: Optional[str] = None,
                             new_url: Optional[str] = None):
        """
        Add a given Storage object to own backends, replace if exists. While replacing, current
        inline state will override the inline parameter.
        :param storage: Storage object
        :param inline: should the storage be added as inline storage or standalone one
        :param storage_name: if inline=False and the storage does not already exist, this name
        will be used to save it
        :param new_url: if inline=False and the storage is already within own backends, replaces
        its url with this url.
        """
        for idx, cache in enumerate(self._storage_cache):
            try:
                current_backend = cache.get(self.client, self.owner)
            except (ManifestError, WildlandError):
                continue

            if current_backend.backend_id == storage.backend_id:
                if current_backend.params == storage.params and not new_url:
                    logger.info('No changes in storage %s found. Not saving.', storage.backend_id)
                    return

                if isinstance(cache.storage, dict):
                    if cache.storage.get('object') == 'link':
                        link = self.client.load_link_object(cache.storage, self.owner)
                        self.client.save_object(WildlandObject.Type.STORAGE, storage,
                                                Path(cache.storage['file']).relative_to('/'),
                                                link.storage_driver)
                        return
                    self._storage_cache[idx] = _StorageCache(self.fill_storage_fields(
                        storage.to_manifest_fields(inline=True)), self)
                else:
                    if new_url:
                        self._storage_cache[idx] = _StorageCache(new_url, self)
                    elif cache.storage.startswith('file://'):
                        self.client.save_object(
                            WildlandObject.Type.STORAGE, storage,
                            self.client.parse_file_url(cache.storage, self.owner))
                    else:
                        raise WildlandError(f'Cannot updated a standalone storage: {cache.storage}')
                break
        else:
            if inline:
                self._storage_cache.append(_StorageCache(
                    self.fill_storage_fields(storage.to_manifest_fields(inline=True)), self))
            else:
                if new_url:
                    new_path = new_url
                else:
                    storage_path = storage.local_path
                    if not storage_path:
                        storage_path = self.client.save_new_object(
                            WildlandObject.Type.STORAGE, storage, storage_name)
                    new_path = self.client.local_url(storage_path)
                self._storage_cache.append(_StorageCache(new_path, self))

    def clear_storages(self):
        """Remove all storages"""
        self._storage_cache = []

    def copy(self, new_name) -> 'Container':
        """Copy this container to a new object with a new UUID and appropriately edited storages."""
        new_container = Container(
            owner=self.owner,
            paths=self.paths[1:],
            backends=[],
            client=self.client,
            title=self.title,
            categories=self.categories,
            access=deepcopy(self.access),
        )
        new_uuid = new_container.uuid

        for cache in self._storage_cache:
            old_backend = cache.get(self.client, self.owner)
            new_backend = old_backend.copy(self.uuid, new_uuid)

            new_container.add_storage_from_obj(new_backend,
                                               inline=(isinstance(cache.storage, dict)),
                                               storage_name=new_name)

        return new_container

    def validate(self):
        """
        Validate container. This is not done automatically because we might want to load a
        container having wrong fields.
        """
        # calling 'get_all_storages' will raise an exception if duplicate backend-id has been
        # inserted while editing the container
        self.client.get_all_storages(self)


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

        return Container.from_fields(self.fields, parent_container.client,
                                     WildlandObject.Type.CONTAINER)
