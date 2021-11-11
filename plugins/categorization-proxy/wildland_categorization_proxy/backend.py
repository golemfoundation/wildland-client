# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Patryk Bęza <patryk@wildland.io>
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
Categorization proxy backend
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable, Iterator, List, Set, Tuple, FrozenSet

import click

from wildland.storage_backends.base import StorageBackend, File, Attr
from wildland.manifest.schema import Schema
from wildland.container import ContainerStub
from wildland.log import get_logger

logger = get_logger('categorization-proxy')


@dataclass(eq=True, frozen=True)
class CategorizationSubcontainerMetaInfo:
    """
    Categorization subcontainer metadata. Every unique instance of this class corresponds to a
    single subcontainer's manifest.
    """
    dir_path: PurePosixPath
    title: str
    categories: FrozenSet[str]


class CategorizationProxyStorageBackend(StorageBackend):
    """
    Storage backend exposing subcontainers based on category tags embedded in directory names. For
    full description of the logic behind multicategorization tags, refer documentation.
    """

    SCHEMA = Schema({
        "title": "Categorization proxy manifest",
        "type": "object",
        "required": [
            "reference-container",
            "with-unclassified-category",
            "unclassified-category-path",
        ],
        "properties": {
            "reference-container": {
                "$ref": "/schemas/types.json#reference-container",
                "description": "Container to be used, either as URL or as an inlined manifest",
            },
            "with-unclassified-category": {
                "type": "boolean",
                "description": "Create unclassified directory holding all of the untagged "
                               "directories (default: False).",
            },
            "unclassified-category-path": {
                "$ref": "/schemas/types.json#abs-path",
                "description": "Path to directory where unclassified directories are mounted "
                               "(`/unclassified` by default). This option is ignored unless "
                               "`with-unclassified-category` is set.",
            },
        }
    })
    TYPE = 'categorization'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.inner = self.params['storage']
        self.with_unclassified_category = self.params.get('with-unclassified-category', False)
        self.unclassified_category_path = self.params.get('unclassified-category-path',
                                                          '/unclassified')
        self.read_only = True

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'],
                         metavar='URL',
                         help='URL for inner container manifest.',
                         required=True),
            click.Option(['--with-unclassified-category'],
                         is_flag=True,
                         default=False,
                         required=False,
                         help='Create unclassified directory holding all of the untagged '
                              'directories.'),
            click.Option(['--unclassified-category-path'],
                         metavar='PATH',
                         default='/unclassified',
                         required=False,
                         help='Path to directory where unclassified directories are mounted '
                              '(`/unclassified` by default). This option is ignored unless '
                              '`--with-unclassified-category` is set.'),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'reference-container': data['reference_container_url'],
            'with-unclassified-category': data['with_unclassified_category'],
            'unclassified-category-path': data['unclassified_category_path'],
        }

    def mount(self) -> None:
        self.inner.request_mount()

    def unmount(self) -> None:
        self.inner.request_unmount()

    def getattr(self, path: PurePosixPath) -> Attr:
        return self.inner.getattr(path)

    def readdir(self, path: PurePosixPath) -> List[str]:
        return self.inner.readdir(path)

    def open(self, path: PurePosixPath, flags: int) -> File:
        return self.inner.open(path, flags)

    @property
    def can_have_children(self) -> bool:
        return True

    def get_children(self, client=None, query_path: PurePosixPath = PurePosixPath('*')) -> \
            Iterable[Tuple[PurePosixPath, ContainerStub]]:
        ns = uuid.UUID(self.backend_id)
        dir_path = PurePosixPath('')
        subcontainer_metainfo_set = self._get_categories_to_subcontainer_map(dir_path)

        logger.debug('Collected subcontainers: %r', subcontainer_metainfo_set)

        for subcontainer_metainfo in subcontainer_metainfo_set:
            dirpath = str(subcontainer_metainfo.dir_path)
            title = subcontainer_metainfo.title
            categories = list(subcontainer_metainfo.categories)
            ident = str(uuid.uuid3(ns, dirpath))
            subcontainer_path = '/' + dirpath
            container_stub = ContainerStub(fields={
                'paths': [f'/.uuid/{ident}'],
                'title': title,
                'categories': categories,
                'backends': {'storage': [{
                    'type': 'delegate',
                    'reference-container': 'wildland:@default:@parent-container:',
                    'subdirectory': subcontainer_path,
                    'backend-id': str(uuid.uuid3(ns, dirpath))}]}})
            yield PurePosixPath(subcontainer_path), container_stub

    def _get_categories_to_subcontainer_map(self, dir_path: PurePosixPath) -> \
            Set[CategorizationSubcontainerMetaInfo]:
        """
        Recursively traverse directory tree and generate subcontainers' metainformation based on the
        directory names: ``@`` starts new category path, ``_`` joins two categories.
        """
        return set(self._get_categories_to_subcontainer_map_recursive(dir_path, '', set(), False))

    def _get_categories_to_subcontainer_map_recursive(
            self,
            dir_path: PurePosixPath,
            open_category: str,
            closed_categories: Set[str],
            category_tag_found: bool) -> Iterator[CategorizationSubcontainerMetaInfo]:
        """
        Recursively traverse directory tree, collect and return all of the metainformation needed to
        create subcontainers based on the tags embedded in directory names.
        """
        dir_contains_files = False

        for name in self.inner.readdir(dir_path):
            path = dir_path / name
            attr = self.inner.getattr(path)
            if attr.is_dir():
                prefix_category, postfix_category = self._get_category_info(name)
                if postfix_category:
                    new_category_tag_found = True
                    closed_category = open_category + prefix_category
                    closed_category_set = {closed_category} if closed_category else set()
                    new_closed_categories = closed_categories | closed_category_set
                    new_open_category = postfix_category
                else:
                    new_category_tag_found = category_tag_found
                    new_closed_categories = closed_categories.copy()
                    new_open_category = open_category + prefix_category
                yield from self._get_categories_to_subcontainer_map_recursive(
                    path,
                    new_open_category,
                    new_closed_categories,
                    new_category_tag_found)
            else:
                dir_contains_files = True

        if dir_contains_files:
            prefix_category, _, subcontainer_title = open_category.rpartition('/')

            if not category_tag_found and self.with_unclassified_category:
                assert not closed_categories
                all_categories = frozenset({self.unclassified_category_path})
            else:
                if not prefix_category:
                    assert subcontainer_title
                    prefix_category = '/' + subcontainer_title
                    subcontainer_title = '.'
                all_categories = frozenset(closed_categories | {prefix_category})

            yield CategorizationSubcontainerMetaInfo(
                dir_path=dir_path,
                title=subcontainer_title or '.',
                categories=all_categories
            )

    def _get_category_info(self, dir_name: str) -> Tuple[str, str]:
        """
        Extract category @tag from directory name together with text preceding it (prefix) and text
        following it (postfix). Both prefix and postfix are treated as category paths joined with an
        underscore that is replaced with a slash. At most one category tag is allowed in a directory
        name. If a directory name ``XYZ`` does not have any tags, then ``('/XYZ', '')`` is returned.

        For convenience returned tuple can consits of empty string instead of ``None``

        Examples explaining the implemented logic::

            'aaa'                      ->  ('/aaa', '')
            'aaa_bbb_ccc'              ->  ('/aaa/bbb/ccc', '')
            'aaa bbb ccc ddd'          ->  ('/aaa bbb ccc ddd', '')
            'aaa bbb_ccc ddd'          ->  ('/aaa bbb/ccc ddd', '')
            'aaa bbb_ccc ddd_'         ->  ('/aaa bbb/ccc ddd', '')
            '_aaa bbb_ccc ddd_'        ->  ('/aaa bbb/ccc ddd', '')
            'aaa @'                    ->  ('/aaa @', '')
            ' '                        ->  ('/ ', '')
            'aaa_@bbb @ccc'            ->  ('/aaa_@bbb @ccc', '')
            'aaa @@ bbb'               ->  ('/aaa @@ bbb', '')
            'aaa_bbb_ccc@ddd_eee_fff'  ->  ('/aaa/bbb/ccc', '/ddd/eee/fff')
            'aaa_bbb @ccc_ddd'         ->  ('/aaa/bbb ', '/ccc/ddd')
            'aaa_bbb@ccc ddd'          ->  ('/aaa/bbb', '/ccc ddd')
            '@aaa'                     ->  ('', '/aaa')
            '@aaa_bbb_ccc_ddd_eee'     ->  ('', '/aaa/bbb/ccc/ddd/eee')
            '@aaa_bbb_ccc_ddd__eee'    ->  ('', '/aaa/bbb/ccc/ddd/_eee')
            '_aaa bbb_ccc @ddd_'       ->  ('/aaa bbb/ccc ', '/ddd')
            '@_____'                   ->  ('', '/____')
            '_'                        ->  ('/_', '')
        """
        prefix, _, postfix = dir_name.partition('@')

        if dir_name.endswith('@') or postfix.find('@') != -1:
            logger.debug('Directory [%s] seems to either have multiple category tags or empty '
                         'category tag - treating it as a regular directory without any category '
                         'tag', dir_name)
            return '/' + dir_name, ''

        return self._filename_to_category_path(prefix), \
               self._filename_to_category_path(postfix)

    @staticmethod
    def _filename_to_category_path(category_path: str) -> str:
        """
        Convert category path, joined by underscores, to a category path joined with slashes. The
        result will be assigned to ``path`` in subcontainer's manifest. In case of series of
        adjacent underscores, only the first underscore is replaced with a slash, treating rest of
        them as a part of category name. ``category_path`` is assumed to not have slash characters
        ('/') since it is part of a file name.
        """
        if category_path == '':
            return ''

        if category_path == '_':
            return '/_'

        return '/' + re.sub(r'_(_*)', r'/\1', category_path).strip('/')
