# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=missing-docstring,redefined-outer-name


from pathlib import Path
import os
import uuid
from datetime import datetime

import pytest

from wildland.wildland_object.wildland_object import WildlandObject
from .helpers import treewalk
from ..client import Client


def test_delegate_with_url(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'referenceContainer', '--path', '/reference_PATH')
    cli('storage', 'create', 'local', 'referenceStorage', '--location', '/tmp/local-path',
        '--container', 'referenceContainer', '--no-inline')

    reference_path = base_dir / 'containers/referenceContainer.container.yaml'
    assert reference_path.exists()
    reference_url = f'file://{reference_path}'

    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'delegate', 'ProxyStorage',
        '--reference-container-url', reference_url,
        '--container', 'Container', '--no-inline')

    client = Client(base_dir)

    # When loaded directly, the storage manifest contains container URL...
    storage = client.load_object_from_name(WildlandObject.Type.STORAGE, 'ProxyStorage')
    assert storage.params['reference-container'] == reference_url

    # But select_storage loads also the reference manifest
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, 'Container')
    storage = client.select_storage(container)
    assert storage.storage_type == 'delegate'
    reference_storage = storage.params['storage']
    assert isinstance(reference_storage, dict)
    assert reference_storage['type'] == 'local'


@pytest.fixture
def data_dir(base_dir):
    data_dir = Path(base_dir / 'data')
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def storage(data_dir):
    return {
        'type': 'delegate',
        'storage': {
            'type': 'local',
            'owner': '0xaaa',
            'is-local-owner': True,
            'location': str(data_dir),
            'backend-id': str(uuid.uuid4()),
        },
        'backend-id': str(uuid.uuid4()),
    }


@pytest.fixture
def storage_subdir(data_dir):
    return {
        'type': 'delegate',
        'subdirectory': '/dir1',
        'backend-id': str(uuid.uuid4()),
        'storage': {
            'type': 'local',
            'owner': '0xaaa',
            'is-local-owner': True,
            'location': str(data_dir),
            'backend-id': str(uuid.uuid4())
        }
    }


def test_delegate_fuse_empty(env, storage):
    env.mount_storage(['/proxy'], storage)
    assert os.listdir(env.mnt_dir / 'proxy') == []


def test_delegate_fuse_files(env, storage, data_dir):
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    # Empty directory
    (data_dir / 'dir2').mkdir()

    env.mount_storage(['/proxy'], storage)
    assert treewalk.walk_all(env.mnt_dir / 'proxy') == [
        'dir1/',
        'dir1/file1',
        'dir2/',
    ]

    assert Path(env.mnt_dir / 'proxy/dir1/file1').read_text() == \
        'file 1'

    assert Path(env.mnt_dir / 'proxy/dir1/file1').stat().st_mtime == \
        datetime(2010, 5, 7, 10, 30).timestamp()

    (env.mnt_dir / 'proxy/dir3/dir4').mkdir(parents=True)
    (env.mnt_dir / 'proxy/dir3/dir4/file2').write_text('file 2')

    assert Path(data_dir / 'dir3/dir4/file2').read_text() == \
        'file 2'


def test_delegate_fuse_subdir(env, storage_subdir, data_dir):
    (data_dir / 'dir1').mkdir()
    (data_dir / 'dir1/file1').write_text('file 1')
    os.utime(data_dir / 'dir1/file1',
             (int(datetime(2010, 5, 7, 10, 30).timestamp()),
              int(datetime(2010, 5, 7, 10, 30).timestamp())))

    # Empty directory
    (data_dir / 'dir1/dir2').mkdir()

    env.mount_storage(['/proxy'], storage_subdir)
    assert treewalk.walk_all(env.mnt_dir / 'proxy') == [
        'dir2/',
        'file1',
    ]

    assert Path(env.mnt_dir / 'proxy/file1').read_text() == \
        'file 1'

    assert Path(env.mnt_dir / 'proxy/file1').stat().st_mtime == \
        datetime(2010, 5, 7, 10, 30).timestamp()

    with pytest.raises(FileNotFoundError):
        Path(env.mnt_dir / 'proxy/dir1/file1').read_text()

    (env.mnt_dir / 'proxy/dir3/dir4').mkdir(parents=True)
    (env.mnt_dir / 'proxy/dir3/dir4/file2').write_text('file 2')

    assert Path(data_dir / 'dir1/dir3/dir4/file2').read_text() == \
        'file 2'
