# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>
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
StorageBackend mixin providing support for file-based Publishable Wildland Objects (both via
glob patterns and a file list).
"""

import re
from pathlib import PurePosixPath
from typing import List, Dict, Any, Iterable, Tuple, Optional, Iterator, Set

import click

from wildland.client import Client
from wildland.container import Container
from wildland.link import Link
from wildland.storage import Storage
from wildland.storage_backends.base import StorageBackend
from wildland.exc import WildlandError
from wildland.storage_driver import StorageDriver
from wildland.wildland_object.wildland_object import WildlandObject, PublishableWildlandObject


class FileChildrenMixin(StorageBackend):
    """
    A backend storage mixin providing support for pattern-manifest types of glob and list.

    glob type is a UNIX-style expression for listing all manifest files that fit a given pattern.
    list type is an array that holds a list of relative paths to child objects manifests within
    the storage itself. The paths are relative to the storage's root (i.e. ``path`` for Local
    storage backend).

    When adding this mixin, you should append the following snippet to the backend's ``SCHEMA``::
    "manifest-pattern": {
    "oneOf": [ {"$ref": "/schemas/types.json#pattern-glob"},
    {"$ref": "/schemas/types.json#pattern-list"} ], }

    Furthermore, classes using this mixin should remember to use super() call in cli_options
    and cli_create (see LocalStorageBackend as an example).
    """
    # pylint: disable=abstract-method

    DEFAULT_MANIFEST_PATTERN = {'type': 'glob', 'path': '/*.{object-type}.yaml'}

    @classmethod
    def cli_options(cls) -> List[click.Option]:
        result = super(FileChildrenMixin, cls).cli_options()
        result.append(
            click.Option(['--subcontainer-manifest'], metavar='PATH', multiple=True,
                         help='Relative path to a child manifest (can be repeated), '
                              'cannot be used together with manifest-pattern'))
        result.append(
            click.Option(['--manifest-pattern'], metavar='GLOB',
                         help='Set the manifest pattern for storage, cannot be used '
                              'together with --subcontainer-manifest'))
        return result

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        result = super(FileChildrenMixin, cls).cli_create(data)
        if data.get('subcontainer_manifest'):
            if data.get('manifest_pattern'):
                raise WildlandError('--subcontainer-manifest and --manifest-pattern '
                                    'are mutually exclusive.')
            result['manifest-pattern'] = {
                    'type': 'list',
                    'paths': list(data['subcontainer_manifest'])
                }
        elif data.get('manifest_pattern'):
            result['manifest-pattern'] = {
                    'type': 'glob',
                    'path': data['manifest_pattern']
                }
        return result

    @property
    def supports_publish(self) -> bool:
        """
        Check if storage handles child manifests.

        At the moment only simple file-based backends with manifest-pattern: glob are supported.
        """
        return 'manifest-pattern' in self.params \
               and self.params['manifest-pattern']['type'] == 'glob'

    @property
    def can_have_children(self) -> bool:
        """
        Check if storage can have subcontainers.

        If False `get_children` have to return empty collection or raise error.
        If True `get_children` can return an empty or non-empty collection.
        """
        return 'manifest-pattern' in self.params

    def has_child(self, wl_object_uuid_path: PurePosixPath) -> bool:
        """
        Check if the given container is child of this storage.
        """
        wl_object_manifest = next(self._get_relpaths(wl_object_uuid_path))

        with StorageDriver(self) as driver:
            return driver.file_exists(wl_object_manifest)

    def _get_relpaths(self, wl_object_uuid_path: PurePosixPath,
                      wl_object_expanded_paths: Optional[Iterable[PurePosixPath]] = None) -> \
            Iterator[PurePosixPath]:
        pattern = self.params['manifest-pattern']['path']

        path_pattern = pattern.replace('*', wl_object_uuid_path.name)\
            .replace('{object-type}', 'container')

        paths = wl_object_expanded_paths or (wl_object_uuid_path,)
        for path in paths:
            yield PurePosixPath(path_pattern.replace(
                '{path}', str(path.relative_to('/')))).relative_to('/')

    def add_child(self, client: Client, wl_object: PublishableWildlandObject):
        """
        Add Wildland object manifest to this storage.

        If the given object is already a child of this storage, update it.
        """
        self._update_child(client, wl_object, just_remove=False)

    def remove_child(self, client: Client, wl_object: PublishableWildlandObject):
        """
        Remove Wildland object manifest from this storage.

        If the given object is already a child of this storage, nothing happens.
        """
        self._update_child(client, wl_object, just_remove=True)

    def _update_child(self, client: Client, wl_object: PublishableWildlandObject,
                      just_remove: bool):
        # Marczykowski-Górecki's Algorithm:
        # 1) choose manifests catalog entry from object's owner
        #    - if the wildland object was published earlier, the same entry
        #      should be chosen; this will make sense when user is be able to
        #      choose to which catalog entry the wl object should be published
        # 2) generate all new relpaths for the wl object (and potentially
        #    container storages)
        # 3) try to fetch previous wl object from new relpaths and check if the file
        #    contains the same wl object; if yes, generate relpaths for old
        #    paths
        # 4) remove old copies of manifest for wl object (and storages if the
        #    object is a container) but only those that won't be overwritten later
        # 5) post new storage manifests (if wl object is a container)
        # 6) post new wl object manifests, starting with the /.uuid/ one
        #
        # For unpublishing, instead of 4), 5) and 6), all manifests are removed
        # from relpaths and no new manifests are published.

        if just_remove:
            update = set.update
        else:
            update = set.difference_update

        manifest_relpaths = list(
            self._get_relpaths(
                wl_object.get_primary_publish_path(),
                wl_object.get_publish_paths()
            )
        )

        with StorageDriver(self, bulk_writing=True) as driver:
            storage_relpaths = {}
            old_relpaths_to_remove = self._fetch_from_uuid_path(
                client, driver, manifest_relpaths[0], wl_object.get_unique_publish_id())

            update(old_relpaths_to_remove, manifest_relpaths)

            if wl_object.type == WildlandObject.Type.CONTAINER:
                # Container is an exception as it directly relates to publishable Storage
                # objects. (assert below is for mypy's sake)
                assert isinstance(wl_object, Container)
                storage_relpaths = self._replace_containers_old_relative_urls(wl_object)
                update(old_relpaths_to_remove, storage_relpaths)

            self._remove_old_paths(driver, old_relpaths_to_remove)
            if not just_remove:
                self._create_new_paths(
                    client, driver, storage_relpaths, manifest_relpaths, wl_object)

    def _replace_containers_old_relative_urls(self, container: Container) -> \
            Dict[PurePosixPath, Storage]:
        storage_relpaths = {}
        for backend in container.load_storages(include_inline=False):
            # we publish only a single manifest for a storage, under `/.uuid/` path
            container_manifest = next(self._get_relpaths(container.uuid_path))

            name = container_manifest.name

            if container_manifest.name.endswith('.container.yaml'):
                name = name.removesuffix('.container.yaml')\
                       + f'.{backend.backend_id}.container.yaml'
            else:
                name = name.removesuffix('.yaml')\
                       + f'.{backend.backend_id}.yaml'

            relpath = container_manifest.with_name(name)
            assert relpath not in storage_relpaths
            storage_relpaths[relpath] = backend
            container.add_storage_from_obj(
                backend, inline=False, new_url=None)
        return storage_relpaths

    def _fetch_from_uuid_path(self,
                              client: Client,
                              driver: StorageDriver,
                              primary_publish_path: PurePosixPath,
                              unique_publish_id: str) -> \
            Set[PurePosixPath]:
        old_relpaths_to_remove = set()
        try:
            old_object_manifest_data = driver.read_file(primary_publish_path)
        except FileNotFoundError:
            pass
        else:
            old_object = client.load_object_from_bytes(None, old_object_manifest_data)

            if not old_object.get_unique_publish_id() == unique_publish_id:
                # we just downloaded this file from manifest's primary uuid path, so
                # things are very wrong here
                raise WildlandError(
                    f'old version of object manifest at storage '
                    f'{driver.storage.params["backend-id"]} has serious '
                    f'problems; please remove it manually')

            old_relpaths_to_remove.update(set(
                self._get_relpaths(
                    old_object.get_primary_publish_path(),
                    old_object.get_publish_paths()
                )
            ))

        return old_relpaths_to_remove

    @staticmethod
    def _remove_old_paths(driver: StorageDriver, old_relpaths_to_remove: Set[PurePosixPath]):
        # remove /.uuid path last, if present (bool sorts False < True)
        for relpath in sorted(old_relpaths_to_remove,
                              key=(lambda path: path.parts[:2] == ('/', '.uuid'))):
            try:
                driver.remove_file(relpath)
            except FileNotFoundError:
                pass
            try:
                for parent in relpath.parents:
                    if not driver.remove_empty_dir(parent):
                        break
            except FileNotFoundError:
                pass

    @staticmethod
    def _create_new_paths(client: Client,
                          driver: StorageDriver,
                          storage_relpaths: Dict[PurePosixPath, Storage],
                          wl_object_relpaths: List[PurePosixPath],
                          wl_object: PublishableWildlandObject):
        for relpath, storage in storage_relpaths.items():
            driver.makedirs(relpath.parent)
            driver.write_file(relpath, client.session.dump_object(storage))

        for relpath in wl_object_relpaths:
            driver.makedirs(relpath.parent)
            driver.write_file(relpath, client.session.dump_object(wl_object))

    def get_children(
            self,
            client=None,
            query_path: PurePosixPath = PurePosixPath('*'),
            paths_only: bool = False
    ) -> Iterable[Tuple[PurePosixPath, Optional[Link]]]:
        """
        List all child objects provided by this storage.
        """
        manifest_pattern = self.params.get('manifest-pattern', self.DEFAULT_MANIFEST_PATTERN)

        if manifest_pattern['type'] == 'list':
            for child_path in manifest_pattern['paths']:
                if not paths_only:
                    try:
                        attr = self.getattr(PurePosixPath(child_path).relative_to('/'))
                    except FileNotFoundError:
                        continue
                    if not attr.is_dir():
                        child_object_link = Link(
                            file_path=child_path, storage_backend=self, client=client)
                        yield PurePosixPath(child_path), child_object_link
                    else:
                        yield PurePosixPath(child_path), None
        elif manifest_pattern['type'] == 'glob':
            path = self._parse_glob_pattern(query_path)

            for file_path in self._find_manifest_files(PurePosixPath('.'),
                                                       path.relative_to(PurePosixPath('/'))):
                if not paths_only:
                    child_object_link = Link(file_path=PurePosixPath('/') / file_path,
                                             storage_backend=self, client=client)
                    yield file_path, child_object_link
                else:
                    yield file_path, None

    def _find_manifest_files(self, prefix: PurePosixPath, path: PurePosixPath)\
            -> Iterable[PurePosixPath]:
        assert len(path.parts) > 0, 'empty path'

        part = path.parts[0]
        sub_path = path.relative_to(part)
        if '{object-type}' in part:
            for object_type in WildlandObject.Type:
                full_file_name = part.replace('{object-type}', object_type.value) / sub_path
                yield from self._find_manifest_files(prefix, PurePosixPath(full_file_name))
        elif '*' in part:
            # This is a glob part, use readdir()
            try:
                names = list(self.readdir(prefix))
            except IOError:
                return
            regex = re.compile('^' + part.replace('.', r'\.').replace('*', '.*') + '$')
            for name in names:
                if regex.match(name):
                    sub_prefix = prefix / name
                    if sub_path.parts:
                        yield from self._find_manifest_files(sub_prefix, sub_path)
                    else:
                        yield sub_prefix
        elif sub_path.parts:
            # This is a normal part, recurse deeper
            sub_prefix = prefix / part
            yield from self._find_manifest_files(sub_prefix, sub_path)
        else:
            # End of a normal path, check using getattr()
            full_path = prefix / part
            try:
                self.getattr(full_path)
            except IOError:
                return
            yield full_path

    def _parse_glob_pattern(self, query_path: PurePosixPath) -> PurePosixPath:
        manifest_pattern = self.params.get('manifest-pattern', self.DEFAULT_MANIFEST_PATTERN)
        if manifest_pattern['type'] == 'list':
            return query_path
        glob_pattern = manifest_pattern['path']
        if str(query_path) == '*':
            # iterate over manifests saved under /.uuid/ path, to try to avoid loading the
            # same manifests multiple times
            glob_path = glob_pattern.replace('{path}', '.uuid/*')
        else:
            glob_path = glob_pattern.replace('{path}', str(query_path.relative_to('/')))
        return PurePosixPath(glob_path)

    def get_subcontainer_watch_pattern(self, query_path: PurePosixPath) -> PurePosixPath:
        manifest_pattern = self.params.get('manifest-pattern', self.DEFAULT_MANIFEST_PATTERN)
        if manifest_pattern['type'] == 'glob':
            return self._parse_glob_pattern(query_path)
        return query_path
