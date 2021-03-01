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

from wildland.storage_backends.encrypted_proxy import GoCryptFS, generate_password


# def test_encrypted_proxy_with_url(cli, base_dir):
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
#         '--container', 'Container', '--no-inline',
#         '--symmetrickey', '1234567890deadbeef')

#     client = Client(base_dir)
#     client.recognize_users()

#     # When loaded directly, the storage manifest contains container URL...
#     storage = client.load_storage_from('ProxyStorage')
#     assert storage.params['reference-container'] == reference_url

#     # But select_storage loads also the reference manifest
#     container = client.load_container_from('Container')
#     storage = client.select_storage(container)
#     assert storage.storage_type == 'encrypted-proxy'
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
def data_dir(base_dir):
    data_dir = Path(base_dir / 'data')
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def storage(data_dir):
    return {
        'type': 'encrypted-proxy',
        'storage': {
            'type': 'local',
            'location': str(data_dir),
            'backend-id': 'test',
            'owner': '0xaaa',
            'is-local-owner': True,
        },
        'backend-id': 'test2'
    }


@pytest.fixture
def container(cli, base_dir, data_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    # this needs to be saved, so client.load_containers() will see it
    (base_dir / 'containers').mkdir(parents=True)
    with (base_dir / 'containers/macro.container.yaml').open('w') as f:
        f.write(yaml.dump({
            'object': 'container',
            'owner': '0xaaa',
            'paths': [
                '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                '/PATH',
            ],
            'backends': {
                'storage': [{
                    'object': 'storage',
                    'type': 'date-proxy',
                    'owner': '0xaaa',
                    'container-path': '/.uuid/98cf16bf-f59b-4412-b54f-d8acdef391c0',
                    'backend-id': str(uuid.uuid4()),
                    'reference-container': {
                        'object': 'container',
                        'owner': '0xaaa',
                        'paths': ['/.uuid/39f437f3-b071-439c-806b-6d14fa55e827'],
                        'backends': {
                            'storage': [{
                                'object': 'storage',
                                'owner': '0xaaa',
                                'container-path': '/.uuid/39f437f3-b071-439c-806b-6d14fa55e827',
                                'type': 'local',
                                'location': str(data_dir),
                                'backend-id': str(uuid.uuid4())
                            }]
                        }
                    }
                }]
            }
        }))
    cli('container', 'sign', '-i', 'macro')

    yield 'macro'


def test_gcfs_runner(base_dir):
    cleardir = base_dir / 'clear'
    initdir = base_dir / 'init'
    encdir = base_dir / 'enc'
    os.mkdir(cleardir)
    os.mkdir(initdir)
    os.mkdir(encdir)
    # init, capture config
    runner = GoCryptFS.init(base_dir, initdir)

    # open for writing, working directory
    runner2 = GoCryptFS(base_dir, encdir, runner.credentials())
    runner2.run(cleardir)
    with open(cleardir / 'test.file', 'w') as f:
        f.write("string")
    assert 0 == runner2.stop()

    # open for reading, working directory
    runner3 = GoCryptFS(base_dir, encdir, runner.credentials())
    assert runner3.password
    assert runner3.config
    assert runner3.topdiriv
    runner3.run(cleardir)
    with open(cleardir / 'test.file', 'r') as f:
        assert "string" == f.read()
    assert 0 == runner3.stop()

def test_generate_password():
    assert ';' not in generate_password(100)
