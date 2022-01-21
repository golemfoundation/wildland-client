# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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

# pylint: disable=missing-docstring,redefined-outer-name,protected-access

import tempfile
from pathlib import Path

import pytest

from wildland.wildland_object.wildland_object import WildlandObject
from ..client import Client
from ..manifest.sig import DummySigContext
from ..container import Container, _StorageCache
from ..storage import Storage


@pytest.fixture(scope='session')
def key_dir():
    with tempfile.TemporaryDirectory(prefix='wlsecret.') as d:
        yield Path(d)


@pytest.fixture
def sig(key_dir):
    return DummySigContext(key_dir)


@pytest.fixture
def owner(sig):
    own, pubkey = sig.generate()
    sig.add_pubkey(pubkey)
    return own


@pytest.fixture
def client(base_dir, sig):
    yield Client(base_dir, sig)


def test_add_storage(client, owner):
    container = Container(owner=owner, paths=[], backends=[], client=client)
    cont_path = client.save_new_object(WildlandObject.Type.CONTAINER, container, "container")
    storage = Storage(
        storage_type='local',
        owner=owner,
        container=container,
        params={},
        client=client,
        trusted=True,
        access=None)

    client.add_storage_to_container(container, [storage])

    assert len(container._storage_cache) == 1

    cont_data = cont_path.read_text()
    assert 'backend-id' in cont_data
    assert 'object: storage' in cont_data

    # duplicate should not be re-added
    client.add_storage_to_container(container, [storage])
    assert len(container._storage_cache) == 1

    # but changes should be reflected
    storage.access = [{'user': '*'}]
    client.add_storage_to_container(container, [storage])
    assert len(container._storage_cache) == 1
    assert container._storage_cache[0].storage['access'] == [{'user': '*'}]


def test_add_storage_not_inline(client, owner):
    client.config.override(override_fields={'local-owners': [owner]})
    container = Container(owner=owner, paths=[], backends=[], client=client)
    client.save_new_object(WildlandObject.Type.CONTAINER, container, "container")
    storage = Storage(
        storage_type='local',
        owner=owner,
        container=container,
        params={},
        client=client,
        trusted=True,
        access=None)

    client.add_storage_to_container(container, [storage], False, "storage")

    assert len(container._storage_cache) == 1
    assert container._storage_cache[0].storage.startswith('file://localhost')

    storage_path = Path(container._storage_cache[0].storage[len('file://localhost'):])
    assert 'type: local' in storage_path.read_text()

    # re-adding should not cause duplicates
    client.add_storage_to_container(container, [storage], False, "storage")
    assert len(container._storage_cache) == 1

    # but changes should be reflected
    storage.access = [{'user': '*'}]
    client.add_storage_to_container(container, [storage])
    assert len(container._storage_cache) == 1
    assert '*' in storage_path.read_text()


def test_add_storage_link(client, owner, tmpdir):
    client.config.override(override_fields={'local-owners': [owner]})
    container = Container(owner=owner, paths=[], backends=[], client=client)

    storage = Storage(
        storage_type='local',
        owner=owner,
        container=container,
        params={},
        client=client,
        trusted=True,
        access=None)

    target_dir = Path(tmpdir / 'test')
    target_dir.mkdir()

    storage_path = client.save_new_object(WildlandObject.Type.STORAGE, storage,
                                          "storage", target_dir / "s.storage.yaml")

    container._storage_cache.append(_StorageCache({
        'storage': {'type': 'local', 'location': str(target_dir), 'owner': owner,
                    'object': 'storage', 'backend-id': 'test'},
        'file': '/s.storage.yaml',
        'object': 'link'
    }, None))

    client.save_new_object(WildlandObject.Type.CONTAINER, container, "container")

    # reflect changes
    storage.access = [{'user': '*'}]
    client.add_storage_to_container(container, [storage])
    assert len(container._storage_cache) == 1
    assert '*' in storage_path.read_text()


def test_unquote_local_path(client, owner):
    client.config.override(override_fields={'local-owners': [owner]})
    local_url = 'file:///Users/Jan%20Kowalski/whatever'
    path = client.parse_file_url(local_url, owner)
    assert str(path) == '/Users/Jan Kowalski/whatever'
