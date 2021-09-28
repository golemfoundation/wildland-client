# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument

import os
import shutil
import time
from typing import Callable
from pathlib import PurePosixPath, Path
from itertools import combinations, product

import pytest

from wildland.storage_sync.naive_sync import BLOCK_SIZE
from wildland.storage_sync.base import SyncConflict, BaseSyncer, SyncState, SyncEvent, \
    SyncStateEvent, SyncErrorEvent, SyncConflictEvent
from ..client import Client
from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.local_cached import LocalCachedStorageBackend, \
    LocalDirectoryCachedStorageBackend
from ..storage_backends.base import StorageBackend
from ..log import init_logging
from ..wildland_object.wildland_object import WildlandObject

MAX_TIMEOUT = 10

init_logging()


@pytest.fixture(params=[LocalStorageBackend, LocalCachedStorageBackend,
                        LocalDirectoryCachedStorageBackend])
def storage_backend(request) -> Callable:
    """
    Parametrize the tests by storage backend; at the moment include only those with watchers
    implemented.
    """

    return request.param


second_backend = storage_backend


@pytest.fixture
def cleanup():
    cleanup_functions = []

    def add_cleanup(func):
        cleanup_functions.append(func)

    yield add_cleanup

    for f in cleanup_functions:
        f()


def make_file(path, contents):
    with open(path, mode='w') as f:
        f.write(contents)


def read_file(path):
    with open(path, mode='r') as f:
        return f.read()


def make_storage(backend_class: Callable, target_dir: PurePosixPath):
    try:
        os.mkdir(target_dir)
    except FileExistsError:
        pass
    backend = backend_class(params={'location': str(target_dir),
                                    'owner': '0xaaa',
                                    'is-local-owner': True,
                                    'type': getattr(backend_class, 'TYPE'),
                                    'backend-id': str(backend_class) + str(target_dir)})
    return backend, target_dir


def make_syncer(storage1: StorageBackend, storage2: StorageBackend) -> BaseSyncer:
    return BaseSyncer.from_storages(storage1, storage2, 'test: ', False, False, True, False)


def wait_for_file(path: Path, contents=None, timeout=MAX_TIMEOUT) -> bool:
    counter = 0
    while counter < timeout:
        if path.exists():
            if contents:
                if path.read_text() == contents:
                    return True
            else:
                return True
        time.sleep(1)
        counter += 1
    return False


def wait_for_dir(path: Path, timeout=MAX_TIMEOUT) -> bool:
    counter = 0
    while counter < timeout:
        if path.exists() and path.is_dir():
            return True
        time.sleep(1)
        counter += 1
    return False


def wait_for_deletion(path: Path, timeout=MAX_TIMEOUT) -> bool:
    counter = 0
    while counter < timeout:
        if not path.exists():
            return True
        time.sleep(1)
        counter += 1
    return False


def do_correct_event(path: Path) -> bool:
    path.write_text('123456')
    return wait_for_file(path, '123456')


