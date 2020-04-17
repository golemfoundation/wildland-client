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

import os
import stat
import errno
import shutil
import subprocess

import pytest

from .fuse_env import FuseEnv
from ..manifest.manifest import Manifest
from ..manifest.sig import DummySigContext


@pytest.fixture
def env():
    env = FuseEnv()
    try:
        create_test_data(env)
        env.mount(['manifest1.yaml'])
        yield env
    finally:
        env.destroy()


def create_test_data(env):
    # TODO: instead of creating a single fixture, we should define them on the
    # fly.
    env.create_manifest('manifest1.yaml', {
        'paths': ['/container1'],
        'backends': {
            'storage': [
                'storage1.yaml',
            ]
        }
    })

    env.create_manifest('storage1.yaml', {
        'type': 'local',
        'path': './storage/storage1',
        'container_path': '/container1',
    })

    env.create_dir('./storage/storage1/')


def test_list(env):
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
    ]


def test_list_contains_dots(env):
    # Python's directory list functions filter out '.' and '..', so we use ls.
    ls_output = subprocess.check_output(['ls', '-a', env.mnt_dir])
    assert sorted(ls_output.decode().split()) == [
        '.',
        '..',
        '.control',
        'container1',
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


def test_container_list(env):
    env.create_file('storage/storage1/file1')
    env.create_file('storage/storage1/file2')
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == ['file1', 'file2']


def test_container_stat_file(env):
    env.create_file('storage/storage1/file1', mode=0o644)
    st = os.stat(env.mnt_dir / 'container1/file1')
    assert st.st_mode == 0o644 | stat.S_IFREG


def test_container_read_file(env):
    env.create_file('storage/storage1/file1', 'hello world')
    with open(env.mnt_dir / 'container1/file1', 'r') as f:
        content = f.read()
    assert content == 'hello world'


def test_container_create_file(env):
    with open(env.mnt_dir / 'container1/file1', 'w') as f:
        f.write('hello world')
    os.sync()
    with open(env.test_dir / 'storage/storage1/file1', 'r') as f:
        content = f.read()
    assert content == 'hello world'


def test_container_delete_file(env):
    env.create_file('storage/storage1/file1', 'hello world')
    os.unlink(env.mnt_dir / 'container1/file1')
    assert not (env.test_dir / 'storage/storage1/file1').exists()


def test_control_paths(env):
    text = (env.mnt_dir / '.control/paths').read_text()
    assert text.splitlines() == [f'/container1 0']


def test_control_containers(env):
    containers_dir = env.mnt_dir / '.control/containers'
    assert sorted(os.listdir(containers_dir)) == ['0']

    with open(containers_dir / '0/manifest.yaml') as f:
        manifest_content = f.read()
    assert "signer: '0x3333'" in manifest_content
    assert '/container1' in manifest_content


def test_control_storage(env):
    storage_dir = env.mnt_dir / '.control/containers/0/storage'
    assert sorted(os.listdir(storage_dir)) == ['0']

    with open(storage_dir / '0/manifest.yaml') as f:
        manifest_content = f.read()
    assert "signer: '0x3333'" in manifest_content
    assert '/storage1' in manifest_content


def cmd(env, data):
    with open(env.mnt_dir / '.control/cmd', 'w') as f:
        f.write(data)


def container_manifest(*, signer='0x3333',
                       paths=None, storage=None):
    if paths is None:
        paths = ['/container2']
    if storage is None:
        storage = ['storage2.yaml']

    return {
        'signer': signer,
        'paths': paths,
        'backends': {
            'storage': storage
        }
    }


def storage_manifest(*, signer='0x3333', path, container_path='/container2'):
    return {
        'signer': signer,
        'type': 'local',
        'container_path': container_path,
        'path': path,
    }


def test_cmd_mount(env):
    env.create_manifest('storage2.yaml', storage_manifest(
        path='./storage/storage2'))
    env.create_manifest('manifest2.yaml', container_manifest())
    cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == [
        '0', '1'
    ]
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]


