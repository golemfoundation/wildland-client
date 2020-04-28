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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument

import os
import stat
import errno
import shutil
import subprocess
import json

import pytest

from .fuse_env import FuseEnv


@pytest.fixture
def env():
    env = FuseEnv()
    try:
        env.mount()
        yield env
    finally:
        env.destroy()



@pytest.fixture(params=['local', 'local-cached'])
def storage_type(request):
    '''
    Parametrize the tests by storage type
    '''

    return request.param


@pytest.fixture
def container(env, storage_type):
    env.create_dir('storage/storage1')
    env.mount_storage(['/container1'], {
        'type': storage_type,
        'signer': '0x3333',
        'path': str(env.test_dir / 'storage/storage1'),
        'container_path': '/container1',
    })
    return 'container1'


def test_list(env, container):
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        container
    ]


def test_list_contains_dots(env, container):
    # Python's directory list functions filter out '.' and '..', so we use ls.
    ls_output = subprocess.check_output(['ls', '-a', env.mnt_dir])
    assert sorted(ls_output.decode().split()) == [
        '.',
        '..',
        '.control',
        container,
    ]


def test_list_not_found(env):
    with pytest.raises(FileNotFoundError):
        os.listdir(env.mnt_dir / 'nonexistent')


def test_stat_dir(env):
    st = os.stat(env.mnt_dir)
    assert st.st_mode == 0o755 | stat.S_IFDIR


def test_stat_not_found(env):
    with pytest.raises(FileNotFoundError):
        os.stat(env.mnt_dir / 'nonexistent')


def test_container_list(env, container):
    env.create_file('storage/storage1/file1')
    env.create_file('storage/storage1/file2')
    env.refresh_storage(1)
    assert sorted(os.listdir(env.mnt_dir / container)) == ['file1', 'file2']


def test_container_stat_file(env, container):
    env.create_file('storage/storage1/file1', mode=0o644)
    env.refresh_storage(1)
    st = os.stat(env.mnt_dir / container / 'file1')
    assert st.st_mode == 0o644 | stat.S_IFREG


def test_container_read_file(env, container):
    env.create_file('storage/storage1/file1', 'hello world')
    env.refresh_storage(1)
    with open(env.mnt_dir / container / 'file1', 'r') as f:
        content = f.read()
    assert content == 'hello world'


def test_container_create_file(env, container):
    with open(env.mnt_dir / container / 'file1', 'w') as f:
        f.write('hello world')
    env.refresh_storage(1)
    with open(env.test_dir / 'storage/storage1/file1', 'r') as f:
        content = f.read()
    assert content == 'hello world'


def test_container_delete_file(env, container):
    env.create_file('storage/storage1/file1', 'hello world')
    env.refresh_storage(1)
    os.unlink(env.mnt_dir / container / 'file1')
    assert not (env.mnt_dir / container / 'file1').exists()
    assert not (env.test_dir / 'storage/storage1/file1').exists()


def test_container_mkdir_rmdir(env, container):
    dirpath = env.mnt_dir / container / 'directory'

    os.mkdir(dirpath, 0o755)
    assert os.stat(dirpath).st_mode == 0o755 | stat.S_IFDIR

    os.rmdir(dirpath)
    with pytest.raises(FileNotFoundError):
        os.stat(dirpath)


def test_control_paths(env, container):
    text = (env.mnt_dir / '.control/paths').read_text()
    assert json.loads(text) == {
        '/.control': 0,
        '/' + container: 1,
    }


def test_control_storage(env, container):
    storage_dir = env.mnt_dir / '.control/storage'
    assert sorted(os.listdir(storage_dir)) == ['0', '1']

    with open(storage_dir / '1/manifest.yaml') as f:
        manifest_content = f.read()
    assert "signer: '0x3333'" in manifest_content
    assert '/storage1' in manifest_content


def storage_manifest(env, path, storage_type, read_only=False):
    return {
        'signer': '0x3333',
        'type': storage_type,
        'path': str(env.test_dir / path),
        'read_only': read_only,
    }


def test_cmd_mount(env, container, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type)
    env.mount_storage(['/container2'], storage)
    assert sorted(os.listdir(env.mnt_dir / '.control/storage')) == [
        '0', '1', '2'
    ]
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]


