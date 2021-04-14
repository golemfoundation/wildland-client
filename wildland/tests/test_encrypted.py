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
from pathlib import Path
import os
import time
import subprocess
import uuid
import zlib

import pytest

from wildland.storage_backends.encrypted import EncFS, GoCryptFS, generate_password
from wildland.storage_backends.local import LocalStorageBackend

from .fuse_env import FuseEnv
from ..client import Client

from ..cli.cli_base import ContextObj
from ..cli.cli_main import _do_mount_containers

def test_encrypted_with_url_and_gocryptfs(cli, base_dir):
    local_dir = base_dir / 'local'
    Path(local_dir).mkdir()
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', local_dir,
        '--container', 'referenceContainer', '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    # handle both files and paths here
    reference_url = 'wildland::/reference_PATH:'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'encrypted', 'ProxyStorage',
        '--reference-container-url', reference_url,
        '--engine', 'gocryptfs',
        '--container', 'Container', '--inline')

    client = Client(base_dir)

    obj = ContextObj(client)
    obj.fs_client = client.fs_client

    # But select_storage loads also the reference manifest
    container = client.load_container_from('Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'encrypted'
    assert storage.params['symmetrickey']
    assert storage.params['engine'] in ['gocryptfs', 'cryfs', 'encfs']
    reference_storage = storage.params['storage']
    assert isinstance(reference_storage, dict)
    assert reference_storage['type'] == 'local'

    # start and check if engine is running
    user = client.users['0xaaa']
    client.fs_client.mount(single_thread=False, default_user=user)
    _do_mount_containers(obj, ['referenceContainer'])
    _do_mount_containers(obj, ['Container'])

    # write and read a file
    mounted_plaintext = obj.fs_client.mount_dir / Path('/PATH').relative_to('/')
    assert os.listdir(mounted_plaintext) == [], "plaintext dir should be empty!"
    with open(mounted_plaintext / 'test.file', 'w') as ft:
        ft.write("1" * 10000) # low entropy plaintext file

    assert os.listdir(mounted_plaintext) == ['test.file']

    time.sleep(1) # time to let gocryptfs finish writing to plaintext dir

    # check if ciphertext directory looks familiar
    listing = os.listdir(local_dir)
    assert len(listing) == 3
    assert 'gocryptfs.conf' in listing
    assert 'gocryptfs.diriv' in listing
    listing.remove('gocryptfs.conf')
    listing.remove('gocryptfs.diriv')

    # read and examine entropy of ciphertext file
    with open(local_dir / listing[0], 'rb') as fb:
        enc_bytes = fb.read()
    packed_bytes = zlib.compress(enc_bytes)
    assert len(packed_bytes) * 1.05 > len(enc_bytes), "encrypted bytes are of low entropy!"

    time.sleep(1) # otherwise "unmount: /tmp/.../mnt: target is busy"

def test_encrypted_with_url_and_encfs(cli, base_dir):
    local_dir = base_dir / 'local'
    Path(local_dir).mkdir()
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', local_dir,
        '--container', 'referenceContainer', '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    # handle both files and paths here
    reference_url = 'wildland::/reference_PATH:'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'encrypted', 'ProxyStorage',
        '--reference-container-url', reference_url,
        '--engine', 'encfs',
        '--container', 'Container', '--inline')

    client = Client(base_dir)
    client.recognize_users()

    obj = ContextObj(client)
    obj.fs_client = client.fs_client

    # But select_storage loads also the reference manifest
    container = client.load_container_from('Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'encrypted'
    assert storage.params['symmetrickey']
    assert storage.params['engine'] in ['gocryptfs', 'cryfs', 'encfs']
    reference_storage = storage.params['storage']
    assert isinstance(reference_storage, dict)
    assert reference_storage['type'] == 'local'

    # start and check if engine is running
    user = client.users['0xaaa']
    client.fs_client.mount(single_thread=False, default_user=user)
    to_mount = ['Container']
    _do_mount_containers(obj, to_mount)
    subprocess.run(['pidof', 'encfs'], check=True)

    # write and read a file
    mounted_plaintext = obj.fs_client.mount_dir / Path('/PATH').relative_to('/')
    assert os.listdir(mounted_plaintext) == [], "plaintext dir should be empty!"
    with open(mounted_plaintext / 'test.file', 'w') as ft:
        ft.write("1" * 10000) # low entropy plaintext file

    assert os.listdir(mounted_plaintext) == ['test.file']

    time.sleep(1) # time to let gocryptfs finish writing to plaintext dir

    # check if ciphertext directory looks familiar
    listing = os.listdir(local_dir)
    assert len(listing) == 2
    assert '.encfs6.xml' in listing
    listing.remove('.encfs6.xml')

    # read and examine entropy of ciphertext file
    with open(local_dir / listing[0], 'rb') as fb:
        enc_bytes = fb.read()
    packed_bytes = zlib.compress(enc_bytes)
    assert len(packed_bytes) * 1.05 > len(enc_bytes), "encrypted bytes are of low entropy!"

    time.sleep(1) # otherwise "unmount: /tmp/.../mnt: target is busy"

@pytest.fixture
def env():
    env = FuseEnv()
    try:
        env.mount()
        yield env
    finally:
        env.destroy()

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
    runner = GoCryptFS.init(first, first_enc, None)

    # open for writing, working directory
    runner2 = GoCryptFS(second, second_enc, runner.credentials())
    params = {'location': second_enc,
              'type': 'local',
              'backend-id': str(uuid.uuid4())
              }
    runner2.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'w') as f:
        f.write("string")
    assert runner2.stop() == 0

    assert not (second_clear / 'test.file').exists()

    # open for reading, working directory
    runner3 = GoCryptFS(second, second_enc, runner.credentials())
    assert runner3.password
    assert runner3.config
    assert runner3.topdiriv
    runner3.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'r') as f:
        assert f.read() == "string"
    assert runner3.stop() == 0

def test_encfs_runner(base_dir):
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
    runner = EncFS.init(first, first_enc, first_clear)

    # open for writing, working directory
    runner2 = EncFS(second, second_enc, runner.credentials())
    params = {'location': second_enc,
              'type': 'local',
              'backend-id': str(uuid.uuid4())
              }
    runner2.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'w') as f:
        f.write("string")
    assert runner2.stop() == 0

    assert not (second_clear / 'test.file').exists()

    # open for reading, working directory
    runner3 = EncFS(second, second_enc, runner.credentials())
    assert runner3.password
    assert runner3.config
    runner3.run(second_clear, LocalStorageBackend(params=params))
    with open(second_clear / 'test.file', 'r') as f:
        assert f.read() == "string"
    assert runner3.stop() == 0

def test_generate_password():
    assert ';' not in generate_password(100)