def test_cmd_mount_direct(env):
    env.create_manifest('storage2.yaml', storage_manifest(
        path='./storage/storage2'))
    manifest = Manifest.from_fields(container_manifest(storage=[
        # Absolute path
        str(env.test_dir / 'storage2.yaml')
    ]))
    manifest.sign(DummySigContext())
    with open(env.mnt_dir / '.control/mount', 'wb') as f:
        f.write(manifest.to_bytes())
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == [
        '0', '1'
    ]
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]


def test_cmd_mount_path_collision(env):
    env.create_manifest('manifest3.yaml', container_manifest(paths=['/container1']))
    with pytest.raises(IOError) as e:
        cmd(env, 'mount ' + str(env.test_dir / 'manifest3.yaml'))
    assert e.value.errno == errno.EINVAL


def test_cmd_mount_signer_mismatch(env):
    env.create_manifest('storage2.yaml', storage_manifest(
        signer='0x4444',
        path='./storage/storage2',
        container_path='/container2'))
    env.create_manifest('manifest2.yaml', container_manifest(
        signer='0x3333', paths=['/container2'],
        storage=['storage2.yaml']))
    with pytest.raises(IOError) as e:
        cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert e.value.errno == errno.EINVAL


def test_cmd_mount_container_path_mismatch(env):
    env.create_manifest('storage2.yaml', storage_manifest(
        signer='0x3333',
        path='./storage/storage2',
        container_path='/container3'))
    env.create_manifest('manifest2.yaml', container_manifest(
        signer='0x3333', paths=['/container2'],
        storage=['storage2.yaml']))
    with pytest.raises(IOError) as e:
        cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert e.value.errno == errno.EINVAL


def test_cmd_unmount(env):
    cmd(env, 'unmount 0')
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == []
    assert sorted(os.listdir(env.mnt_dir)) == ['.control']


def test_cmd_unmount_error(env):
    with pytest.raises(IOError) as e:
        cmd(env, 'unmount 1')
    assert e.value.errno == errno.EINVAL

    with pytest.raises(IOError) as e:
        cmd(env, 'unmount XXX')
    assert e.value.errno == errno.EINVAL


def test_mount_no_directory(env):
    # Mount should still work if them backing directory does not exist
    env.create_manifest(
        'manifest2.yaml', container_manifest(storage=['storage2.yaml']))

    env.create_manifest(
        'storage2.yaml', storage_manifest(path='./storage/storage2',
                                          container_path='/container2'))

    # The container should mount, with the directory visible but empty
    cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]

    # It's not possible to list the directory, or create a file...
    with pytest.raises(IOError):
        assert os.listdir(env.mnt_dir / 'container2') == []
    with pytest.raises(IOError):
        open(env.mnt_dir / 'container2/file1', 'w')

    # ... until you create the backing directory
    os.mkdir(env.test_dir / 'storage/storage2')
    with open(env.mnt_dir / 'container2/file1', 'w') as f:
        f.write('hello world')
    os.sync()

    with open(env.test_dir / 'storage/storage2/file1') as f:
        assert f.read() == 'hello world'


def test_nested_mounts(env):
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

    env.create_file('storage/storage1/file-c1')
    env.create_dir('storage/storage1/nested1')
    env.create_file('storage/storage1/nested1/file-c1-nested')

    env.create_dir('storage/storage2/')
    env.create_file('storage/storage2/file-c2-nested')

    env.create_manifest(
        'storage2.yaml', storage_manifest(
            path='./storage/storage2',
            container_path='/container1/nested1',
        ))
    env.create_manifest(
        'manifest2.yaml', container_manifest(storage=['storage2.yaml'],
                                             paths=['/container1/nested1',
                                                    '/container1/nested2']))

    # Before mounting container2:
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'file-c1',
        'nested1',
    ]
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested1')) == [
        'file-c1-nested',
    ]


    # Mount container2: nested1 and nested2 should be shadowed
    cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
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
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'nested1',
        'nested2',
    ]

    # Unmount container1
    cmd(env, 'unmount 0')
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'nested1',
        'nested2',
    ]
