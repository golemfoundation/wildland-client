# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                 Maja Kostacinska <maja@wildland.io>
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

# pylint: disable=missing-docstring,redefined-outer-name

import pytest

from ..storage_backends.transpose import TransposeStorageBackend
from ..storage_backends.base import StorageBackend
from ..container import ContainerStub
from ..client import Client
from ..wildland_object.wildland_object import WildlandObject
from ..exc import WildlandError

def test_category_modification_first_apply():
    """
    Testing the category modification logic with the 'first-apply'
    conflict resolution scheme.
    Ensures that the initial categories have been successfully transformed
    into expected ones.
    """
    initial_categories = ['/category/one', '/category/two']

    #setup for the first dummy backend instance
    rules_exclude = [{'match-with': '/category/one', 'replace-with': '/changed'},
                     {'match-with': '/category/one', 'replace-with': '/different/changed'},
                     {'match-with': '/category/two', 'exclude': True}]
    expected_categories_exclude = ['/changed']
    params_one = {
              'reference-container': 'test_reference',
              'backend-id': 'test_id',
              'conflict': 'first-apply',
              'rules': rules_exclude,
              'type': TransposeStorageBackend.TYPE,
              'storage': None,
    }
    dummy_one = TransposeStorageBackend(params=params_one)
    changed_categories_exclude = dummy_one.modify_categories(initial_categories)
    assert changed_categories_exclude == expected_categories_exclude

    #setup for the second dummy backend instance
    rules_include = [{'match-with': '/category/one', 'include': True}]
    expected_categories_include = ['/category/one']
    params_two = {
              'reference-container': 'test_reference',
              'backend-id': 'test_id',
              'conflict': 'first-apply',
              'rules': rules_include,
              'type': TransposeStorageBackend.TYPE,
              'storage': None,
    }
    dummy_two = TransposeStorageBackend(params=params_two)
    changed_categories_include = dummy_two.modify_categories(initial_categories)
    assert changed_categories_include == expected_categories_include

def test_category_modification_last_apply():
    """
    Testing the category modification logic with the 'last-apply'
    conflict resolution scheme.
    Ensures that the initial categories have been successfully transformed
    into expected ones.
    """
    initial_categories = ['/category/one', '/category/two']

    #setup for the first dummy backend instance
    rules_exclude = [{'match-with': '/category/one', 'replace-with': '/changed'},
                     {'match-with': '/category/one', 'replace-with': '/different/changed'},
                     {'match-with': '/category/two', 'exclude': True}]
    expected_categories_exclude = ['/different/changed']
    params_one = {
              'reference-container': 'test_reference',
              'backend-id': 'test_id',
              'conflict': 'last-apply',
              'rules': rules_exclude,
              'type': TransposeStorageBackend.TYPE,
              'storage': None,
    }
    dummy_one = TransposeStorageBackend(params=params_one)
    changed_categories_exclude = dummy_one.modify_categories(initial_categories)
    assert changed_categories_exclude == expected_categories_exclude

    #setup for the second dummy backend instance
    rules_include = [{'match-with': '/category/one', 'include': True},
                     {'match-with': '/category/one', 'exclude': True},
                     {'match-with': '/category/two', 'replace-with': '/changed'}]
    expected_categories_include = ['/changed']
    params_two = {
              'reference-container': 'test_reference',
              'backend-id': 'test_id',
              'conflict': 'last-apply',
              'rules': rules_include,
              'type': TransposeStorageBackend.TYPE,
              'storage': None,
    }
    dummy_two = TransposeStorageBackend(params=params_two)
    changed_categories_include = dummy_two.modify_categories(initial_categories)
    assert changed_categories_include == expected_categories_include

