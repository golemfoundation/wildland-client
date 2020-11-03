# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument

import os
import shutil
import time
import logging
from typing import Callable
from pathlib import PurePosixPath

import pytest

from ..storage_backends.local import LocalStorageBackend
from ..cli.cli_sync import Syncer, BLOCK_SIZE
from ..log import init_logging

init_logging()

@pytest.fixture(params=[LocalStorageBackend])
def storage_backend(request) -> Callable:
    '''
    Parametrize the tests by storage backend; at the moment include only those with watchers
    implemented.
    '''

    return request.param


second_backend = storage_backend
third_backend = storage_backend


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
    os.mkdir(target_dir)
    backend = backend_class(params={'path': target_dir, 'type': backend_class.TYPE})
    return backend, target_dir


def test_sync_subdirs(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    dirs = [storage_dir1, storage_dir2]

    for d in dirs:
        make_file(d / 'testfile', 'abcd')
        os.mkdir(d / 'subdir')
        make_file(d / 'subdir/testfile2', 'efgh')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()
    time.sleep(1)

    make_file(storage_dir1 / 'testfile', '1234')
    time.sleep(1)

    assert read_file(storage_dir2 / 'testfile') == '1234'

    # Make a subdirectory and some data
    os.mkdir(storage_dir2 / 'subdir2')
    make_file(storage_dir2 / 'subdir2/testfile3', 'efgh')
    make_file(storage_dir2 / 'subdir2/testfile4', 'ijkl')
    time.sleep(1)

    assert (storage_dir1 / 'subdir2').exists()
    assert (storage_dir1 / 'subdir2/testfile3').exists()
    assert read_file(storage_dir1 / 'subdir2/testfile3') == 'efgh'
    assert read_file(storage_dir1 / 'subdir2/testfile4') == 'ijkl'


def test_sync_large_file(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    data = '1234' * (BLOCK_SIZE * 4 + 5)

    make_file(storage_dir1 / 'testfile', data)

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    assert read_file(storage_dir2 / 'testfile') == data


def test_sync_move_dir(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    os.mkdir(tmpdir / 'newdir')
    os.mkdir(tmpdir / 'newdir/subdir')
    make_file(tmpdir / 'newdir/testfile', 'abcd')
    make_file(tmpdir / 'newdir/subdir/testfile2', 'efgh')

    shutil.move(str(tmpdir / 'newdir'), str(storage_dir1))

    time.sleep(1)

    assert (storage_dir2 / 'newdir').exists()
    assert (storage_dir2 / 'newdir/testfile').exists()
    assert (storage_dir2 / 'newdir/subdir').exists()
    assert read_file(storage_dir2 / 'newdir/testfile') == 'abcd'
    assert read_file(storage_dir2 / 'newdir/subdir/testfile2') == 'efgh'

    make_file(storage_dir1 / 'newdir/subdir/testfile3', 'ijkl')
    time.sleep(1)

    assert read_file(storage_dir2 / 'newdir/subdir/testfile3') == 'ijkl'

    shutil.move(str(storage_dir2 / 'newdir'), str(storage_dir2 / 'moveddir'))
    time.sleep(1)

    assert not (storage_dir1 / 'newdir').exists()
    assert (storage_dir1 / 'moveddir').exists()
    assert (storage_dir1 / 'moveddir/testfile').exists()
    assert (storage_dir1 / 'moveddir/subdir').exists()
    assert read_file(storage_dir1 / 'moveddir/testfile') == 'abcd'
    assert read_file(storage_dir1 / 'moveddir/subdir/testfile3') == 'ijkl'

    shutil.move(str(storage_dir1 / 'moveddir'), str(tmpdir))
    time.sleep(1)

    assert not (storage_dir2 / 'moveddir').exists()


def test_sync_three_storages(tmpdir, storage_backend, second_backend, third_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(second_backend, tmpdir / 'storage2')
    backend3, storage_dir3 = make_storage(third_backend, tmpdir / 'storage3')

    os.mkdir(storage_dir1 / 'subdir1')
    os.mkdir(storage_dir1 / 'subdir1/subsubdir1')
    make_file(storage_dir1 / 'subdir1/file1', 'abcd')
    make_file(storage_dir1 / 'subdir1/subsubdir1/file2', 'efgh')

    make_file(storage_dir2 / 'file3', 'ijkl')

    syncer = Syncer([backend1, backend2, backend3], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    dirs = [storage_dir1, storage_dir2, storage_dir3]

    time.sleep(1)

    for d in dirs:
        assert (d / 'subdir1').exists()
        assert (d / 'subdir1/subsubdir1').exists()
        assert (d / 'subdir1/file1').exists()
        assert (d / 'subdir1/subsubdir1/file2').exists()
        assert (d / 'file3').exists()
        assert read_file(d / 'subdir1/file1') == 'abcd'
        assert read_file(d / 'subdir1/subsubdir1/file2') == 'efgh'
        assert read_file(d / 'file3') == 'ijkl'

    make_file(storage_dir3 / 'file4', 'mnop')
    time.sleep(1)

    for d in dirs:
        assert (d / 'file4').exists()
        assert read_file(storage_dir3 / 'file4') == 'mnop'


def test_sync_remove_file(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcd')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    os.unlink(storage_dir1 / 'file1')

    time.sleep(1)

    assert not (storage_dir2 / 'file1').exists()


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

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    shutil.rmtree(str(storage_dir1 / 'subdir'))

    time.sleep(1)

    assert not (storage_dir2 / 'subdir').exists()


def test_sync_move_file(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcd')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    shutil.move(str(storage_dir1 / 'file1'), str(storage_dir1 / 'file2'))
    time.sleep(1)

    assert not (storage_dir2 / 'file1').exists()
    assert (storage_dir2 / 'file2').exists()
    assert read_file(storage_dir2 / 'file2') == 'abcd'

    shutil.move(str(storage_dir1 / 'file2'), str(tmpdir))
    time.sleep(1)

    assert not (storage_dir2 / 'file2').exists()


def test_sync_simple_conflict(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcdefghijkl')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == 'abcd'
    assert read_file(storage_dir2 / 'file1') == 'abcdefghijkl'

    make_file(storage_dir1 / 'file1', '1234')
    make_file(storage_dir2 / 'file1', 'ZZZZZZZZ')
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == '1234'
    assert read_file(storage_dir2 / 'file1') == 'ZZZZZZZZ'


def test_sync_complex_conflict(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'a')
    make_file(storage_dir2 / 'file1', 'a')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()
    time.sleep(1)

    # Simulate going into a tunnel
    with syncer.lock:
        make_file(storage_dir1 / 'file1', '1234')
        make_file(storage_dir2 / 'file1', 'ZZZZZZZZ')
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == '1234'
    assert read_file(storage_dir2 / 'file1') == 'ZZZZZZZZ'


def test_sync_lost_event_delete(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'a')
    make_file(storage_dir2 / 'file1', 'a')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()
    time.sleep(1)

    # "lost" event (we filter out backend-caused events)
    logging.debug("IGNORE THIS MODIFY")
    with backend1.open('file1', os.O_RDWR) as file:
        file.write(b'bbbb', 0)
    logging.debug("CHANGE MADE")
    assert read_file(storage_dir1 / 'file1') == 'bbbb'
    assert read_file(storage_dir2 / 'file1') == 'a'
    time.sleep(1)

    # normal event
    os.unlink(storage_dir2 / 'file1')
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == 'bbbb'
    assert not (storage_dir2 / 'file1').exists()


def test_sync_delete_conflict(tmpdir, storage_backend, cleanup):

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', '123456789')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()
    time.sleep(1)

    # Deleting one of the files acts as choosing the other as the correct version
    os.unlink(storage_dir1 / 'file1')
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == '123456789'
    assert read_file(storage_dir2 / 'file1') == '123456789'


def test_sync_conflict_resolved(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    make_file(storage_dir1 / 'file1', 'abcd')
    make_file(storage_dir2 / 'file1', '1234')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == 'abcd'
    assert read_file(storage_dir2 / 'file1') == '1234'

    # Fix conflict manually
    make_file(storage_dir2 / 'file1', 'abcd')
    time.sleep(1)

    # Make another change
    make_file(storage_dir1 / 'file1', 'xyz')
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == 'xyz'
    assert read_file(storage_dir2 / 'file1') == 'xyz'


def test_sync_move_from_subdir(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'subdir')
    make_file(storage_dir1 / 'subdir/file1', 'abcd')
    make_file(storage_dir2 / 'file1', 'abcdefghijkl')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    assert read_file(storage_dir1 / 'subdir/file1') == 'abcd'
    assert read_file(storage_dir2 / 'subdir/file1') == 'abcd'
    assert read_file(storage_dir1 / 'file1') == 'abcdefghijkl'
    assert read_file(storage_dir2 / 'file1') == 'abcdefghijkl'

    shutil.move(str(storage_dir1 / 'subdir/file1'), str(storage_dir1 / 'file1'))
    time.sleep(1)

    assert read_file(storage_dir1 / 'file1') == 'abcd'
    assert read_file(storage_dir2 / 'file1') == 'abcd'
    assert (storage_dir1 / 'subdir').exists()
    assert (storage_dir2 / 'subdir').exists()
    assert not (storage_dir1 / 'subdir/file1').exists()
    assert not (storage_dir2 / 'subdir/file1').exists()


def test_sync_file_dir_conflict(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'test')
    make_file(storage_dir2 / 'test', 'abcd')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == 'abcd'

    # changes to file should not cause further errors
    make_file(storage_dir2 / 'test', '11')
    time.sleep(1)

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == '11'


def test_sync_file_dir_conf_res1(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'test')
    make_file(storage_dir2 / 'test', 'abcd')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == 'abcd'

    # moving the directory away should lead to syncing of the file
    os.rmdir(storage_dir1 / 'test')
    time.sleep(1)

    assert read_file(storage_dir1 / 'test') == 'abcd'
    assert read_file(storage_dir2 / 'test') == 'abcd'


def test_sync_file_dir_conf_res2(tmpdir, storage_backend, cleanup):
    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, storage_dir2 = make_storage(storage_backend, tmpdir / 'storage2')

    os.mkdir(storage_dir1 / 'test')
    make_file(storage_dir2 / 'test', 'abcd')

    syncer = Syncer([backend1, backend2], 'test')
    cleanup(syncer.stop_syncing)
    syncer.start_syncing()

    time.sleep(1)

    assert (storage_dir1 / 'test').isdir()
    assert read_file(storage_dir2 / 'test') == 'abcd'

    # moving the file away should resume syncing
    shutil.move(str(storage_dir2 / 'test'), tmpdir)
    time.sleep(1)

    assert (storage_dir1 / 'test').isdir()
    assert (storage_dir2 / 'test').isdir()
