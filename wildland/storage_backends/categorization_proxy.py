# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
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

"""
Categorization proxy backend
"""

import logging
import uuid
from typing import Tuple, Optional, Iterable, List, Dict, Set
from pathlib import PurePosixPath
from dataclasses import dataclass

import click

from .base import StorageBackend, File, Attr
from .cached import CachedStorageMixin
from ..manifest.schema import Schema
from ..manifest.sig import SigContext

logger = logging.getLogger('categorization-proxy')


@dataclass
class CategorizationSubcontainerMetaInfo:
    """
    Categorization subcontainer metainformation
    """
    dir_path: PurePosixPath
    title: str
    categories: List[str]


class CategorizationProxyStorageBackend(CachedStorageMixin, StorageBackend):
    """
    Storage backend exposing subcontainers based on category tags embedded in directories' names.
    For full description of the logic behind multicategorization tags, refer documentation.
    """

    SCHEMA = Schema({
        "type": "object",
        "required": ["reference-container"],
        "properties": {
            "reference-container": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#url"},
                    {"$ref": "/schemas/container.schema.json"}
                ],
                "description": ("Container to be used, either as URL or as an inlined manifest"),
            },
        }
    })
    TYPE = 'categorization'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.inner = self.params['storage']
        self.read_only = True

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'],
                         metavar='URL',
                         help='URL for inner container manifest',
                         required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {'reference-container': data['reference_container_url']}

    def mount(self) -> None:
        self.inner.request_mount()

    def unmount(self) -> None:
        self.inner.request_unmount()

    def clear_cache(self) -> None:
        self.inner.clear_cache()

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        yield from self._info_all_walk(PurePosixPath('.'))

    def _info_all_walk(self, dir_path: PurePosixPath) -> Iterable[Tuple[PurePosixPath, Attr]]:
        for name in self.inner.readdir(dir_path):
            path = dir_path / name
            attr = self.inner.getattr(path)
            if attr.is_dir():
                yield from self._info_all_walk(path)
            else:
                yield path, attr

    def open(self, path: PurePosixPath, flags: int) -> File:
        return self.inner.open(path, flags)

    def list_subcontainers(self, sig_context: Optional[SigContext] = None) -> Iterable[dict]:
        ns = uuid.UUID(self.backend_id)
        dir_path = PurePosixPath('')
        categories_to_container_map = self._get_categories_to_subcontainer_map(dir_path)

        # TODO DEBUG
        logger.warning('DUPAA1')
        logger.warning(repr(categories_to_container_map))
        logger.warning('DUPAA2')
        for (categories, title), subcontainer_metainfo in categories_to_container_map.items():
            logger.warning('categories: %s vs %s', repr(categories), repr(subcontainer_metainfo.categories))
            assert list(categories) == subcontainer_metainfo.categories
            assert title == subcontainer_metainfo.title
            subcontainer_path = str(subcontainer_metainfo.dir_path)
            ident = str(uuid.uuid3(ns, subcontainer_path))
            yield {
                'paths': [f'/.uuid/{ident}'],
                'title': subcontainer_metainfo.title,
                'categories': list(categories),
                'backends': {'storage': [{
                    'type': 'delegate',
                    'reference-container': 'wildland:@default:@parent-container:',
                    'subdirectory': '/' + subcontainer_path,
                    'backend-id': str(uuid.uuid3(ns, subcontainer_path))
                }]}
            }

    def _get_categories_to_subcontainer_map(self, dir_path: PurePosixPath) -> \
            Dict[Tuple[frozenset, str], CategorizationSubcontainerMetaInfo]:
        """
        Recursively traverse directory tree and build categories to directory paths mapping.
        """
        return self._get_categories_to_subcontainer_map_recursive(dir_path, '', set(), dict())

    def _get_categories_to_subcontainer_map_recursive(
        self,
        dir_path: PurePosixPath,
        open_category: str,
        closed_categories: Set[str],
        results: Dict[Tuple[frozenset, str], CategorizationSubcontainerMetaInfo]) -> \
            Dict[Tuple[frozenset, str], CategorizationSubcontainerMetaInfo]:

        for name in self.inner.readdir(dir_path):
            # TODO DEBUG
            logger.warning('DUPA > dir=%s, name=%s', str(dir_path), name)
            path = dir_path / name
            attr = self.inner.getattr(path)
            if attr.is_dir():
                prefix_category, postfix_category = self._get_category_info(name)
                if postfix_category:
                    concatenated = open_category + prefix_category
                    concatenated_set = {concatenated} if concatenated else set()
                    new_closed_categories = closed_categories | concatenated_set
                    new_open_category = postfix_category
                else:
                    new_closed_categories = closed_categories
                    new_open_category = open_category + prefix_category
                self._get_categories_to_subcontainer_map_recursive(
                    path,
                    new_open_category,
                    new_closed_categories,
                    results)
            else:
                tmp_open_category, _, subcontainer_title = open_category.rpartition('/')
                if tmp_open_category:
                    closed_categories.add(tmp_open_category)
                all_categories = frozenset(closed_categories) or frozenset('/unclassified')
                # TODO DEBUG
                logger.warning('DUPAA > [%s] -> (%s, title=%s), open_category=%s, tmp_open_category=%s', path, repr(all_categories), subcontainer_title, open_category, tmp_open_category)
                key = (all_categories, subcontainer_title)
                if key in results:
                    logger.warning('Asserting [%s] == [%s]', dir_path, results[key].dir_path)
                    assert dir_path == results[key].dir_path
                    continue
                results[key] = CategorizationSubcontainerMetaInfo(
                    dir_path=dir_path,
                    title=subcontainer_title,
                    categories=list(all_categories))

        return results

    @staticmethod
    def _get_category_info(dir_name: str) -> Tuple[str, str]:
        """
        Extract category tag from directory name together with text preceding it (prefix) and text
        following it (postfix). Both prefix and postfix are treated as category paths joined with an
        underscore that is replaced with a slash. At most one category tag is allowed in a directory
        name. If a directory name does not have any tags, then ``(dir_name, '', '')`` is returned.

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
        cp = CategorizationProxyStorageBackend

        if dir_name.endswith('@') or postfix.find('@') != -1:
            logger.debug('Directory [%s] seems to either have multiple category tags or empty '
                         'category tag - treating it as a regular directory without any category '
                         'tag', dir_name)
            return '/' + dir_name, ''

        return cp._filename_to_category_path(prefix), \
               cp._filename_to_category_path(postfix)

    @staticmethod
    def _filename_to_category_path(category_path: str) -> str:
        """
        Convert category path, joined by underscores, to a category path joined with slashes. The
        result will be assigned to ``path`` in subcontainer's manifest. In case of series of
        adjacent underscores, only the first underscore is replaced with a slash, treating rest of
        them as a part of category name. ``category_path`` is assumed to not have slash characters
        ('/') since it is part of a file name.
        """
        if category_path == '_':
            return '/_'

        converted_path = '' if category_path.startswith('_') else '/'
        idx = 0
        n = len(category_path)

        while idx < n:
            separator_idx = category_path.find('_', idx)
            if separator_idx == -1:
                converted_path += category_path[idx:]
                break
            converted_path += category_path[idx:separator_idx] + '/'
            idx = separator_idx + 1
            while idx < n and category_path[idx] == '_':
                converted_path += '_'
                idx += 1
        # Result ends with '/' iff category_path ends with a single '_'
        return converted_path[:-1] if converted_path.endswith('/') else converted_path
