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
        '--container', 'Container1')

    cli('storage', 'create', 'local', 'Storage2',
        '--path', base_dir / 'storage2',
        '--container', 'Container1')

@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    try:
        client.recognize_users()
        yield client
    finally:
        client.close()


def test_select_storage(client, base_dir):
    container = client.load_container_from('Container1')

    storage = client.select_storage(container)
    assert storage.params['path'] == str(base_dir / 'storage1')


def test_select_storage_unsupported(client, base_dir):
    container = client.load_container_from('Container1')

    storage_manifest = Manifest.from_fields({
        'signer': '0xaaa',
        'type': 'unknown'
    })
    storage_manifest.sign(client.session.sig)
    with open(base_dir / 'storage' / 'Storage1.yaml', 'wb') as f:
        f.write(storage_manifest.to_bytes())

    storage = client.select_storage(container)
    assert storage.params['path'] == str(base_dir / 'storage2')
