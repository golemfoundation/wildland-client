# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Frédéric Pierret <frederic@invisiblethingslab.com>,
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

# pylint: disable=missing-docstring,redefined-outer-name,relative-beyond-top-level

import os
import pytest

from wildland.exc import WildlandError
from ..client import Client
from ..wildland_object.wildland_object import WildlandObject


@pytest.fixture
def setup(base_dir, cli):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')
    cli('user', 'create', 'Charlie', '--key', '0xccc')

    cli('bridge', 'create', '--owner', 'Alice',
                            '--target-user', 'Bob',
                            '--path', '/users/bob',
                            '--path', '/people/bob',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'users/Bob.user.yaml'),
                            'br-bob')
    cli('bridge', 'create', '--owner', 'Alice',
                            '--target-user', 'Charlie',
                            '--path', '/users/charlie',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'users/Charlie.user.yaml'),
                            'br-charlie')
    cli('bridge', 'create', '--owner', 'Charlie',
                            '--target-user', 'Bob',
                            '--path', '/users/bob',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'users/Bob.user.yaml'),
                            'br-charlie-bob')

    cli('container', 'create', 'Container1', '--path', '/path')

    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container1', '--no-inline')

    template_dir = base_dir / 'template'
    os.mkdir(template_dir)
    cli('storage-template', 'create', 'local', '--location', template_dir, 'simple')


@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client


def test_user_repr(client):
    user = client.load_object_from_name(WildlandObject.Type.USER, "Alice")
    expected_str = "user(owner=0xaaa, paths=['/users/Alice'])"

    assert repr(user) == expected_str
    assert str(user) == expected_str


def test_storage_repr(client, cli):
    with pytest.raises(WildlandError, match='Failed to sync storage for container'):
        cli('storage', 'create', 'dropbox', '--container', 'Container1',
            '--inline', '--app-key', 'MY_SECRET_APP', '--refresh-token', 'MY_SECRET_TOKEN')

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, "Container1")
    storages = client.get_all_storages(container)

    for s in storages:
        assert repr(s) == f"storage(backend-id='{s.backend_id}')"
        assert str(s) == f"storage(backend-id='{s.backend_id}')"


# pylint: disable=unused-argument
def test_container_repr(client, cli):
    with pytest.raises(WildlandError, match='Failed to sync storage for container'):
        cli('storage', 'create', 'dropbox', '--container', 'Container1',
            '--inline', '--app-key', 'MY_SECRET_APP', '--refresh-token', 'MY_SECRET_TOKEN')

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, "Container1")
    dropbox_backend_id = None
    for s in container.manifest.fields['backends']['storage']:
        if isinstance(s, dict) and s["type"] == "dropbox":
            dropbox_backend_id = s['backend-id']

    assert dropbox_backend_id is not None

    expected_str = f"container(owner='0xaaa', paths=['/.uuid/{container.uuid}', '/path'], " \
                   f"local-path='{client.base_dir}/containers/Container1.container.yaml', " \
                   f"backends=['file://localhost{client.base_dir}/storage/Storage1.storage.yaml'," \
                   f" {{'type': 'dropbox', 'backend-id': '{dropbox_backend_id}'}}])"

    assert repr(container) == expected_str
    assert str(container) == expected_str


def test_bridge_repr(client):
    bridges = client.bridges
    for b in bridges:
        assert repr(b) == f"bridge(user='{b.user_location}', " \
                          f"paths={str([str(p) for p in b.paths])})"
        assert str(b) == f"bridge(user='{b.user_location}', " \
                         f"paths={str([str(p) for p in b.paths])})"


def test_link_repr(client, cli):
    cli('bridge', 'create', '--owner', 'Charlie', '--target-user', 'Charlie',
        '--target-user-location', f'file://{client.base_dir}/users/Charlie.user.yaml',
        '--path', '/forests/Charlie', 'self_bridge')
    cli('forest', 'create', '--owner', 'Charlie', 'simple')

    user = client.load_object_from_name(WildlandObject.Type.USER, "Charlie")
    link_dict = user.manifest.fields['manifests-catalog'][0]
    link = client.load_link_object(
        link_dict=link_dict, expected_owner=link_dict.get("storage-owner", None) or user.owner)

    assert repr(link) == 'link(file_path=/.manifests.container.yaml)'
