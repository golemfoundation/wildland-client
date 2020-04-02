import os
import stat

import pytest

from .fuse_env import FuseEnv

# For Pytest fixtures
# pylint: disable=redefined-outer-name, missing-function-docstring, invalid-name


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
    assert text.splitlines() == ['/.control 0', '/container1 1']


def test_control_containers(env):
    assert sorted(os.listdir(env.mnt_dir / '.control/containers')) == ['0', '1']


def test_control_cmd(env):
    # For now, just check if we can write without errors
    with open(env.mnt_dir / '.control/cmd', 'w') as f:
        f.write('test')
