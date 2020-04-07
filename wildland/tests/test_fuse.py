import os
import stat
import errno

import pytest

from .fuse_env import FuseEnv
from ..manifest import Manifest
from ..sig import DummySigContext

# For Pytest fixtures
# pylint: disable=redefined-outer-name

TEST_UUID = '85ab42ce-c087-4c80-8bf1-197b44235287'
TEST_UUID_2 = 'd8d3ed8a-75a6-11ea-b5d2-00163e5e6c00'


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
        'uuid': TEST_UUID,
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
    })

    env.create_dir('./storage/storage1/')


def test_list(env):
    assert sorted(os.listdir(env.mnt_dir)) == [
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
    assert text.splitlines() == [f'/container1 {TEST_UUID}']


def test_control_containers(env):
    containers_dir = env.mnt_dir / '.control/containers'
    assert sorted(os.listdir(containers_dir)) == [
        TEST_UUID
    ]

    with open(containers_dir / TEST_UUID / 'manifest.yaml') as f:
        manifest_content = f.read()
    assert 'signer: "signer"' in manifest_content
    assert '/container1' in manifest_content


def test_control_storage(env):
    storage_dir = (env.mnt_dir / '.control/containers' /
                    TEST_UUID / 'storage')
    assert sorted(os.listdir(storage_dir)) == ['0']

    with open(storage_dir / '0/manifest.yaml') as f:
        manifest_content = f.read()
    assert 'signer: "signer"' in manifest_content
    assert '/storage1' in manifest_content


def cmd(env, data):
    with open(env.mnt_dir / '.control/cmd', 'w') as f:
        f.write(data)


def container_manifest(*, signer='signer',
                       ident=TEST_UUID_2, paths=None, storage=None):
    if paths is None:
        paths = ['/container2']
    if storage is None:
        storage = ['storage1.yaml']

    return {
        'signer': signer,
        'uuid': ident,
        'paths': paths,
        'backends': {
            'storage': storage
        }
    }


def storage_manifest(*, signer='signer', path):
    return {
        'signer': signer,
        'type': 'local',
        'path': path,
    }


def test_cmd_mount(env):
    env.create_manifest('manifest2.yaml', container_manifest())
    cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == [
        TEST_UUID,
        TEST_UUID_2,
    ]
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]


def test_cmd_mount_direct(env):
    manifest = Manifest.from_fields(container_manifest(storage=[
        str(env.test_dir / 'storage1.yaml')
    ]), DummySigContext())
    with open(env.mnt_dir / '.control/mount', 'wb') as f:
        f.write(manifest.to_bytes())
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == [
        TEST_UUID,
        TEST_UUID_2,
    ]
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]


def test_cmd_mount_error(env):
    env.create_manifest('manifest2.yaml', container_manifest(ident=TEST_UUID))
    with pytest.raises(IOError) as e:
        cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert e.value.errno == errno.EINVAL

    env.create_manifest('manifest3.yaml', container_manifest(paths=['/container1']))
    with pytest.raises(IOError) as e:
        cmd(env, 'mount ' + str(env.test_dir / 'manifest3.yaml'))
    assert e.value.errno == errno.EINVAL


def test_cmd_unmount(env):
    cmd(env, 'unmount ' + TEST_UUID)
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == []
    assert sorted(os.listdir(env.mnt_dir)) == ['.control']


def test_cmd_unmount_error(env):
    with pytest.raises(IOError) as e:
        cmd(env, 'unmount ' + TEST_UUID_2)
    assert e.value.errno == errno.EINVAL

    with pytest.raises(IOError) as e:
        cmd(env, 'unmount XXX')
    assert e.value.errno == errno.EINVAL


def test_mount_no_directory(env):
    # Mount should still work if them backing directory does not exist
    env.create_manifest(
        'manifest2.yaml', container_manifest(storage=['storage2.yaml']))

    env.create_manifest(
        'storage2.yaml', storage_manifest(path='./storage/storage2'))

    # The container should mount, with the directory visible but empty
    cmd(env, 'mount ' + str(env.test_dir / 'manifest2.yaml'))
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.control',
        'container1',
        'container2',
    ]
    assert os.listdir(env.mnt_dir / 'container2') == []

    # It's not possible to create a file...
    with pytest.raises(IOError):
        open(env.mnt_dir / 'container2/file1', 'w')

    # ... until you create the backing directory
    os.mkdir(env.test_dir / 'storage/storage2')
    with open(env.mnt_dir / 'container2/file1', 'w') as f:
        f.write('hello world')
    os.sync()

    with open(env.test_dir / 'storage/storage2/file1') as f:
        assert f.read() == 'hello world'
