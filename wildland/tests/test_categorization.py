# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
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
Unit tests for the categorization proxy
"""

import os

from .helpers import treewalk
from ..storage_backends.categorization_proxy import CategorizationProxyStorageBackend


def test_filename_to_prefix_postfix_category_path():
    """
    Test conversion from directory name into ``(prefix_category, postfix_category)`` where
    ``prefix_category`` and ``postfix_category`` are respectively: category parsed from part of
    directory name preceding and following ``@`` character (a.k.a. category tag). If ``@`` is not
    present in directory name, then ``postfix_category`` is empty. Underscores (``_``) are being
    used as a category path separator in direcory name. Slash ``/`` plays the same role in a
    subcontainer's manifest.
    """
    dirname_to_categories_tests = {
        # Names with no valid category tag embedded (note no '@' character in directories' names).
        'author1': ('/author1', ''),
        'aaa': ('/aaa', ''),
        'aaa_bbb_ccc': ('/aaa/bbb/ccc', ''),
        'aaa bbb ccc ddd': ('/aaa bbb ccc ddd', ''),
        'aaa bbb_ccc ddd': ('/aaa bbb/ccc ddd', ''),
        'aaa bbb_ccc ddd_': ('/aaa bbb/ccc ddd', ''),
        '_aaa bbb_ccc ddd_': ('/aaa bbb/ccc ddd', ''),
        ' ': ('/ ', ''),
        '_': ('/_', ''),
        # Names with invalid category tag. Treated as a plain directory name.
        'aaa @': ('/aaa @', ''),
        '@': ('/@', ''),
        '_@': ('/_@', ''),
        # Names with multiple '@' characters indicating multiple category tags. Since we don't
        # support multiple tags in a directory name, we treat it as a plain directory name.
        'aaa_@bbb @ccc': ('/aaa_@bbb @ccc', ''),
        'aaa @@ bbb': ('/aaa @@ bbb', ''),
        '@aaa_bbb_ccc@': ('/@aaa_bbb_ccc@', ''),
        '@@@@@@@@': ('/@@@@@@@@', ''),
        # Names with valid category name embedded.
        '@authors': ('', '/authors'),
        '@titles_title1': ('', '/titles/title1'),
        'author2_@titles_title3': ('/author2', '/titles/title3'),
        'aaa_bbb_ccc@ddd_eee_fff': ('/aaa/bbb/ccc', '/ddd/eee/fff'),
        'aaa_bbb @ccc_ddd': ('/aaa/bbb ', '/ccc/ddd'),
        'aaa_bbb@ccc ddd': ('/aaa/bbb', '/ccc ddd'),
        '@aaa': ('', '/aaa'),
        '@aaa_bbb_ccc_ddd_eee': ('', '/aaa/bbb/ccc/ddd/eee'),
        '@aaa_bbb_ccc_ddd__eee': ('', '/aaa/bbb/ccc/ddd/_eee'),
        '_aaa bbb_ccc @ddd_': ('/aaa bbb/ccc ', '/ddd'),
        'aaa @ bbb_ccc__ddd': ('/aaa ', '/ bbb/ccc/_ddd'),
        '@_____': ('', '/____'),
        '_@_': ('/_', '/_'),
        '__@_': ('/_', '/_'),
        '__@__': ('/_', '/_'),
        '___@___': ('/__', '/__'),
    }
    for filename, (expected_prefix, expected_postfix) in dirname_to_categories_tests.items():
        params = {
            'backend-id': 'test_id',
            'type': CategorizationProxyStorageBackend.TYPE,
            'storage': None
        }
        cp = CategorizationProxyStorageBackend(params=params)
        prefix, postfix = cp._get_category_info(filename)  # pylint: disable=protected-access
        assert prefix == expected_prefix
        assert postfix == expected_postfix


def test_filename_to_category_path_conversion():
    """
    Test conversion from category embedded in directory's name, into category path that is indented
    to be saved into subcontainer's manifest.
    """
    dirname_to_category_tests = {
        'books_titles': '/books/titles',
        'actors_humans_author': '/actors/humans/author',
        'actors_humans__author': '/actors/humans/_author',
        'actors___humans__author': '/actors/__humans/_author',
        't_1974': '/t/1974',
        't_20th_1940s_1945_born': '/t/20th/1940s/1945/born',
        'aaa': '/aaa',
        'aaa_bbb_ccc': '/aaa/bbb/ccc',
        'aaa bbb ccc ddd': '/aaa bbb ccc ddd',
        'aaa bbb_ccc ddd': '/aaa bbb/ccc ddd',
        'aaa bbb_ccc ddd_': '/aaa bbb/ccc ddd',
        '_aaa bbb_ccc ddd_': '/aaa bbb/ccc ddd',
        'aaa ': '/aaa ',
        ' ': '/ ',
        'aaa_': '/aaa',
        'aaa_bbb ': '/aaa/bbb ',
        'aaa_bbb': '/aaa/bbb',
        'aaa_bbb_ccc_ddd_eee': '/aaa/bbb/ccc/ddd/eee',
        'aaa_bbb_ccc_ddd__eee': '/aaa/bbb/ccc/ddd/_eee',
        '_____': '/____',
        '_': '/_',
        '__ ~` weird !@ test #$%^&__*()_+-=___': '/_ ~` weird !@ test #$%^&/_*()/+-=/__',
        'To be, or not to be, that is the question': '/To be, or not to be, that is the question',
        '': '',
        'aaa_@bbb @ccc': '/aaa/@bbb @ccc',
        'aaa @@ bbb': '/aaa @@ bbb',
    }
    for filename, expected_category_path in dirname_to_category_tests.items():
        # pylint: disable=protected-access
        category_path = CategorizationProxyStorageBackend._filename_to_category_path(filename)
        assert category_path == expected_category_path


def test_books_titles_dir_tree(cli, base_dir):
    """
    Tested directory tree::

        ./books
        └── @authors
            ├── author1
            │   ├── @titles_title1
            │   │   ├── book.epub
            │   │   └── book.pdf
            │   └── @titles_title2
            │       └── skan.pdf
            ├── author2_@titles_title3
            │   └── ocr.epub
            ├── author3_@titles_title4
            │   └── title.epub
            └── author4_title5
                └── unclassified.txt
    """
    local_storage_path = base_dir / 'books'
    local_storage_path.mkdir()

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', local_storage_path,
        '--container', 'referenceContainer', '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    reference_url = f'file://{reference_path}'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'categorization', 'CategorizationStorage',
        '--container', 'Container', '--no-inline',
        '--reference-container-url', reference_url,
        '--with-unclassified-category')

    given_dirtree = {
        '@authors/author1/@titles_title1': None,
        '@authors/author1/@titles_title1/book.epub': 'one',
        '@authors/author1/@titles_title1/book.pdf': 'two',
        '@authors/author1/@titles_title2': None,
        '@authors/author1/@titles_title2/skan.pdf': 'three',
        '@authors/author2_@titles_title3': None,
        '@authors/author2_@titles_title3/ocr.epub': 'four',
        '@authors/author3_@titles_title4': None,
        '@authors/author3_@titles_title4/title.epub': 'five',
        'author4_title5': None,
        'author4_title5/unclassified.txt': 'six'
    }

    for path, file_content in given_dirtree.items():
        full_path = local_storage_path / path

        if file_content:
            full_path.write_text(file_content)
        else:
            full_path.mkdir(parents=True)

    cli('start', '--default-user', 'User', '--skip-forest-mount')
    cli('container', 'mount', 'Container')

    mnt_dir = base_dir / 'wildland'

    assert sorted(os.listdir(mnt_dir)) == [
        '.backends',
        '.users',
        '.uuid',
        'PATH',
        'authors',
        'titles',
        'unclassified'
    ]

    assert treewalk.walk_all(mnt_dir / 'authors') == [
        'author1/',
        'author1/@titles/',
        'author1/@titles/title1/',
        'author1/@titles/title1/.manifest.wildland.yaml',
        'author1/@titles/title1/book.epub',
        'author1/@titles/title1/book.pdf',
        'author1/@titles/title2/',
        'author1/@titles/title2/.manifest.wildland.yaml',
        'author1/@titles/title2/skan.pdf',
        'author1/title1/',
        'author1/title1/.manifest.wildland.yaml',
        'author1/title1/book.epub',
        'author1/title1/book.pdf',
        'author1/title2/',
        'author1/title2/.manifest.wildland.yaml',
        'author1/title2/skan.pdf',
        'author2/',
        'author2/@titles/',
        'author2/@titles/title3/',
        'author2/@titles/title3/.manifest.wildland.yaml',
        'author2/@titles/title3/ocr.epub',
        'author2/title3/',
        'author2/title3/.manifest.wildland.yaml',
        'author2/title3/ocr.epub',
        'author3/',
        'author3/@titles/',
        'author3/@titles/title4/',
        'author3/@titles/title4/.manifest.wildland.yaml',
        'author3/@titles/title4/title.epub',
        'author3/title4/',
        'author3/title4/.manifest.wildland.yaml',
        'author3/title4/title.epub'
    ]

    assert treewalk.walk_all(mnt_dir / 'titles') == [
        '@authors/',
        '@authors/author1/',
        '@authors/author1/title1/',
        '@authors/author1/title1/.manifest.wildland.yaml',
        '@authors/author1/title1/book.epub',
        '@authors/author1/title1/book.pdf',
        '@authors/author1/title2/',
        '@authors/author1/title2/.manifest.wildland.yaml',
        '@authors/author1/title2/skan.pdf',
        '@authors/author2/',
        '@authors/author2/title3/',
        '@authors/author2/title3/.manifest.wildland.yaml',
        '@authors/author2/title3/ocr.epub',
        '@authors/author3/',
        '@authors/author3/title4/',
        '@authors/author3/title4/.manifest.wildland.yaml',
        '@authors/author3/title4/title.epub',
        'title1/',
        'title1/.manifest.wildland.yaml',
        'title1/book.epub',
        'title1/book.pdf',
        'title2/',
        'title2/.manifest.wildland.yaml',
        'title2/skan.pdf',
        'title3/',
        'title3/.manifest.wildland.yaml',
        'title3/ocr.epub',
        'title4/',
        'title4/.manifest.wildland.yaml',
        'title4/title.epub'
    ]

    assert treewalk.walk_all(mnt_dir / 'unclassified') == [
        'title5/',
        'title5/.manifest.wildland.yaml',
        'title5/unclassified.txt'
    ]
