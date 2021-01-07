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

# pylint: disable=missing-docstring,redefined-outer-name

import pytest
from ..manifest.manifest import Manifest
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
    client.recognize_users()
    return client


def test_select_storage(client, base_dir):
    container = client.load_container_from('Container1')

    storage = client.select_storage(container)
    assert storage.params['location'] == str(base_dir / 'storage1')


def test_select_storage_unsupported(client, base_dir):
    container = client.load_container_from('Container1')

    storage_manifest = Manifest.from_fields({
        'owner': '0xaaa',
        'type': 'unknown'
    })
    storage_manifest.sign(client.session.sig)
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

    storage_manifest.sign(client.session.sig)
    storage_manifest_modified.sign(client.session.sig)

    with open(base_dir / 'storage' / 'Storage1.storage.yaml', 'wb') as f:
        f.write(storage_manifest.to_bytes())
    with open(base_dir / 'storage' / 'Storage2.storage.yaml', 'wb') as f:
        f.write(storage_manifest.to_bytes())
    with open(base_dir / 'storage' / 'Storage3.storage.yaml', 'wb') as f:
        f.write(storage_manifest_modified.to_bytes())

    storage = client.load_storage_from_path(base_dir / 'storage' / 'Storage1.storage.yaml')
    storage2 = client.load_storage_from_path(base_dir / 'storage' / 'Storage2.storage.yaml')
    storage3 = client.load_storage_from_path(base_dir / 'storage' / 'Storage3.storage.yaml')

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

    container = client.load_container_from('ContainerExt')

    assert {'/path', '/t1/t2/title', '/t3/title', '/t1/t2/t3/title', '/t3/t1/t2/title'} \
           == {str(p) for p in container.expanded_paths if 'uuid' not in str(p)}


def test_users_additional_pubkeys(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa', '--add-pubkey', 'key.0xbbb',
        '--add-pubkey', 'key.0xccc')
    cli('user', 'create', 'User2', '--key', '0xbbb')
    cli('user', 'create', 'User3', '--key', '0xccc', '--add-pubkey', 'key.0xddd')

    client = Client(base_dir=base_dir)
    client.recognize_users()

    assert set(client.session.sig.get_possible_owners('0xaaa')) == {'0xaaa'}
    assert set(client.session.sig.get_possible_owners('0xbbb')) == {'0xbbb', '0xaaa'}
    assert set(client.session.sig.get_possible_owners('0xddd')) == {'0xddd', '0xccc'}

    assert len(client.session.sig.keys) == 4
