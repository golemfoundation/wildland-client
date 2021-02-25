"""
Unit tests for a categorization proxy
"""
from pathlib import PurePosixPath

from ..storage_backends.categorization_proxy import CategorizationProxyStorageBackend as cp


def test_filename_to_prefix_postfix_category_path():
    """
    Test conversion from directory name into ``(prefix_category, postfix_category)`` where
    ``prefix_category`` and ``postfix_category`` are respectively: category parsed from part of
    directory name preceding and following ``@`` character (a.k.a. category tag). If ``@`` is not
    present in directory name, then ``postfix_category`` is empty.
    """
    dirname_to_categories_tests = {
        # Tests with no valid category tag embedded (note no '@' character in directories' names).
        'author1': ('/author1', ''),
        'aaa': ('/aaa', ''),
        'aaa_bbb_ccc': ('/aaa/bbb/ccc', ''),
        'aaa bbb ccc ddd': ('/aaa bbb ccc ddd', ''),
        'aaa bbb_ccc ddd': ('/aaa bbb/ccc ddd', ''),
        'aaa bbb_ccc ddd_': ('/aaa bbb/ccc ddd', ''),
        '_aaa bbb_ccc ddd_': ('/aaa bbb/ccc ddd', ''),
        ' ': ('/ ', ''),
        '_': ('/_', ''),
        # Tests with invalid category tag. Treated as a plain directory name.
        'aaa @': ('/aaa @', ''),
        '@': ('/@', ''),
        '_@': ('/_@', ''),
        # Tests with multiple '@' characters indicating multiple category tags. Since we don't
        # support multiple tags in a directory name, we treat it as a plain directory name.
        'aaa_@bbb @ccc': ('/aaa_@bbb @ccc', ''),
        'aaa @@ bbb': ('/aaa @@ bbb', ''),
        '@aaa_bbb_ccc@': ('/@aaa_bbb_ccc@', ''),
        '@@@@@@@@': ('/@@@@@@@@', ''),
        # Test cases with valid category name embedded.
        '@authors': ('', '/authors'),
        '@titles_title1' : ('', '/titles/title1'),
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
        prefix, postfix = cp._get_category_info(filename)
        assert prefix == expected_prefix
        assert postfix == expected_postfix


def test_filename_to_category_path_conversion():
    """
    Test conversion from category embedded in directory's name, into category path saved into
    subcontainer's manifest.
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
        category_path = cp._filename_to_category_path(filename)
        assert category_path == expected_category_path

def test_get_title_from_dir_path():
    dirname_to_subcontainer_title_tests = {
        'books_titles': 'titles',
        'actors_humans_author': 'author',
        'actors_humans__author': 'author',
        '@authors': 'authors',
        '@titles_title1': 'title1',
        'author2_@titles_title3': 'title3',
    }
    for dirname, expected_subcontainer_title in dirname_to_subcontainer_title_tests.items():
        subcontainer_title = cp._get_title_from_dir_path(PurePosixPath(dirname))
        assert subcontainer_title == expected_subcontainer_title
