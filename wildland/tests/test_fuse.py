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

import errno
import os
import stat
import subprocess
import time
import socket
import uuid

import pytest

from .fuse_env import FuseEnv, FuseError

@pytest.fixture
def env():
    env = FuseEnv()
    try:
        env.mount()
        yield env
    finally:
        env.destroy()


@pytest.fixture(params=['local', 'local-cached', 'local-dir-cached'])
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
        'owner': '0x3333',
        'is-local-owner': True,
        'location': str(env.test_dir / 'storage/storage1'),
        'container_path': '/container1',
        'backend-id': str(uuid.uuid4()),
    })
    return 'container1'


def test_list(env, container):
    assert sorted(os.listdir(env.mnt_dir)) == [
        container
    ]


def test_list_contains_dots(env, container):
    # Python's directory list functions filter out '.' and '..', so we use ls.
    ls_output = subprocess.check_output(['ls', '-a', env.mnt_dir])
    assert sorted(ls_output.decode().split()) == [
        '.',
        '..',
        container,
    ]


def test_list_not_found(env):
    with pytest.raises(FileNotFoundError):
        os.listdir(env.mnt_dir / 'nonexistent')


def test_stat_dir(env):
    st = os.stat(env.mnt_dir)
    assert st.st_mode == 0o555 | stat.S_IFDIR


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

def test_cmd_paths(env, container):
    assert env.run_control_command('paths') == {
        '/' + container: [1],
    }


def test_cmd_info(env, container, storage_type):
    assert env.run_control_command('info') == {
        '1': {
            'paths': ['/container1'],
            'type': storage_type,
            'extra': {},
        },
    }

def storage_manifest(env, path, storage_type, read_only=False, is_local_owner=True):
    return {
        'owner': '0x3333',
        'is-local-owner': is_local_owner,
        'type': storage_type,
        'location': str(env.test_dir / path),
        'read-only': read_only,
        'backend-id': str(uuid.uuid4())
    }

def test_cmd_test(env):
    assert env.run_control_command('test', {'foo': 'bar'}) == {'kwargs': {'foo': 'bar'}}


def test_cmd_mount(env, container, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type)
    env.mount_storage(['/container2'], storage)
    assert sorted(os.listdir(env.mnt_dir)) == [
        'container1',
        'container2',
    ]

def test_cmd_mount_already_mounted(env, container, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type)
    env.mount_storage(['/.uuid/XYZ', '/container2'], storage)
    with pytest.raises(FuseError):
        env.mount_storage(['/.uuid/XYZ', '/container3'], storage)


def test_cmd_mount_not_local_owner(env, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type, is_local_owner=False)
    with pytest.raises(FuseError):
        env.mount_storage(['/.uuid/XYZ', '/container2'], storage)


def test_cmd_mount_owner_file(env, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type, is_local_owner=False)
    (env.test_dir / 'storage/storage2').mkdir(parents=True)
    (env.test_dir / 'storage/storage2' / '.wildland-owners').write_bytes(b'0x3333\n')
    env.mount_storage(['/.uuid/XYZ', '/container2'], storage)
    assert os.listdir(env.mnt_dir) == ['.uuid', 'container2']


def test_cmd_mount_owner_file_parent(env, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type, is_local_owner=False)
    (env.test_dir / '.wildland-owners').write_bytes(b'0x3333\n')
    env.mount_storage(['/.uuid/XYZ', '/container2'], storage)
    assert os.listdir(env.mnt_dir) == ['.uuid', 'container2']


def test_cmd_mount_remount(env, container, storage_type):
    storage = storage_manifest(env, 'storage/storage2', storage_type)
    env.mount_storage(['/.uuid/XYZ', '/container2'], storage)

    storage = storage_manifest(env, 'storage/storage3', storage_type)
    env.mount_storage(['/.uuid/XYZ', '/container3'], storage, remount=True)
    assert sorted(os.listdir(env.mnt_dir)) == [
        '.uuid',
        'container1',
        'container3',
    ]


def test_cmd_unmount(env, container):
    env.unmount_storage(1)
    assert sorted(os.listdir(env.mnt_dir)) == []