def test_sync_subdirs(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    dirs = [storage_dir1, storage_dir2]

    for d in dirs:
        make_file(d / 'testfile', 'abcd')
        os.mkdir(d / 'subdir')
        make_file(d / 'subdir/testfile2', 'efgh')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    make_file(storage_dir1 / 'testfile', '1234')

    assert wait_for_file(Path(storage_dir2 / 'testfile'), '1234')

    # Make a subdirectory and some data
    os.mkdir(storage_dir2 / 'subdir2')
    make_file(storage_dir2 / 'subdir2/testfile3', 'efgh')
    make_file(storage_dir2 / 'subdir2/testfile4', 'ijkl')

    assert wait_for_file(Path(storage_dir1 / 'subdir2/testfile3'), 'efgh')
    assert wait_for_file(Path(storage_dir1 / 'subdir2/testfile4'), 'ijkl')


def test_sync_large_file(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    data = '1234' * (BLOCK_SIZE * 4 + 5)

    make_file(storage_dir1 / 'testfile', data)

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    wait_for_file(Path(storage_dir2 / 'testfile'), data)


def test_sync_move_dir(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    os.mkdir(tmpdir / 'newdir')
    os.mkdir(tmpdir / 'newdir/subdir')
    make_file(tmpdir / 'newdir/testfile', 'abcd')
    make_file(tmpdir / 'newdir/subdir/testfile2', 'efgh')

    shutil.move(str(tmpdir / 'newdir'), str(storage_dir1))

    assert wait_for_file(Path(storage_dir2 / 'newdir/testfile'), 'abcd')
    assert wait_for_file(Path(storage_dir2 / 'newdir/subdir/testfile2'), 'efgh')

    make_file(storage_dir1 / 'newdir/subdir/testfile3', 'ijkl')

    assert wait_for_file(Path(storage_dir2 / 'newdir/subdir/testfile3'), 'ijkl')

    shutil.move(str(storage_dir2 / 'newdir'), str(storage_dir2 / 'moveddir'))

    assert wait_for_file(Path(storage_dir1 / 'moveddir/testfile'), 'abcd')
    assert wait_for_file(Path(storage_dir1 / 'moveddir/subdir/testfile3'), 'ijkl')

    shutil.move(str(storage_dir1 / 'moveddir'), str(tmpdir))

    assert wait_for_deletion(Path(storage_dir2 / 'moveddir'))


def test_sync_remove_file(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcd')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    os.unlink(storage_dir1 / 'file1')

    assert wait_for_deletion(Path(storage_dir2 / 'file1'))


def test_sync_remove_dir(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'subdir')
    os.mkdir(storage_dir2 / 'subdir')
    os.mkdir(storage_dir1 / 'subdir/subsubdir')
    os.mkdir(storage_dir2 / 'subdir/subsubdir')
    make_file(storage_dir1 / 'subdir/file1', 'abcd')
    make_file(storage_dir2 / 'subdir/file1', 'abcd')
    make_file(storage_dir1 / 'subdir/subsubdir/file2', 'efgh')
    make_file(storage_dir2 / 'subdir/subsubdir/file2', 'efgh')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    shutil.rmtree(str(storage_dir1 / 'subdir'))

    assert wait_for_deletion(Path(storage_dir2 / 'subdir'))


def test_sync_move_file(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcd')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    shutil.move(str(storage_dir1 / 'file1'), str(storage_dir1 / 'file2'))

    assert wait_for_deletion(Path(storage_dir2 / 'file1'))
    assert wait_for_file(Path(storage_dir2 / 'file2'), 'abcd')

    shutil.move(str(storage_dir1 / 'file2'), str(tmpdir))

    assert wait_for_deletion(Path(storage_dir2 / 'file2'))


def test_sync_simple_conflict(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcdefghijkl')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert do_correct_event(Path(storage_dir1 / 'file2'))

    assert read_file(storage_dir1 / 'file1') == 'abcd'
    assert read_file(storage_dir2 / 'file1') == 'abcdefghijkl'

    make_file(storage_dir1 / 'file1', '1234')
    make_file(storage_dir2 / 'file1', 'ZZZZZZZZ')

    assert do_correct_event(Path(storage_dir1 / 'file3'))
    assert read_file(storage_dir1 / 'file1') == '1234'
    assert read_file(storage_dir2 / 'file1') == 'ZZZZZZZZ'


def test_sync_complex_conflict(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'a')
    make_file(storage_dir2 / 'file1', 'a')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert do_correct_event(Path(storage_dir1 / 'file2'))

    # Simulate going into a tunnel
    with syncer.lock:
        make_file(storage_dir1 / 'file1', '1234')
        make_file(storage_dir2 / 'file1', 'ZZZZZZZZ')

    assert do_correct_event(Path(storage_dir1 / 'file3'))

    assert read_file(storage_dir1 / 'file1') == '1234'
    assert read_file(storage_dir2 / 'file1') == 'ZZZZZZZZ'


def test_sync_lost_event_delete(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'a')
    make_file(storage_dir2 / 'file1', 'a')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    # "lost" event (we filter out backend-caused events)

    with backend1.open('file1', os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    assert do_correct_event(Path(storage_dir1 / 'file2'))

    assert read_file(storage_dir1 / 'file1') == 'bbbb'
    assert read_file(storage_dir2 / 'file1') == 'a'

    # normal event
    os.unlink(storage_dir2 / 'file1')

    assert do_correct_event(Path(storage_dir1 / 'file3'))

    assert wait_for_file(Path(storage_dir1 / 'file1'), 'bbbb')
    assert wait_for_deletion(Path(storage_dir2 / 'file1'))


def test_sync_delete_conflict(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', '123456789')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert do_correct_event(Path(storage_dir1 / 'file3'))

    # Deleting one of the files acts as choosing the other as the correct version
    os.unlink(storage_dir1 / 'file1')

    assert wait_for_file(Path(storage_dir1 / 'file1'), '123456789')
    assert wait_for_file(Path(storage_dir2 / 'file1'), '123456789')


def test_sync_conflict_resolved(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', '1234')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    # on conflict, files did not change
    assert read_file(storage_dir1 / 'file1') == 'abcd'
    assert read_file(storage_dir2 / 'file1') == '1234'

    # Fix conflict manually
    make_file(storage_dir2 / 'file1', 'abcd')

    assert wait_for_file(Path(storage_dir1 / 'file1'), 'abcd')
    assert wait_for_file(Path(storage_dir2 / 'file1'), 'abcd')

    time.sleep(1)
    # Make another change
    make_file(storage_dir1 / 'file1', 'xyz')

    assert wait_for_file(Path(storage_dir1 / 'file1'), 'xyz')
    assert wait_for_file(Path(storage_dir2 / 'file1'), 'xyz')


def test_sync_move_from_subdir(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'subdir')
    make_file(storage_dir1 / 'subdir/file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcdefghijkl')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert wait_for_file(Path(storage_dir1 / 'subdir/file1'), 'abcd')
    assert wait_for_file(Path(storage_dir2 / 'subdir/file1'), 'abcd')
    assert wait_for_file(Path(storage_dir1 / 'file1'), 'abcdefghijkl')
    assert wait_for_file(Path(storage_dir2 / 'file1'), 'abcdefghijkl')

    time.sleep(1)

    shutil.move(str(storage_dir1 / 'subdir/file1'), str(storage_dir1 / 'file1'))

    assert wait_for_file(Path(storage_dir1 / 'file1'), 'abcd')
    assert wait_for_file(Path(storage_dir2 / 'file1'), 'abcd')
    assert wait_for_deletion(Path(storage_dir1 / 'subdir/file1'))
    assert wait_for_deletion(Path(storage_dir2 / 'subdir/file1'))


def test_sync_file_dir_conflict(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'test')
    make_file(storage_dir2 / 'test', 'abcd')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert do_correct_event(Path(storage_dir1 / 'file1'))

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == 'abcd'

    # changes to file should not cause further errors
    make_file(storage_dir2 / 'test', '11')

    assert do_correct_event(Path(storage_dir1 / 'file2'))

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == '11'


def test_sync_file_dir_conf_res1(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'test')
    make_file(storage_dir2 / 'test', 'abcd')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert do_correct_event(Path(storage_dir1 / 'file1'))

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == 'abcd'

    # moving the directory away should lead to syncing of the file
    os.rmdir(storage_dir1 / 'test')

    assert wait_for_file(Path(storage_dir1 / 'test'), 'abcd')
    assert wait_for_file(Path(storage_dir2 / 'test'), 'abcd')


def test_sync_file_dir_conf_res2(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'test')
    make_file(storage_dir2 / 'test', 'abcd')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert do_correct_event(Path(storage_dir1 / 'file1'))

    assert Path(storage_dir1 / 'test').is_dir()
    assert read_file(storage_dir2 / 'test') == 'abcd'

    # moving the file away should resume syncing
    shutil.move(str(storage_dir2 / 'test'), tmpdir)

    assert Path(storage_dir1 / 'test').is_dir()
    assert wait_for_dir(Path(storage_dir2 / 'test'))


@pytest.mark.parametrize('use_hash_db', [True, False])
def test_sync_two_containers(tmpdir, storage_backend, cleanup, use_hash_db):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')
    backend3, storage_dir3 = make_storage(storage_backend, tmpdir / 'storage3')
    backend4, storage_dir4 = make_storage(storage_backend, tmpdir / 'storage4')

    if use_hash_db:
        backend1.set_config_dir(tmpdir)
        backend2.set_config_dir(tmpdir)
        backend3.set_config_dir(tmpdir)
        backend4.set_config_dir(tmpdir)

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir3 / 'file2', 'efgh')

    syncer1 = make_syncer(backend1, backend2)
    syncer2 = make_syncer(backend3, backend4)
    cleanup(syncer1.stop_sync)
    cleanup(syncer2.stop_sync)
    syncer1.start_sync()
    syncer2.start_sync()

    assert wait_for_file(Path(storage_dir2 / 'file1'), 'abcd')
    assert wait_for_file(Path(storage_dir4 / 'file2'), 'efgh')

    assert wait_for_deletion(Path(storage_dir1 / 'file2'))
    assert wait_for_deletion(Path(storage_dir2 / 'file2'))
    assert wait_for_deletion(Path(storage_dir3 / 'file1'))
    assert wait_for_deletion(Path(storage_dir4 / 'file1'))


@pytest.mark.parametrize('use_hash_db', [True, False])
def test_get_conflicts_simple(tmpdir, storage_backend, cleanup, use_hash_db):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')
    backend3, storage_dir3 = make_storage(storage_backend, tmpdir / 'storage3')

    make_file(storage_dir1 / 'file1', 'aaaa')
    make_file(storage_dir2 / 'file1', 'bbbb')
    make_file(storage_dir3 / 'file1', 'cccc')

    backends = [backend1, backend2, backend3]

    if use_hash_db:
        for backend in backends:
            backend.set_config_dir(tmpdir)

    conflicts = []

    for b1, b2 in combinations(backends, 2):
        syncer = make_syncer(b1, b2)
        conflicts.extend(syncer.iter_conflicts_force())

    expected_conflicts = []

    for b1, b2 in combinations(backends, 2):
        expected_conflicts.append(SyncConflict(Path('file1'), b1.backend_id, b2.backend_id))

    assert conflicts == expected_conflicts


def test_find_syncer(tmpdir):
    # pylint: disable=protected-access
    backend1, _ = make_storage(LocalStorageBackend, tmpdir / 'storage1')
    backend2, _ = make_storage(LocalStorageBackend, tmpdir / 'storage2')

    backend1.TYPE = 'type1'
    backend2.TYPE = 'type2'

    for bool1, bool2, bool3, bool4 in product([True, False], repeat=4):
        syncer = BaseSyncer.from_storages(backend1, backend2,
                                          'test', unidirectional=bool1,
                                          one_shot=bool2, continuous=bool3, can_require_mount=bool4)
        # assert that a Syncer was found
        assert syncer.SYNCER_NAME

    class TestSyncer1(BaseSyncer):
        SYNCER_NAME = "test1"
        SOURCE_TYPES = ["type1"]
        TARGET_TYPES = ["*"]
        ONE_SHOT = True
        CONTINUOUS = True
        UNIDIRECTIONAL = True
        REQUIRES_MOUNT = False

        def iter_conflicts_force(self):
            pass

        def iter_conflicts(self):
            pass

    class TestSyncer2(BaseSyncer):
        SYNCER_NAME = "test2"
        SOURCE_TYPES = ["type1"]
        TARGET_TYPES = ["type2"]
        ONE_SHOT = True
        CONTINUOUS = True
        UNIDIRECTIONAL = True
        REQUIRES_MOUNT = False

        def iter_conflicts_force(self):
            pass

        def iter_conflicts(self):
            pass

    BaseSyncer._types['test1'] = TestSyncer1
    BaseSyncer._types['test2'] = TestSyncer2

    for bool1, bool2, bool3, bool4 in product([True, False], repeat=4):
        syncer = BaseSyncer.from_storages(backend1, backend2,
                                          'test', unidirectional=bool1,
                                          one_shot=bool2, continuous=bool3, can_require_mount=bool4)
        # assert that the correct Syncer was found
        assert syncer.SYNCER_NAME == 'test2'


def assert_event(client: Client, ev: SyncEvent):
    event = next(client.get_sync_event())
    assert event == ev


def assert_state(client: Client, job_id: str, state: SyncState):
    assert_event(client, SyncStateEvent(state, job_id))


def wait_for_event(client: Client, predicate: Callable[[SyncEvent], bool]):
    while True:
        event = next(client.get_sync_event())
        if predicate(event):
            break


def wait_for_state(client: Client, job_id: str, state: SyncState):
    wait_for_event(client, lambda s: s == SyncStateEvent(state, job_id))


def events_setup(base_dir, cli, container_name):
    base_data_dir = base_dir / container_name
    storage1_data = base_data_dir / 'storage1'
    storage2_data = base_data_dir / 'storage2'

    if not base_data_dir.exists():
        os.mkdir(base_data_dir)
    os.mkdir(storage1_data)
    os.mkdir(storage2_data)

    cli('user', 'create', 'Alice')
    cli('container', 'create', '--owner', 'Alice', '--path', '/Alice', container_name)
    cli('storage', 'create', 'local', '--container', container_name, '--location', storage1_data)
    cli('storage', 'create', 'local-cached', '--container', container_name,
        '--location', storage2_data)

    client = Client(base_dir)
    container = client.load_object_from_name(WildlandObject.Type.CONTAINER, container_name)
    source = client.get_local_storage(container, 'local')
    target = client.get_remote_storage(container, 'local-cached')
    job_id = container.sync_id
    path1 = storage1_data / 'testfile'
    path2 = storage2_data / 'testfile'
    return client, source, target, job_id, path1, path2


# pylint: disable=unused-argument
def test_sync_events_oneshot(base_dir, sync, cli):
    container_name = 'sync_events_oneshot'
    client, source, target, job_id, path1, _ = events_setup(base_dir, cli, container_name)

    # one-shot
    make_file(path1, 'test data')
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=True,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    assert_state(client, job_id, SyncState.SYNCED)


# pylint: disable=unused-argument
def test_sync_events_continuous_pre(base_dir, sync, cli):
    container_name = 'sync_events_continuous_pre'
    client, source, target, job_id, path1, _ = events_setup(base_dir, cli, container_name)

    # continuous, preexisting file
    make_file(path1, 'test data')
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    assert_state(client, job_id, SyncState.RUNNING)
    assert_state(client, job_id, SyncState.SYNCED)


# pylint: disable=unused-argument
def test_sync_events_continuous_post(base_dir, sync, cli):
    container_name = 'sync_events_continuous_post'
    client, source, target, job_id, path1, _ = events_setup(base_dir, cli, container_name)

    # continuous, file created after sync start
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)  # initial sync
    assert_state(client, job_id, SyncState.SYNCED)
    make_file(path1, 'test data')
    assert_state(client, job_id, SyncState.RUNNING)  # handling events
    # there can be some more RUNNING events before this
    wait_for_state(client, job_id, SyncState.SYNCED)


# pylint: disable=unused-argument
def test_sync_events_oneshot_error(base_dir, sync, cli):
    container_name = 'sync_events_oneshot_error'
    client, source, target, job_id, path1, _ = events_setup(base_dir, cli, container_name)

    shutil.rmtree(path1.parent)
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=True,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    wait_for_event(client, lambda ev: ev.type == SyncErrorEvent.type and
                   ev.job_id == job_id and
                   'No such file or directory' in ev.value)


# pylint: disable=unused-argument
def test_sync_events_continuous_error(base_dir, sync, cli):
    container_name = 'sync_events_continuous_error'
    client, source, target, job_id, path1, _ = events_setup(base_dir, cli, container_name)

    make_file(path1, 'test data')
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    wait_for_state(client, job_id, SyncState.SYNCED)
    shutil.rmtree(path1.parent)
    wait_for_event(client, lambda ev: ev.type == SyncErrorEvent.type and
                   ev.job_id == job_id and
                   'No such file or directory' in ev.value)


# pylint: disable=unused-argument
def test_sync_events_oneshot_conflict(base_dir, sync, cli):
    container_name = 'sync_events_oneshot_conflict'
    client, source, target, job_id, path1, path2 = events_setup(base_dir, cli, container_name)

    make_file(path1, 'test data 1')
    make_file(path2, 'test data 2')
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=True,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    wait_for_event(client, lambda ev: ev.type == SyncConflictEvent.type and
                   ev.job_id == job_id and
                   'Conflict detected on testfile' in ev.value)


# pylint: disable=unused-argument
def test_sync_events_continuous_pre_conflict(base_dir, sync, cli):
    container_name = 'sync_events_continuous_pre_conflict'
    client, source, target, job_id, path1, path2 = events_setup(base_dir, cli, container_name)

    make_file(path1, 'test data 1')
    make_file(path2, 'test data 2')
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    wait_for_event(client, lambda ev: ev.type == SyncConflictEvent.type and
                   ev.job_id == job_id and
                   'Conflict detected on testfile' in ev.value)


# pylint: disable=unused-argument
def test_sync_events_continuous_post_conflict(base_dir, sync, cli):
    container_name = 'sync_events_continuous_post_conflict'
    client, source, target, job_id, path1, _ = events_setup(base_dir, cli, container_name)

    make_file(path1, 'test data 1')
    client.do_sync(container_name, job_id, source.params, target.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id, SyncState.ONE_SHOT)
    assert_state(client, job_id, SyncState.RUNNING)
    assert_state(client, job_id, SyncState.SYNCED)
    make_file(path1, 'test data 2')
    wait_for_event(client, lambda ev: ev.type == SyncConflictEvent.type and
                   ev.job_id == job_id and
                   'Conflict detected on testfile' in ev.value)


# pylint: disable=unused-argument
def test_sync_events_multiple(base_dir, sync, cli):
    container_name1 = 'sync_events_multiple_1'
    container_name2 = 'sync_events_multiple_2'
    _, source1, target1, job_id1, path1a, _ = events_setup(base_dir, cli, container_name1)
    client, source2, target2, job_id2, path1b, _ = events_setup(base_dir, cli, container_name2)

    client.do_sync(container_name1, job_id1, source1.params, target1.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id1, SyncState.ONE_SHOT)  # initial sync
    assert_state(client, job_id1, SyncState.SYNCED)
    client.do_sync(container_name2, job_id2, source2.params, target2.params, one_shot=False,
                   unidir=False)
    assert_state(client, job_id2, SyncState.ONE_SHOT)
    assert_state(client, job_id2, SyncState.SYNCED)

    make_file(path1a, 'test data')
    wait_for_state(client, job_id1, SyncState.RUNNING)  # handling events
    wait_for_state(client, job_id1, SyncState.SYNCED)

    make_file(path1b, 'test data')
    wait_for_state(client, job_id2, SyncState.RUNNING)
    wait_for_state(client, job_id2, SyncState.SYNCED)
