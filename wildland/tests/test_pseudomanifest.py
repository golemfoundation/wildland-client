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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument

import os
from pathlib import Path, PurePosixPath
import pytest

from ..client import Client
from ..wildland_object.wildland_object import WildlandObject
from ..storage_backends.pseudomanifest import PseudomanifestStorageBackend


@pytest.fixture
def setup(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'Container',
        '--inline',
        '--no-encrypt-manifest')

    cli('user', 'create', 'UserB', '--key', '0xbbb')
    cli('container', 'create', 'ContainerB', '--path', '/PATH', '--owner', 'UserB',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'StorageB',
        '--location', os.fspath(tmp_path),
        '--container', 'ContainerB',
        '--inline',
        '--no-encrypt-manifest')


@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client


def test_pseudomanifest_create(client, cli, base_dir):
    cli('start', '--default-user', 'User')
    cli('container', 'mount', 'Container')

    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container')
    mounted_path = client.fs_client.mount_dir / Path('/PATH').relative_to('/')

    assert os.listdir(mounted_path) == ['.manifest.wildland.yaml'], \
        "plaintext dir should contain pseudomanifest only!"

    with open(mounted_path / 'new.file', 'w') as new_file:
        new_file.write("I'm editable!")

    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'
    with open(pseudomanifest_path, 'r+'):
        pass

    with open(mounted_path / '.manifest.wildland.yaml', 'rb') as fb:
        pseudomanifest_content_bytes = fb.read()

    assert pseudomanifest_content_bytes.decode() == \
f'''# All YAML comments will be discarded when the manifest is saved
version: '1'
object: container
owner: '0xaaa'
paths:
- /.uuid/{container.uuid}
- /PATH
title: 'null'
categories: []
access:
- user: '*'
'''


def get_pseudomanifest_storage(client, container_name):
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, container_name)
    storage = next(container.load_storages())
    # pylint: disable=protected-access
    pm_storage = client.fs_client._generate_pseudomanifest_storage(container, storage)
    return PseudomanifestStorageBackend(params=pm_storage.params)


def pseudomanifest_replace(container_name, client, to_replace, new, expected_os_error=False):
    """Open pseudomanifest file for first storage from a container and replace phrase
    `to_replace` to `new`.

    Return pseudomanifest storage backend.
    """
    pm_backend = get_pseudomanifest_storage(client, container_name)

    # open pseudomanifest file and replace given phrase
    pm_file = pm_backend.open(PurePosixPath(), flags=0)
    pseudomanifest_content = pm_file.read().decode()
    new_pseudomanifest_content = pseudomanifest_content.replace(to_replace, new)
    pm_file.ftruncate(0)
    pm_file.write(new_pseudomanifest_content.encode(), offset=0)

    try:
        # try to save changes
        pm_file.release(0)
    except OSError:
        # if changes are incorrect, pseudomanifest is rejected and OSError is raised
        if expected_os_error:
            pass
        else:
            raise
    else:
        # container manifest changed, get new pseudomanifest storage backend
        pm_backend = get_pseudomanifest_storage(client, container_name)
    return pm_backend


def test_edit_path(client, base_dir):
    pm_backend = pseudomanifest_replace("Container", client, "paths:\n", "paths:\n- /NEW\n")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert "- /NEW" in content
        assert "paths:\n- /.uuid/" in content

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "- /NEW" in content
        assert "paths:\n- /.uuid/" in content


def test_edit_with_non_default_owner(client, base_dir):
    pm_backend = pseudomanifest_replace("ContainerB", client, "paths:\n", "paths:\n- /NEW\n")

    with open(base_dir / "containers/ContainerB.container.yaml", "r") as f:
        content = f.read()
        assert "- /NEW" in content
        assert "paths:\n- /.uuid/" in content

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "- /NEW" in content
        assert "paths:\n- /.uuid/" in content


def test_edit_category(client, base_dir):
    pm_backend = pseudomanifest_replace(
        "Container", client, "categories: []", "categories:\n- /cat")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert "- /cat" in content
    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "- /cat" in content

    pm_backend = pseudomanifest_replace(
        "Container", client, "categories:\n- /cat", "categories: []")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert "categories: []" in content
    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "categories: []" in content


def test_edit_category_goes_wrong(client, base_dir):
    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        old_content = f.read()

    pm_backend = pseudomanifest_replace(
        "Container", client, "categories: []", "categories:\n- cat", expected_os_error=True)

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        assert old_content == f.read()

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "rejected due to encountered errors" in content