def test_category_modification_all_apply():
    """
    Testing the category modification logic with the 'all-apply'
    conflict resolution scheme.
    Ensures that the initial categories have been successfully transformed
    into expected ones.
    """
    initial_categories = ['/category/one', '/category/two']

    #setup for the first dummy backend instance
    rules_exclude = [{'match-category-regex': '/(.*)', 'replace-with': r'/prefix/\1'},
                     {'match-with': '/prefix/category/one', 'replace-with': '/changed/prefix/c/1'},
                     {'match-with': '/prefix/category/two', 'exclude': True}]
    expected_categories_exclude = ['/changed/prefix/c/1']
    params_one = {
              'reference-container': 'test_reference',
              'backend-id': 'test_id',
              'conflict': 'all-apply',
              'rules': rules_exclude,
              'type': TransposeStorageBackend.TYPE,
              'storage': None,
    }
    dummy_one = TransposeStorageBackend(params=params_one)
    changed_categories_exclude = dummy_one.modify_categories(initial_categories)
    assert changed_categories_exclude == expected_categories_exclude

    #setup for the second dummy backend instance
    rules_include = [{'match-category-regex': '/category', 'replace-with': '/cat'},
                     {'match-with': '/cat/one', 'include': True}]
    expected_categories_include = ['/cat/one']
    params_two = {
              'reference-container': 'test_reference',
              'backend-id': 'test_id',
              'conflict': 'all-apply',
              'rules': rules_include,
              'type': TransposeStorageBackend.TYPE,
              'storage': None,
    }
    dummy_two = TransposeStorageBackend(params=params_two)
    changed_categories_include = dummy_two.modify_categories(initial_categories)
    assert changed_categories_include == expected_categories_include

@pytest.fixture
def setup(base_dir, cli):
    #creating the user, forest and the reference container
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location', '/tmp/location', 'mylocal')
    cli('forest', 'create', '--owner', 'User', 'mylocal')
    cli('container', 'create', 'referenceContainer', '--path', '/path',
        '--category', '/cat/one', '--category', '/cat/two')
    cli('storage', 'create', 'local', 'referenceStorage',
        '--location', base_dir / 'reference',
        '--container', 'referenceContainer', '--no-inline')

    cli('container', 'create', 'transposeCatalog', '--no-publish')
    cli('storage', 'create', 'transpose',
        '--reference-container-url', 'wildland::/.manifests:',
        '--container', 'transposeCatalog',
        '--rules', '{"match-with": "/cat/one", "replace-with": "/replaced"}',
        '--no-inline')

@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client

def test_transpose_get_children(client):
    """
    Checks whether the get_children method returns expected objects.
    """
    expected_categories = ['/replaced', '/cat/two']

    reference_container = client.load_object_from_name(WildlandObject.Type.CONTAINER,
                                                       'referenceContainer')
    transpose_container = client.load_object_from_name(WildlandObject.Type.CONTAINER,
                                                       'transposeCatalog')
    transpose_container_storage = client.select_storage(transpose_container)
    transpose_backend = StorageBackend.from_params(transpose_container_storage.params)

    transpose_children = list(transpose_backend.get_children(client = client, paths_only = False))

    child = transpose_children[0]
    expected_paths = []
    assert isinstance(child[1], ContainerStub)
    assert child[1].fields['categories'] == expected_categories
    for path in reference_container.paths:
        expected_paths.append(str(path))
    assert child[1].fields['paths'] == expected_paths

def test_transpose_errors(cli, base_dir):
    """
    Checks whether correct errors are thrown whenever a syntactically incorrect input
    is provided
    """
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', '/tmp/local-path',
        '--container', 'referenceContainer',
        '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    reference_url = f'file://{reference_path}'

    cli('container', 'create', 'Container', '--path', '/PATH')
    with pytest.raises(WildlandError, match='Could not parse rules:'):
        cli('storage', 'create', 'transpose', 'ProxyStorage',
            '--reference-container-url', reference_url,
            '--container', 'Container',
            '--rules', '!!wrong.syntax!!',
            '--no-inline')

    with pytest.raises(WildlandError, match='Expected any url:'):
        cli('storage', 'create', 'transpose', 'ProxyStorage',
            '--reference-container-url', 'wrong.url',
            '--container', 'Container',
            '--rules', '{"match-with": "/cat/one", "replace-with": "/cat/two"}',
            '--no-inline')

    with pytest.raises(WildlandError, match='one of the following values:'):
        cli('storage', 'create', 'transpose', 'ProxyStorage',
            '--reference-container-url', reference_url,
            '--container', 'Container',
            '--rules', '{"match-with": "/cat/one", "replace-with": "/cat/two"}',
            '--conflict', 'wrong-conflict',
            '--no-inline')

    cli('container', 'rm', 'Container')
