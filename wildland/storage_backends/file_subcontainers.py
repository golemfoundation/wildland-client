# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
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
StorageBackend mixin providing support for file-based subcontainers (both via glob patterns
and a file list.
"""

import re
from pathlib import PurePosixPath
from typing import List, Dict, Any, Iterable, Tuple

import click

from wildland.link import Link
from wildland.storage_backends.base import StorageBackend
from wildland.exc import WildlandError


class FileSubcontainersMixin(StorageBackend):
    """
    A backend storage mixin providing support for pattern-manifest types of glob and list.

    glob type is a UNIX-style expression for listing all manifest files that fit a given pattern.
    list type is an array that holds a list of relative paths to the subcontainers
    manifests within the storage itself. The paths are relative to the storage's root (i.e. ``path``
    for Local storage backend).

    When adding this mixin, you should append the following snippet to the backend's ``SCHEMA``::
    "manifest-pattern": {
    "oneOf": [ {"$ref": "/schemas/types.json#pattern-glob"},
    {"$ref": "/schemas/types.json#pattern-list"} ], }

    Furthermore, classes using this mixin should remember to use super() call in cli_options
    and cli_create (see LocalStorageBackend as an example).
    """
    # pylint: disable=abstract-method

    DEFAULT_MANIFEST_PATTERN = {'type': 'glob', 'path': '/*.yaml'}

    @classmethod
    def cli_options(cls) -> List[click.Option]:
        result = super(FileSubcontainersMixin, cls).cli_options()
        result.append(
            click.Option(['--subcontainer-manifest'], metavar='PATH', multiple=True,
                         help='Relative path to a subcontainer manifest (can be repeated), '
                              'cannot be used together with manifest-pattern'))
        result.append(
            click.Option(['--manifest-pattern'], metavar='GLOB',
                         help='Set the manifest pattern for storage, cannot be user '
                              'together with --subcontainer-manifest'))
        return result

    @classmethod
    def cli_create(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        result = super(FileSubcontainersMixin, cls).cli_create(data)
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

    def get_children(self, query_path: PurePosixPath = PurePosixPath('*')) -> \
            Iterable[Tuple[PurePosixPath, Link]]:
        """
        List all subcontainers provided by this storage.
        """
        manifest_pattern = self.params.get('manifest-pattern', self.DEFAULT_MANIFEST_PATTERN)

        if manifest_pattern['type'] == 'list':
            for subcontainer_path in manifest_pattern['paths']:
                try:
                    attr = self.getattr(PurePosixPath(subcontainer_path).relative_to('/'))
                except FileNotFoundError:
                    continue
                if not attr.is_dir():
                    subcontainer_link = Link(file_path=subcontainer_path, storage_backend=self)
                    yield PurePosixPath(subcontainer_path), subcontainer_link
        elif manifest_pattern['type'] == 'glob':
            path = self._parse_glob_pattern(query_path)

            for file_path in self._find_manifest_files(PurePosixPath('.'),
                                                       path.relative_to(PurePosixPath('/'))):
                subcontainer_link = Link(file_path=PurePosixPath('/') / file_path,
                                         storage_backend=self)
                yield file_path, subcontainer_link

    def _find_manifest_files(self, prefix: PurePosixPath, path: PurePosixPath)\
            -> Iterable[PurePosixPath]:
        assert len(path.parts) > 0, 'empty path'

        part = path.parts[0]
        sub_path = path.relative_to(part)
        if '*' in part:
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
