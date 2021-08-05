# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Patryk Bęza <patryk@wildland.io>,
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

# pylint: disable=missing-docstring

import pytest
from pathlib import Path
import os

from ..client import Client
from ..cli.cli_base import ContextObj
from ..cli.cli_container import prepare_mount
from ..wildland_object.wildland_object import WildlandObject


def test_pseudomanifest_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'static', 'Storage',
        '--file', 'foo.txt=foo content',
        '--container', 'Container', '--no-inline', '--no-encrypt-manifest')

    client = Client(base_dir)

    obj = ContextObj(client)
    obj.fs_client = client.fs_client

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'static'

    user = client.users['0xaaa']
    client.fs_client.start(single_thread=False, default_user=user)

    user_paths = obj.client.get_bridge_paths_for_user(container.owner)
    commands = list(prepare_mount(obj, container, str(container.local_path), user_paths,
                                  remount=False, with_subcontainers=True, subcontainer_of=None,
                                  verbose=False, only_subcontainers=False))
    obj.fs_client.mount_multiple_containers(commands)

    mounted_path = obj.fs_client.mount_dir / Path('/PATH').relative_to('/')
    assert sorted(os.listdir(mounted_path)) == ['.manifest.wildland.yaml', 'foo.txt']

    assert os.listdir(mounted_path) == ['.manifest.wildland.yaml', 'foo.txt'], \
        "plaintext dir should contain pseudomanifest only!"

    with open(mounted_path / '.manifest.wildland.yaml', 'rb') as fb:
        pseudomanifest_content_bytes = fb.read()

    assert pseudomanifest_content_bytes.decode() == \
f'''object: container
owner: '0xaaa'
paths:
- /.uuid/{container.uuid}
- /PATH
title: 'null'
categories: []
version: '1'
access:
- user: '*'
'''


def mount(cli, base_dir, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'Container',
        '--inline',
        '--no-encrypt-manifest')

    client = Client(base_dir)

    obj = ContextObj(client)
    obj.fs_client = client.fs_client

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container')

    user = client.users['0xaaa']
    client.fs_client.start(single_thread=False, default_user=user)

    user_paths = obj.client.get_bridge_paths_for_user(container.owner)
    commands = list(prepare_mount(obj, container, str(container.local_path), user_paths,
                                  remount=False, with_subcontainers=True, subcontainer_of=None,
                                  verbose=False, only_subcontainers=False))
    obj.fs_client.mount_multiple_containers(commands)

    return obj.fs_client.mount_dir


def pseudomanifest_replace(pseudomanifest_path, to_replace, new):
    with open(pseudomanifest_path, 'r+') as f:
        pseudomanifest_content = f.read()
        new_pseudomanifest_content = pseudomanifest_content.replace(
            to_replace, new)
        f.truncate()
        f.write(new_pseudomanifest_content)


def test_pseudomanifest_editable(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)

    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    assert sorted(os.listdir(mounted_path)) == ['.manifest.wildland.yaml'], \
        "plaintext dir should contain pseudomanifest only!"

    with open(mounted_path / 'new.file', 'w') as new_file:
        new_file.write("I'm editable!")

    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'
    with open(pseudomanifest_path, 'r+'):
        pass


def test_pseudomanifest_edit_path(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)
    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'

    pseudomanifest_replace(pseudomanifest_path, "paths:\n", "paths:\n- /NEW\n")
    with open(base_dir/"containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert "- /NEW" in content
        assert "paths:\\n- /.uuid/" in content

    pseudomanifest_replace(pseudomanifest_path, "- /NEW\n", "")
    with open(base_dir/"containers/Container.container.yaml", "r") as f:
        assert "- /NEW" not in f.read()


def test_pseudomanifest_edit_category(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)
    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'

    pseudomanifest_replace(pseudomanifest_path, "categories: []", "categories:\n- /cat")
    with open(base_dir/"containers/Container.container.yaml", "r") as f:
        assert "- /cat" in f.read()

    pseudomanifest_replace(pseudomanifest_path, "categories:\n- /cat", "categories: []")
    with open(base_dir/"containers/Container.container.yaml", "r") as f:
        assert "categories: []" in f.read()


def test_pseudomanifest_edit_category_goes_wrong(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)
    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        old_content = f.read()

    with pytest.raises(OSError, match='Invalid argument'):
        pseudomanifest_replace(pseudomanifest_path, "categories: []", "categories:\n- cat")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        assert old_content == f.read()

    with open(pseudomanifest_path, 'r') as f:
        assert "rejected due to encountered errors" in f.read()


def test_pseudomanifest_edit_set_title(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)
    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'

    pseudomanifest_replace(pseudomanifest_path, "title: 'null'", "title: title")
    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        assert "title: title" in f.read()

    pseudomanifest_replace(pseudomanifest_path, "title: title", "title: 'null'")
    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        assert "title: 'null'" in f.read()


def test_pseudomanifest_edit_user(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)
    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        old_content = f.read()

    with pytest.raises(OSError, match='Invalid argument'):
        pseudomanifest_replace(pseudomanifest_path, "0xaaa", "0xbbb")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        assert old_content == f.read()

    with open(pseudomanifest_path, 'r') as f:
        assert "rejected due to encountered errors" in f.read()


def test_pseudomanifest_truncate(cli, base_dir, tmp_path):
    mount_dir = mount(cli, base_dir, tmp_path)
    mounted_path = mount_dir / Path('/PATH').relative_to('/')
    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'

    with open(pseudomanifest_path, 'r') as f:
        old_content = f.read()

    with open(pseudomanifest_path, 'r+') as f:
        f.truncate()

    with open(pseudomanifest_path, 'r') as f:
        assert old_content == f.read()