def test_cmd_unmount_error(env, container):
    with pytest.raises(FuseError):
        env.unmount_storage(2)

    with pytest.raises(FuseError):
        env.unmount_storage('XXX')


def test_mount_no_directory(env, container, storage_type):
    # Mount should still work if them backing directory does not exist
    storage = storage_manifest(env, 'storage/storage2', storage_type)

    # The container should mount, with the directory visible but empty
    env.mount_storage(['/container2'], storage)
    assert sorted(os.listdir(env.mnt_dir)) == [
        'container1',
        'container2',
    ]

    # In case of the local backend, you can't list the mount directory.
    # The other (cached) backends will generate a synthetic one.
    if storage_type == 'local':
        with pytest.raises(IOError):
            os.listdir(env.mnt_dir / 'container2')
    else:
        os.listdir(env.mnt_dir / 'container2')

    # It's not possible to create a file.
    with pytest.raises(IOError):
        open(env.mnt_dir / 'container2/file1', 'w')

    # After creating the backing directory, you can list the mount directory
    # and create aa file
    os.mkdir(env.test_dir / 'storage/storage2')
    env.refresh_storage(1)
    with open(env.mnt_dir / 'container2/file1', 'w') as f:
        f.write('hello world')
    os.sync()
    time.sleep(1)

    with open(env.test_dir / 'storage/storage2/file1') as f:
        assert f.read() == 'hello world'


