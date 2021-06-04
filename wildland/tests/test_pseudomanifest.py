# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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

# pylint: disable=missing-docstring

from pathlib import Path
import os

from ..client import Client
from ..cli.cli_base import ContextObj
from ..cli.cli_container import prepare_mount
from ..wildland_object.wildland_object import WildlandObject


def test_pseudomanifest(cli, base_dir):
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
    client.fs_client.mount(single_thread=False, default_user=user)

    user_paths = obj.client.get_bridge_paths_for_user(container.owner)
    commands = list(prepare_mount(obj, container, str(container.local_path), user_paths,
        remount=False, with_subcontainers=True, subcontainer_of=None, verbose=False,
        only_subcontainers=False))
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
