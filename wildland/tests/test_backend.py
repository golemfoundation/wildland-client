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
import io
import sqlite3
import time
from typing import Callable, List, Tuple
from pathlib import PurePosixPath, Path
from unittest.mock import patch

import pytest

from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.local_cached import LocalCachedStorageBackend, \
    LocalDirectoryCachedStorageBackend
from ..storage_backends.base import StorageBackend, verify_local_access, OptionalError
from ..storage_backends.watch import FileEvent


@pytest.fixture(params=[LocalStorageBackend, LocalCachedStorageBackend,
                        LocalDirectoryCachedStorageBackend])
def storage_backend(request) -> Callable:
    '''
    Parametrize the tests by storage backend; at the moment include only those with watchers
    implemented.
    '''

    return request.param


@pytest.fixture
def cleanup():
    cleanup_functions = []

    def add_cleanup(func):
        cleanup_functions.append(func)

    yield add_cleanup

    for f in cleanup_functions:
        f()


def make_storage(location, backend_class) -> Tuple[StorageBackend, Path]:
    storage_dir = location / 'storage1'
    os.mkdir(storage_dir)
    backend = backend_class(params={'location': str(storage_dir),
                                    'type': getattr(backend_class, 'TYPE'),
                                    'backend-id': 'test_id'})
    return backend, storage_dir


# Local

def test_simple_operations(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    backend.mkdir(PurePosixPath('newdir'))
    assert (storage_dir / 'newdir').exists()

    file = backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT)
    file.release(os.O_RDWR)
    assert (storage_dir / 'newdir/testfile').exists()

    file = backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR)
    file.write(b'aaaa', 0)
    file.release(os.O_RDWR)

    with open(storage_dir / 'newdir/testfile') as file:
        assert file.read() == 'aaaa'

    backend.unlink(PurePosixPath('newdir/testfile'))
    assert not (storage_dir / 'newdir/testfile').exists()

    backend.rmdir(PurePosixPath('newdir'))
    assert not (storage_dir / 'newdir').exists()


