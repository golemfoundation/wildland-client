import os
import stat

import pytest

from .fuse_env import FuseEnv

# For Pytest fixtures
# pylint: disable=redefined-outer-name


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