def test_cmd_mount_path_collision(env, container, storage_type):
    storage = storage_manifest(env, 'storage2.yaml', storage_type)
    env.mount_storage(['/container2'], storage)
    with pytest.raises(IOError) as e:
        env.mount_storage(['/container2'], storage)
    assert e.value.errno == errno.EINVAL


def test_cmd_unmount(env, container):
    env.unmount_storage(1)
    assert sorted(os.listdir(env.mnt_dir / '.control/storage')) == ['0']
    assert sorted(os.listdir(env.mnt_dir)) == ['.control']


def test_cmd_unmount_error(env, container):
    with pytest.raises(IOError) as e:
        env.unmount_storage(2)
    assert e.value.errno == errno.EINVAL

    with pytest.raises(IOError) as e:
        env.unmount_storage('XXX')
    assert e.value.errno == errno.EINVAL


def test_mount_no_directory(env, container, storage_type):
    # Mount should still work if them backing directory does not exist
    storage = storage_manifest(env, 'storage/storage2', storage_type)

    # The container should mount, with the directory visible but empty
    env.mount_storage(['/container2'], storage)
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]

    # It's not possible to list the directory, or create a file...
    with pytest.raises(IOError):
        os.listdir(env.mnt_dir / 'container2')
    with pytest.raises(IOError):
        open(env.mnt_dir / 'container2/file1', 'w')

    # ... until you create the backing directory
    os.mkdir(env.test_dir / 'storage/storage2')
    env.refresh_storage(2)
    with open(env.mnt_dir / 'container2/file1', 'w') as f:
        f.write('hello world')
    os.sync()

    with open(env.test_dir / 'storage/storage2/file1') as f:
        assert f.read() == 'hello world'


def test_nested_mounts(env, storage_type):
    # Test setup:
    #
    # CONTAINER 1            CONTAINER 2
    #
    # /container1
    #   file-c1
    #   nested1/             nested1/ (shadows container 1)
    #     file-c1-nested       file-c2-nested
    #                        nested2/
    #                          file-c2-nested

    env.create_dir('storage/storage1')
    env.create_file('storage/storage1/file-c1')
    env.create_dir('storage/storage1/nested1')
    env.create_file('storage/storage1/nested1/file-c1-nested')

    env.create_dir('storage/storage2/')
    env.create_file('storage/storage2/file-c2-nested')

    storage1 = storage_manifest(env, 'storage/storage1', storage_type)
    storage2 = storage_manifest(env, 'storage/storage2', storage_type)

    env.mount_storage(['/container1'], storage1)

    # Before mounting container2:
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'file-c1',
        'nested1',
    ]
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested1')) == [
        'file-c1-nested',
    ]


    # Mount container2: nested1 and nested2 should be shadowed
    env.mount_storage(['/container1/nested1', '/container1/nested2'], storage2)
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'file-c1',
        'nested1',
        'nested2',
    ]
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested1')) == [
        'file-c2-nested',
    ]
    assert os.path.isdir(env.mnt_dir / 'container1/nested2')
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested2')) == [
        'file-c2-nested',
    ]

    # Delete backing storage of container1: we can only see the mounts
    shutil.rmtree(env.test_dir / 'storage/storage1')
    env.refresh_storage(1)
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'nested1',
        'nested2',
    ]

    # Unmount container1
    env.unmount_storage(1)
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'nested1',
        'nested2',
    ]

def test_read_only(env, storage_type):
    env.create_dir('storage/storage1')
    env.create_file('storage/storage1/file')
    env.create_dir('storage/storage1/dir')

    storage1 = storage_manifest(env, 'storage/storage1', storage_type,
                                read_only=True)
    env.mount_storage(['/container1/'], storage1)

    st = os.lstat(env.mnt_dir / 'container1/file')
    assert st.st_mode & 0o222 == 0

    st = os.lstat(env.mnt_dir / 'container1/dir')
    assert st.st_mode & 0o222 == 0

    with pytest.raises(OSError):
        os.unlink(env.mnt_dir / 'container1/file')
    with pytest.raises(OSError):
        os.truncate(env.mnt_dir / 'container1/file', 0)
    with pytest.raises(OSError):
        open(env.mnt_dir / 'container1/file', 'w')
    with pytest.raises(OSError):
        open(env.mnt_dir / 'container1/file-new', 'w')
    with pytest.raises(OSError):
        os.mkdir(env.mnt_dir / 'container1/dir-new')
    with pytest.raises(OSError):
        os.rmdir(env.mnt_dir / 'container1/dir')
