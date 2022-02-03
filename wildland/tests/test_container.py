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

# pylint: disable=missing-docstring,redefined-outer-name

import pytest
from wildland.wildland_object.wildland_object import WildlandObject
from ..manifest.manifest import Manifest
from ..wildland_object.wildland_object import WildlandObject
from ..client import Client
from ..storage import StorageBackend


# pylint: disable=missing-docstring,redefined-outer-name

@pytest.fixture
def setup(base_dir, cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/path')

    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container1', '--no-inline')

    cli('storage', 'create', 'local', 'Storage2',
        '--location', base_dir / 'storage2',
        '--container', 'Container1', '--no-inline')


@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client


def test_select_storage(client, base_dir):
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')

    storage = client.select_storage(container)
    assert storage.params['location'] == str(base_dir / 'storage1')


def test_select_storage_unsupported(client, base_dir):
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')

    storage_manifest = Manifest.from_fields({
        'owner': '0xaaa',
        'type': 'unknown'
    })
    storage_manifest.encrypt_and_sign(client.session.sig)
    with open(base_dir / 'storage' / 'Storage1.storage.yaml', 'wb') as f:
        f.write(storage_manifest.to_bytes())

    storage = client.select_storage(container)
    assert storage.params['location'] == str(base_dir / 'storage2')


def test_storage_without_backend_id(client, base_dir):
    base_dict = {
        'owner': '0xaaa',
        'type': 'local',
        'path': '/PATH',
        'container-path': str(base_dir / 'storage2')}
    modified_dict = base_dict.copy()
    modified_dict['container-path'] = str(base_dir / 'storage3')

    storage_manifest = Manifest.from_fields(base_dict)
    storage_manifest_modified = Manifest.from_fields(modified_dict)

    storage_manifest.encrypt_and_sign(client.session.sig)
    storage_manifest_modified.encrypt_and_sign(client.session.sig)

    with open(base_dir / 'storage' / 'Storage1.storage.yaml', 'wb') as f:
        f.write(storage_manifest.to_bytes())
    with open(base_dir / 'storage' / 'Storage2.storage.yaml', 'wb') as f:
        f.write(storage_manifest.to_bytes())
    with open(base_dir / 'storage' / 'Storage3.storage.yaml', 'wb') as f:
        f.write(storage_manifest_modified.to_bytes())

    storage = client.load_object_from_file_path(WildlandObject.Type.STORAGE,
        base_dir / 'storage' / 'Storage1.storage.yaml')
    storage2 = client.load_object_from_file_path(WildlandObject.Type.STORAGE,
        base_dir / 'storage' / 'Storage2.storage.yaml')
    storage3 = client.load_object_from_file_path(WildlandObject.Type.STORAGE,
        base_dir / 'storage' / 'Storage3.storage.yaml')

    backend = StorageBackend.from_params(storage.params)
    backend2 = StorageBackend.from_params(storage2.params)
    backend3 = StorageBackend.from_params(storage3.params)

    assert backend.backend_id is not None
    # Generated backend id should be based on parameters
    assert backend.backend_id == backend2.backend_id
    assert backend.backend_id != backend3.backend_id


def test_expanded_paths(client, cli):
    cli('container', 'create', 'ContainerExt', '--path', '/path', '--title',
        'title', '--category', '/t1/t2', '--category', '/t3')

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'ContainerExt')
    uuid = container.uuid

    assert {'/path', '/t1/t2/title', '/t3/title', '/t1/t2/@t3/title', '/t3/@t1/t2/title'} \
           == {str(p) for p in container.expanded_paths if 'uuid' not in str(p)}

    assert str(container.expanded_paths[0]) == f'/.uuid/{uuid}'


def test_users_additional_pubkeys(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa', '--add-pubkey', 'key.0xbbb',
        '--add-pubkey', 'key.0xccc')
    cli('user', 'create', 'User2', '--key', '0xbbb')
    cli('user', 'create', 'User3', '--key', '0xccc', '--add-pubkey', 'key.0xddd')

    client = Client(base_dir=base_dir)

    assert set(client.session.sig.get_possible_owners('0xaaa')) == {'0xaaa'}
    assert set(client.session.sig.get_possible_owners('0xbbb')) == {'0xbbb', '0xaaa'}
    assert set(client.session.sig.get_possible_owners('0xddd')) == {'0xddd', '0xccc'}

    assert len(client.session.sig.keys) == 4


def test_catalog_cache(cli, client):
    cli('container', 'create', 'ContainerWithCatalog', '--path', '/p1', '--update-user')

    user = client.load_object_from_name(WildlandObject.Type.USER, "User")

    container = next(user.load_catalog())
    assert not container.title
    container.title = 'Test'

    # test that we got the same object
    container2 = next(user.load_catalog())
    assert container2.title == 'Test'


def test_storage_cache(client):
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, "Container1")

    storages = list(container.load_storages())
    assert 'storage1' in storages[0].params['location']
    storages[0].params['location'] = '/test'

    # test that we got the same object
    storages = list(container.load_storages())
    assert 'storage1' not in storages[0].params['location']
    assert storages[0].params['location'] == '/test'


def test_manifest_catalog_format(client):
    user = client.load_object_from_name(WildlandObject.Type.USER, 'User')
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container1')
    fields = container.to_manifest_fields(inline=False)

    user.add_catalog_entry(fields)

    user_fields = user.to_manifest_fields(inline=False)

    assert user_fields['manifests-catalog'][0]['object'] == 'container'
    assert 'version' not in user_fields['manifests-catalog'][0]
    assert 'owner' not in user_fields['manifests-catalog'][0]


def test_recursion_bomb(cli, base_dir, client):
    cli('user', 'create', 'User', '--key', '0xaaa')
    with open(base_dir / 'containers/bomb-1.container.yaml', 'w') as f:
        f.write("""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - /.uuid/e60a489b-1c34-475c-85aa-50979e28742e
 - /bomb-1
object: container
backends:
  storage:
    - object: storage
      type: delegate
      backend-id: 249097f9-563e-4e0c-8332-082ac3caad7d
      reference-container: 'wildland::/bomb-2:'
        """)

    with open(base_dir / 'containers/bomb-2.container.yaml', 'w') as f:
        f.write("""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - /.uuid/c2d147a8-28cd-4a76-b55d-90869210bcd9
 - /bomb-2
object: container
backends:
  storage:
    - object: storage
      type: delegate
      backend-id: 17017282-23ac-40d4-841a-75ced0266509
      reference-container: 'wildland::/bomb-1:'
        """)

    # faulty storages should not be loadable
    bomb1 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'bomb-1')
    bomb2 = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'bomb-2')
    assert not list(bomb1.load_storages())
    assert not list(bomb2.load_storages())
