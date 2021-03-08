# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Pawel Peregud <pepesza@wildland.io>
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
from pathlib import Path, PurePosixPath
import os
from datetime import datetime
import uuid
import yaml

import pytest

from .fuse_env import FuseEnv
from ..client import Client

from wildland.storage_backends.encrypted_proxy import GoCryptFS, generate_password, gen_backend_id
from wildland.storage_backends.local import LocalStorageBackend, LocalFile, to_attr
from wildland.storage_backends.base import StorageBackend, Attr


# def test_encrypted_proxy_with_url(env, cli, base_dir):
#     cli('user', 'create', 'User', '--key', '0xaaa')
#     cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
#     cli('storage', 'create', 'local', 'referenceStorage', '--location', '/tmp/local-path',
#         '--container', 'referenceContainer', '--no-inline')

#     reference_path = base_dir / 'containers/referenceContainer.container.yaml'
#     assert reference_path.exists()
#     reference_url = f'file://{reference_path}'

#     cli('container', 'create', 'Container', '--path', '/PATH')
#     cli('storage', 'create', 'encrypted-proxy', 'ProxyStorage',
#         '--reference-container-url', reference_url,
#         '--container', 'Container', '--no-inline')

#     client = Client(base_dir)
#     client.recognize_users()

#     # When loaded directly, the storage manifest contains container URL...
#     storage = client.load_storage_from('ProxyStorage')
#     assert storage.params['reference-container'] == reference_url

#     # But select_storage loads also the reference manifest
#     container = client.load_container_from('Container')
#     storage = client.select_storage(container)
#     assert storage.storage_type == 'encrypted-proxy'
#     assert storage.params['symmetrickey']
#     assert storage.params['engine'] in ['gocryptfs', 'cryfs', 'encfs']
#     reference_storage = storage.params['storage']
#     assert isinstance(reference_storage, dict)
#     assert reference_storage['type'] == 'local'

@pytest.fixture
def env():
    env = FuseEnv()
    try:
        env.mount()
        yield env
    finally:
        env.destroy()

@pytest.fixture
def storage_dir(base_dir):
    storage_dir = Path(base_dir / 'storage_dir')
    storage_dir.mkdir()
    return storage_dir

@pytest.fixture
def storage(storage_dir):
    return {
        'type': 'encrypted-proxy',
        'symmetrickey': 'NqI1eJypujyJQbLeqN6vggvJpWTqn6;ewoJIkNyZWF0b3IiOiAiZ29jcnlwdGZzIDEuOC4wIiwKCSJFbmNyeXB0ZWRLZXkiOiAiczRtQmtta05sRGdzdDJUblZjeDBCaDQ1cVVnakUwb0ZzdXp5TkI1Q3dxWnU0MURJVTRNMi9VYmZqRERvNUhZcWhDZXMxNVFkcEhYRlFHWmhGWWtsWFE9PSIsCgkiU2NyeXB0T2JqZWN0IjogewoJCSJTYWx0IjogIi9OYW1qaWdrY3F4NHJjS0ZHdS9sdkdsU0ZnV0J4SGYwdm0vSmhydVluc2M9IiwKCQkiTiI6IDY1NTM2LAoJCSJSIjogOCwKCQkiUCI6IDEsCgkJIktleUxlbiI6IDMyCgl9LAoJIlZlcnNpb24iOiAyLAoJIkZlYXR1cmVGbGFncyI6IFsKCQkiR0NNSVYxMjgiLAoJCSJIS0RGIiwKCQkiRGlySVYiLAoJCSJFTUVOYW1lcyIsCgkJIkxvbmdOYW1lcyIsCgkJIlJhdzY0IgoJXQp9Cg==;6af6KVAmgVyBocDWP7ETJw==',
        'engine': 'gocryptfs',
        'backend-id': 'test-plain',
        'owner': '0xaaa',
        'storage': {
            'type': 'local',
            'location': str(storage_dir),
            'backend-id': 'test-enc',
            'owner': '0xaaa',
            'is-local-owner': True,
            'container-path': '/encrypted'
        }
    }

def test_delegate_fuse_empty(env, storage):
    env.mount_storage(['/encrypted'], storage['storage'])
    env.mount_storage(['/plaintext'], storage)
    # assert os.listdir(env.mnt_dir / 'plaintext') == []

def test_gocryptfs_runner(base_dir):
    first = base_dir / 'a'
    first_clear = first / 'clear'
    first_enc = first / 'enc'
    second = base_dir / 'b'
    second_clear = second / 'clear'
    second_enc = second / 'enc'
    first.mkdir()
    first_clear.mkdir()
    first_enc.mkdir()
    second.mkdir()
    second_clear.mkdir()
    second_enc.mkdir()

    # init, capture config
    runner = GoCryptFS.init(first, first_enc)

    # open for writing, working directory
    runner2 = GoCryptFS(second, second_enc, runner.credentials())
    params = {'location': second_enc,
              'type': 'local'}
    gen_backend_id(params)
    runner2.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'w') as f:
        f.write("string")
    assert 0 == runner2.stop()

    assert not (second_clear / 'test.file').exists()

    # open for reading, working directory
    runner3 = GoCryptFS(second, second_enc, runner.credentials())
    assert runner3.password
    assert runner3.config
    assert runner3.topdiriv
    runner3.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'r') as f:
        assert "string" == f.read()
    assert 0 == runner3.stop()

def test_generate_password():
    assert ';' not in generate_password(100)
