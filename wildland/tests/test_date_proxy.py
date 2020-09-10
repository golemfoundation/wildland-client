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


from pathlib import Path
import os
from datetime import datetime

import pytest

from .fuse_env import FuseEnv
from ..client import Client


def test_date_proxy_with_url(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'InnerContainer', '--path', '/INNER_PATH')
    cli('storage', 'create', 'local', 'InnerStorage', '--path', '/tmp/local-path',
        '--container', 'InnerContainer')

    inner_path = base_dir / 'containers/InnerContainer.container.yaml'
    assert inner_path.exists()
    inner_url = f'file://{inner_path}'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'date-proxy', 'ProxyStorage',
        '--inner-container-url', inner_url,
        '--container', 'Container')

    client = Client(base_dir)
    client.recognize_users()

    # When loaded directly, the storage manifest contains container URL...
    storage = client.load_storage_from('ProxyStorage')
    assert storage.params['inner-container'] == inner_url

    # But select_storage loads also the inner manifest
    container = client.load_container_from('Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'date-proxy'
    inner_storage = storage.params['storage']
    assert isinstance(inner_storage, dict)
    assert inner_storage['type'] == 'local'


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
        'type': 'date-proxy',
        'storage': {
            'type': 'local',
            'path': str(data_dir),
        }
    }


def walk_all(path: Path):
    return list(_walk_all(path, path))

def _walk_all(root, path):
    for sub_path in sorted(path.iterdir()):
        if sub_path.is_dir():
            yield str(sub_path.relative_to(root)) + '/'
            yield from _walk_all(root, sub_path)
        else:
            yield str(sub_path.relative_to(root))


def test_date_proxy_fuse_empty(env, storage):
    env.mount_storage(['/proxy'], storage)
    assert os.listdir(env.mnt_dir / 'proxy') == []


def test_date_proxy_fuse_files(env, storage, data_dir):
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    (data_dir / 'dir2/dir3').mkdir(parents=True)
    (data_dir / 'dir2/dir3/file2').write_text('file 2')
    os.utime(data_dir / 'dir2/dir3/file2',
             (int(datetime(2008, 2, 3, 10, 30).timestamp()),
              int(datetime(2008, 2, 3, 10, 30).timestamp())))

    # Empty directory, should be ignored
    (data_dir / 'dir4').mkdir()

    env.mount_storage(['/proxy'], storage)
    assert walk_all(env.mnt_dir / 'proxy') == [
        '2008/',
        '2008/02/',
        '2008/02/03/',
        '2008/02/03/dir2/',
        '2008/02/03/dir2/dir3/',
        '2008/02/03/dir2/dir3/file2',
        '2010/',
        '2010/05/',
        '2010/05/07/',
        '2010/05/07/dir1/',
        '2010/05/07/dir1/file1',
    ]

    assert Path(env.mnt_dir / 'proxy/2010/05/07/dir1/file1').read_text() == \
        'file 1'
    assert Path(env.mnt_dir / 'proxy/2008/02/03/dir2/dir3/file2').read_text() == \
        'file 2'