def pseudomanifest_replace_old(pseudomanifest_path, to_replace, new):
    with open(pseudomanifest_path, 'r+') as f:
        pseudomanifest_content = f.read()
        new_pseudomanifest_content = pseudomanifest_content.replace(
            to_replace, new)
        f.truncate(0)
        f.write(new_pseudomanifest_content)


def test_set_title(client, base_dir):
    pm_backend = pseudomanifest_replace("Container", client, "title: 'null'", "title: 'title'")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert "title: title" in content

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "title: title" in content

    pm_backend = pseudomanifest_replace("Container", client, "title: title", "title: 'null'")

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert "title: 'null'" in content

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "title: 'null'" in content


def test_edit_uuid(client, base_dir):
    pm_backend = pseudomanifest_replace(
        "Container", client, "/.uuid/", "/", expected_os_error=True)

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "rejected due to encountered errors" in content


def test_edit_user(client, base_dir):
    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        old_content = f.read()

    pm_backend = pseudomanifest_replace(
        "Container", client, "0xaaa", "0xbbb", expected_os_error=True)

    with open(base_dir / "containers/Container.container.yaml", "r") as f:
        content = f.read()
        assert old_content == content

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "rejected due to encountered errors" in content

    pm_backend = pseudomanifest_replace(
        "Container", client, "0xaaa", "0xccc", expected_os_error=True)

    # check if only latest error messages are available
    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert "0xbbb" not in content
        assert "0xccc" in content


def test_ignore_whitespaces(client, base_dir):
    pm_backend = pseudomanifest_replace("Container", client, "", "")

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        old_content = f.read()

    pm_backend = pseudomanifest_replace("Container", client, "paths:", "paths:    \n")

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        assert old_content == f.read()


def test_many_changes_at_once(client, base_dir):
    uuid_path = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container').uuid_path

    pseudomanifest_content = \
        f'''# All YAML comments will be discarded when the manifest is saved
version: '1'
object: container
owner: '0xaaa'
paths:
- {uuid_path}
- /PATH
- /NEW
title: new_title
categories:
- /cat1
access:
- user: '*'
'''

    pm_backend = get_pseudomanifest_storage(client, "Container")
    pm_file = pm_backend.open(PurePosixPath(), flags=0)
    pm_file.ftruncate(0)
    pm_file.write(pseudomanifest_content.encode(), offset=0)
    pm_file.release(0)
    pm_backend = get_pseudomanifest_storage(client, "Container")  # remount if success

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        content = f.read().decode()
        assert content == pseudomanifest_content

    new_content = \
        f'''version: '1'
object: container
owner: '0xaaa'
paths:
- {uuid_path}
- /PATH
- /PATH
- /Ano/ther
title: other_title
categories:
- /cat2
- /cat2
access:
- user: '*'
'''

    expexted_content = \
        f'''# All YAML comments will be discarded when the manifest is saved
version: '1'
object: container
owner: '0xaaa'
paths:
- {uuid_path}
- /PATH
- /Ano/ther
title: other_title
categories:
- /cat2
access:
- user: '*'
'''

    pm_backend = get_pseudomanifest_storage(client, "Container")
    pm_file = pm_backend.open(PurePosixPath(), flags=0)
    pm_file.ftruncate(0)
    pm_file.write(new_content.encode(), offset=0)
    pm_file.release(0)
    pm_backend = get_pseudomanifest_storage(client, "Container")  # remount if success

    with pm_backend.open(PurePosixPath(), flags=0) as f:
        assert f.read().decode() == expexted_content


def pseudomanifest_edit(client, cli):
    cli('start', '--default-user', 'User')
    cli('container', 'mount', 'Container')
    cli('container', 'mount', 'ContainerB')

    mount_dir = client.fs_client.mount_dir
    mounted_path = mount_dir / Path('/PATH').relative_to('/')

    assert sorted(os.listdir(mounted_path)) == ['.manifest.wildland.yaml'], \
        "plaintext dir should contain pseudomanifest only!"

    with open(mounted_path / 'new.file', 'w') as new_file:
        new_file.write("I'm editable!")

    pseudomanifest_path = mounted_path / '.manifest.wildland.yaml'
    with open(pseudomanifest_path, 'r+'):
        pass
