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


# pylint: disable=missing-docstring,redefined-outer-name

@pytest.fixture
def setup(base_dir, cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/path')

    cli('storage', 'create', 'local', 'Storage1',
        '--path', base_dir / 'storage1',
        '--container', 'Container1', '--no-inline')

    cli('storage', 'create', 'local', 'Storage2',
        '--path', base_dir / 'storage2',
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
    assert storage.params['path'] == str(base_dir / 'storage1')


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
    assert storage.params['path'] == str(base_dir / 'storage2')


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