def test_nested_mounts(env, storage_type):
    '''
    This is an integration test for conflict resolution.
    See also test_conflict.py for detailed unit tests.

    Test setup:

    CONTAINER 1            CONTAINER 2

    /container1
      file-c1
      nested1/             nested1/ (merges with container 1)
        file-conflict        file-conflict
        file-c1-nested       file-c2-nested
                           nested2/
                             file-conflict
                             file-c2-nested
    '''

    env.create_dir('storage/storage1')
    env.create_file('storage/storage1/file-c1')
    env.create_dir('storage/storage1/nested1')
    env.create_file('storage/storage1/nested1/file-c1-nested')
    env.create_file('storage/storage1/nested1/file-conflict', content='c1')

    env.create_dir('storage/storage2/')
    env.create_file('storage/storage2/file-conflict', content='c2')
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
        'file-conflict',
    ]


    # Mount container2
    env.mount_storage(['/container1/nested1', '/container1/nested2'], storage2)
    assert sorted(os.listdir(env.mnt_dir / 'container1')) == [
        'file-c1',
        'nested1',
        'nested2',
    ]
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested1')) == [
        'file-c1-nested',
        'file-c2-nested',
        'file-conflict.wl.1',
        'file-conflict.wl.2',
    ]
    assert os.path.isdir(env.mnt_dir / 'container1/nested2')
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested2')) == [
        'file-c2-nested',
        'file-conflict',
    ]

    # I should be able to read and write to conflicted files
    path1 = env.mnt_dir / 'container1/nested1/file-conflict.wl.1'
    with open(path1) as f:
        assert f.read() == 'c1'
    with open(path1, 'w') as f:
        f.write('new content')
    with open(env.test_dir / 'storage/storage1/nested1/file-conflict') as f:
        assert f.read() == 'new content'

    # I shouldn't be able to remove the file, or create a new one
    with pytest.raises(PermissionError):
        os.unlink(path1)
    with pytest.raises(PermissionError):
        open(env.mnt_dir / 'container1/nested1/new-file', 'w')

    # However, I can create a file under the second mount path...
    with open(env.mnt_dir / 'container1/nested2/file-c1-nested', 'w'):
        pass
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested2')) == [
        'file-c1-nested',
        'file-c2-nested',
        'file-conflict',
    ]

    # ...and that will cause a conflict and rename under the first path
    assert sorted(os.listdir(env.mnt_dir / 'container1/nested1')) == [
        'file-c1-nested.wl.1',
        'file-c1-nested.wl.2',
        'file-c2-nested',
        'file-conflict.wl.1',
        'file-conflict.wl.2',
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


# Test the paging while reading a file.
def test_read_buffered(env, storage_type):
    data = bytes(range(256))
    env.create_dir('storage/storage1')
    env.create_file('storage/storage1/big_file', data)
    storage1 = storage_manifest(env, 'storage/storage1', storage_type)
    env.mount_storage(['/container1/'], storage1)

    with open(env.mnt_dir / 'container1/big_file', 'rb', buffering=0) as f:
        assert f.read(5) == b'\x00\x01\x02\x03\x04'

        f.seek(0x7f)
        assert f.read(5) == b'\x7f\x80\x81\x82\x83'

        f.seek(0)
        assert f.read() == data

# Watches

def collect_all_events(environment):
    events = []
    while True:
        try:
            events.extend(environment.recv_event())
        except socket.timeout:
            break

    return events


def test_watch(env, storage_type):
    env.create_dir('storage/storage1')
    storage1 = storage_manifest(env, 'storage/storage1', storage_type)
    env.mount_storage(['/container1/'], storage1)

    watch_id = env.run_control_command(
        'add-watch', {'storage-id': 1, 'pattern': '*.txt'})

    # Create a new file (generates a 'create' event)

    with open(env.mnt_dir / 'container1/file1.txt', 'w'):
        pass

    event = collect_all_events(env)
    expected_event = [{
        'type': 'create',
        'path': 'file1.txt',
        'storage-id': 1,
        'watch-id': watch_id},
        {'type': 'modify',
         'path': 'file1.txt',
         'storage-id': 1,
         'watch-id': watch_id}]

    assert event == expected_event

    # Append to file (generates a 'modify' event after close)

    with open(env.mnt_dir / 'container1/file1.txt', 'a') as f:
        f.write('hello')

    event = env.recv_event()
    assert event == [{
        'type': 'modify',
        'path': 'file1.txt',
        'storage-id': 1,
        'watch-id': watch_id,
    }]

    # Delete file (generates a 'delete' event)

    os.unlink(env.mnt_dir / 'container1/file1.txt')
    event = env.recv_event()
    assert event == [{
        'type': 'delete',
        'path': 'file1.txt',
        'storage-id': 1,
        'watch-id': watch_id,
    }]

# Local storage watcher

@pytest.fixture
def local_env(env):
    env.create_dir('storage/storage1')
    storage1 = storage_manifest(env, 'storage/storage1', "local")
    env.mount_storage(['/container1/'], storage1)

    return env


def test_watch_local_file(local_env):
    watch_id = local_env.run_control_command('add-watch', {'storage-id': 1, 'pattern': '*.txt'})

    # Create a new file (generates a 'create' event and a 'modify' event)

    with open(local_env.test_dir / 'storage/storage1/file1.txt', 'w'):
        pass
    event = collect_all_events(local_env)
    assert event == [{'type': 'create', 'path': 'file1.txt',
                      'storage-id': 1, 'watch-id': watch_id},
                     {'type': 'modify', 'path': 'file1.txt',
                      'storage-id': 1, 'watch-id': watch_id}]

    # Append to file (generates a 'modify' event after close)

    with open(local_env.test_dir / 'storage/storage1/file1.txt', 'a') as f:
        f.write('hello')
    event = local_env.recv_event()
    assert event == [{'type': 'modify', 'path': 'file1.txt',
                      'storage-id': 1, 'watch-id': watch_id}]

    # Delete file (generates a 'delete' event)

    os.unlink(local_env.test_dir / 'storage/storage1/file1.txt')
    event = local_env.recv_event()
    assert event == [{'type': 'delete', 'path': 'file1.txt',
                      'storage-id': 1, 'watch-id': watch_id}]


def test_watch_local_dir(local_env):
    watch_id = local_env.run_control_command('add-watch', {'storage-id': 1, 'pattern': '*'})

    os.mkdir(local_env.test_dir / 'storage/storage1/dir1')

    event = local_env.recv_event()
    assert event == [{'type': 'create', 'path': 'dir1',
                      'storage-id': 1, 'watch-id': watch_id}]

    with open(local_env.test_dir / 'storage/storage1/dir1/file1.txt', 'w'):
        pass

    event = collect_all_events(local_env)
    assert event == [{'type': 'create', 'path': 'dir1/file1.txt',
                      'storage-id': 1, 'watch-id': watch_id},
                     {'type': 'modify', 'path': 'dir1/file1.txt',
                      'storage-id': 1, 'watch-id': watch_id}]

    os.rename(local_env.test_dir / 'storage/storage1/dir1',
              local_env.test_dir / 'storage/storage1/dir2')

    event = collect_all_events(local_env)
    assert event == [{'type': 'delete', 'path': 'dir1',
                      'storage-id': 1, 'watch-id': watch_id},
                     {'type': 'create', 'path': 'dir2',
                      'storage-id': 1, 'watch-id': watch_id}]

    with open(local_env.test_dir / 'storage/storage1/dir2/file3.txt', 'w'):
        pass

    event = collect_all_events(local_env)
    assert event == [{'type': 'create', 'path': 'dir2/file3.txt',
                      'storage-id': 1, 'watch-id': watch_id},
                     {'type': 'modify', 'path': 'dir2/file3.txt',
                      'storage-id': 1, 'watch-id': watch_id}]

    os.remove(local_env.test_dir / 'storage/storage1/dir2/file1.txt')
    os.remove(local_env.test_dir / 'storage/storage1/dir2/file3.txt')

    event = collect_all_events(local_env)
    assert event == [{'type': 'delete', 'path': 'dir2/file1.txt',
                      'storage-id': 1, 'watch-id': watch_id},
                     {'type': 'delete', 'path': 'dir2/file3.txt',
                      'storage-id': 1, 'watch-id': watch_id}]

    os.rmdir(local_env.test_dir / 'storage/storage1/dir2')
    event = local_env.recv_event()
    assert event == [{'type': 'delete', 'path': 'dir2',
                      'storage-id': 1, 'watch-id': watch_id}]


def test_container_rename_file_in_same_directory(env, container):
    env.create_file('storage/storage1/foo', 'hello world')
    os.rename(env.mnt_dir / 'container1/foo', env.mnt_dir / 'container1/bar')

    with open(env.mnt_dir / container / 'bar', 'r') as f:
        content = f.read()

    assert content == 'hello world'


def test_container_rename_file_in_different_directory(env, container):
    env.create_dir('storage/storage1/subdir')
    env.create_file('storage/storage1/foo', 'hello world')
    os.rename(env.mnt_dir / 'container1/foo', env.mnt_dir / 'container1/subdir/bar')

    with open(env.mnt_dir / container / 'subdir/bar', 'r') as f:
        content = f.read()

    assert content == 'hello world'


def test_container_rename_empty_directory(env, container):
    env.create_dir('storage/storage1/foodir')
    os.rename(env.mnt_dir / 'container1/foodir', env.mnt_dir / 'container1/bardir')

    assert not (env.mnt_dir / container / 'foodir').exists()
    assert (env.mnt_dir / container / 'bardir').exists()


def test_container_rename_directory_with_files(env, container):
    env.create_dir('storage/storage1/foodir')
    env.create_file('storage/storage1/foodir/foo', 'hello world')
    os.rename(env.mnt_dir / 'container1/foodir', env.mnt_dir / 'container1/bardir')

    assert not (env.mnt_dir / container / 'foodir').exists()
    assert (env.mnt_dir / container / 'bardir').exists()

    with open(env.mnt_dir / container / 'bardir/foo', 'r') as f:
        content = f.read()

    assert content == 'hello world'


def test_container_rename_cross_storage_both_mounted(env, container):
    storage = storage_manifest(env, 'storage/storage2', 'local')
    env.create_dir('storage/storage2')
    env.mount_storage(['/container2'], storage)

    env.create_file('storage/storage1/file1')

    with pytest.raises(OSError) as err:
        os.rename(env.mnt_dir / 'container1/file1', env.mnt_dir / 'container2/file1')

    assert err.value.errno == errno.EXDEV