def test_watcher_not_ignore_own(tmpdir, storage_backend, cleanup):
    backend, _ = make_storage(tmpdir, storage_backend)

    received_events: List[FileEvent] = []

    backend.start_watcher(handler=received_events.extend, ignore_own_events=False)
    cleanup(backend.stop_watcher)

    backend.mkdir(PurePosixPath('newdir'))

    time.sleep(1)
    assert received_events == [FileEvent('create', PurePosixPath('newdir'))]
    received_events.clear()

    with backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT):
        pass

    time.sleep(1)
    # either create or create and modify are correct
    assert received_events in [
        [FileEvent('create', PurePosixPath('newdir/testfile'))],
        [FileEvent('create', PurePosixPath('newdir/testfile')),
         FileEvent('modify', PurePosixPath('newdir/testfile'))]]

    received_events.clear()

    with backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    time.sleep(1)
    assert received_events == [FileEvent('modify', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.unlink(PurePosixPath('newdir/testfile'))

    time.sleep(1)
    assert received_events == [FileEvent('delete', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.rmdir(PurePosixPath('newdir'))

    time.sleep(1)
    assert received_events == [FileEvent('delete', PurePosixPath('newdir'))]


def test_watcher_ignore_own(tmpdir, storage_backend, cleanup):
    backend, _ = make_storage(tmpdir, storage_backend)

    received_events: List[FileEvent] = []

    watcher = backend.start_watcher(handler=received_events.extend, ignore_own_events=True)
    cleanup(backend.stop_watcher)

    backend.mkdir(PurePosixPath('newdir'))
    time.sleep(1)

    with backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT):
        pass

    with backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR) as file:
        file.write(b'bbbb', 0)
    backend.unlink(PurePosixPath('newdir/testfile'))
    backend.rmdir(PurePosixPath('newdir'))

    time.sleep(1)

    # we can allow one superflous modify event, if file creation was parsed as two events and not
    # one
    assert received_events in [
        [], [FileEvent(type='modify', path=PurePosixPath('newdir/testfile'))]]

    assert watcher.ignore_list == []

    received_events.clear()

    # perform some external operations
    os.mkdir(tmpdir / 'storage1/anotherdir')

    time.sleep(1)

    assert received_events == [FileEvent('create', PurePosixPath('anotherdir'))]


def test_hashing_short(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('aaaa')

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'


def test_hashing_long(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    with open(storage_dir / 'testfile', mode='w') as f:
        for _ in range(1024 ** 2):
            f.write('aaaa')

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '299285fc41a44cdb038b9fdaf494c76ca9d0c866672b2b266c1a0c17dda60a05'


def test_hash_cache(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('aaaa')

    time.sleep(1)

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'

    with patch('hashlib.sha256'):
        # if the hash did not get cached correctly, this will return a mock not the correct hash
        assert backend.get_hash(PurePosixPath("testfile")) == \
               '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('bbbb')

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '81cc5b17018674b401b42f35ba07bb79e211239c23bffe658da1577e3e646877'


def test_hashing_db(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    backend.set_config_dir(tmpdir)

    assert (tmpdir / 'wlhashes.db').exists()

    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('aaaa')

    time.sleep(1)

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'

    with sqlite3.connect(tmpdir / 'wlhashes.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hashes')
        results = cursor.fetchall()
        assert len(results) == 1
        backend_id, path, hash_value, _ = results[0]

    assert backend_id == backend.backend_id
    assert path == 'testfile'
    assert hash_value == '61be55a8e2f6b4e172338bddf184d6dbee29c98853e0a0485ecee7f27b9af0b4'

    with sqlite3.connect(tmpdir / 'wlhashes.db') as conn:
        conn.execute('UPDATE hashes SET hash = \'testhash\' WHERE backend_id = ? AND path = ?',
                     (backend_id, str(path)))

    assert backend.get_hash(path) == 'testhash'

    # modify file
    with open(storage_dir / 'testfile', mode='w') as f:
        f.write('bbbb')

    time.sleep(1)

    assert backend.get_hash(PurePosixPath("testfile")) == \
           '81cc5b17018674b401b42f35ba07bb79e211239c23bffe658da1577e3e646877'

    with sqlite3.connect(tmpdir / 'wlhashes.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM hashes')
        results = cursor.fetchall()
        assert len(results) == 1
        backend_id, path, hash_value, _ = results[0]

    assert backend_id == backend.backend_id
    assert path == 'testfile'
    assert hash_value == '81cc5b17018674b401b42f35ba07bb79e211239c23bffe658da1577e3e646877'


def test_walk(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)

    os.mkdir(storage_dir / 'dir1')
    os.mkdir(storage_dir / 'dir2')
    os.mkdir(storage_dir / 'dir1/subdir1')
    os.mkdir(storage_dir / 'dir1/subdir2')
    os.mkdir(storage_dir / 'dir1/subdir1/subsubdir1')

    open(storage_dir / 'testfile1', 'a').close()
    open(storage_dir / 'dir2/testfile2', 'a').close()
    open(storage_dir / 'dir1/subdir1/testfile3', 'a').close()
    open(storage_dir / 'dir1/subdir1/testfile4', 'a').close()
    open(storage_dir / 'dir1/subdir1/subsubdir1/testfile5', 'a').close()

    received_files = [(str(f[0]), f[1].is_dir()) for f in backend.walk()]
    expected_files = [('dir1', True),
                      ('dir2', True),
                      ('dir1/subdir1', True),
                      ('dir1/subdir2', True),
                      ('dir1/subdir1/subsubdir1', True),
                      ('testfile1', False),
                      ('dir2/testfile2', False),
                      ('dir1/subdir1/testfile3', False),
                      ('dir1/subdir1/testfile4', False),
                      ('dir1/subdir1/subsubdir1/testfile5', False)]

    assert sorted(received_files) == sorted(expected_files)


def test_local_access(tmp_path):
    # local-owner
    verify_local_access(tmp_path, '0xaaaa', True)
    with pytest.raises(PermissionError):
        verify_local_access(tmp_path, '0xaaaa', False)


def test_local_access_file(tmp_path):
    (tmp_path / '.wildland-owners').write_bytes(
        b'0xaaaa\n'
        b'0xbbbb # comment\n'
        b'\n'
        b'# comment\n'
        b'# 0xcccc\n'
        b'0xdddd'  # no newline
    )
    verify_local_access(tmp_path, '0xaaaa', False)
    verify_local_access(tmp_path, '0xbbbb', False)
    with pytest.raises(PermissionError):
        verify_local_access(tmp_path, '0xcccc', False)
    verify_local_access(tmp_path, '0xdddd', False)

    verify_local_access(tmp_path / 'subdir/', '0xaaaa', False)
    verify_local_access(tmp_path / 'subdir/filename', '0xaaaa', False)


# Test respecting of read-only flags

def test_read_only_flags(tmpdir, storage_backend):
    backend, storage_dir = make_storage(tmpdir, storage_backend)
    file_path = Path('testfile')
    disk_path = Path(storage_dir / 'testfile')

    file = backend.create(file_path, flags=os.O_CREAT)
    file.release(0)

    assert disk_path.exists()

    with backend.open(file_path, flags=os.O_RDWR) as f:
        f.write(b'test data', offset=0)

    assert disk_path.read_bytes() == b'test data'

    with backend.open(file_path, flags=os.O_RDONLY) as f:
        with pytest.raises((io.UnsupportedOperation, OptionalError)):
            f.write(b'other data', offset=0)

        assert f.read() == b'test data'
