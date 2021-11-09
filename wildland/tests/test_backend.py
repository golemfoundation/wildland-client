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
import io
import sqlite3
import time
from typing import Callable, Dict, Iterable, List, Set, Tuple
from pathlib import PurePosixPath, Path
from unittest.mock import patch
from dataclasses import dataclass

import pytest

from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.local_cached import LocalCachedStorageBackend, \
    LocalDirectoryCachedStorageBackend
from ..storage_backends.base import StorageBackend, verify_local_access, OptionalError
from ..storage_backends.watch import FileEvent, FileEventType


@pytest.fixture(params=[LocalStorageBackend, LocalCachedStorageBackend,
                        LocalDirectoryCachedStorageBackend])
def storage_backend(request) -> Callable:
    """
    Parametrize the tests by storage backend; at the moment include only those with watchers
    implemented.
    """

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
    assert received_events == [FileEvent(FileEventType.CREATE, PurePosixPath('newdir'))]
    received_events.clear()

    with backend.create(PurePosixPath('newdir/testfile'), flags=os.O_CREAT):
        pass

    time.sleep(1)
    # either create or create and modify are correct
    assert received_events in [
        [FileEvent(FileEventType.CREATE, PurePosixPath('newdir/testfile'))],
        [FileEvent(FileEventType.CREATE, PurePosixPath('newdir/testfile')),
         FileEvent(FileEventType.MODIFY, PurePosixPath('newdir/testfile'))]]

    received_events.clear()

    with backend.open(PurePosixPath('newdir/testfile'), os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    time.sleep(1)
    assert received_events == [FileEvent(FileEventType.MODIFY, PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.unlink(PurePosixPath('newdir/testfile'))

    time.sleep(1)
    assert received_events == [FileEvent(FileEventType.DELETE, PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.rmdir(PurePosixPath('newdir'))

    time.sleep(1)
    assert received_events == [FileEvent(FileEventType.DELETE, PurePosixPath('newdir'))]


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

    # we can allow one superfluous modify event, if file creation was parsed as two events and not
    # one
    assert received_events in [
        [], [FileEvent(FileEventType.MODIFY, PurePosixPath('newdir/testfile'))]]

    assert watcher.ignore_list == []

    received_events.clear()

    # perform some external operations
    os.mkdir(tmpdir / 'storage1/anotherdir')

    time.sleep(1)

    assert received_events == [FileEvent(FileEventType.CREATE, PurePosixPath('anotherdir'))]


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
    file_path = PurePosixPath('testfile')
    disk_path = PurePosixPath(storage_dir / 'testfile')

    file = backend.create(file_path, flags=os.O_CREAT)
    file.release(0)

    try:
        with open(disk_path):
            pass
    except FileNotFoundError:
        pytest.fail(f'{disk_path} does not exist')

    with backend.open(file_path, flags=os.O_RDWR) as f:
        f.write(b'test data', offset=0)

    with open(disk_path, 'r') as f:
        assert f.read() == 'test data'

    with backend.open(file_path, flags=os.O_RDONLY) as f:
        with pytest.raises((io.UnsupportedOperation, OptionalError)):
            f.write(b'other data', offset=0)

        assert f.read() == b'test data'


def test_local_dir_cached(tmpdir):
    backend, storage_dir = make_storage(tmpdir, LocalDirectoryCachedStorageBackend)

    # Make sure that the cache will not expire automatically during the test due to the timeout
    # (don't assume the default value is long enough)

    timeout_seconds = 3.0
    backend.cache_timeout = timeout_seconds

    # Create sample test tree with the text files and directories

    entries = {
        'dir': None,
        'dir/text_file_main': 'text file in main dir',
        'dir/subdir0': None,
        'dir/subdir0/text_file_00': 'file-00',
        'dir/subdir0/text_file_01': 'file-01',
        'dir/subdir0/subdir00': None,
        'dir/subdir0/subdir00/text_file_000': 'Wildland000',
        'dir/subdir0/subdir00/text_file_001': 'Wildland001',
        'dir/subdir0/subdir01': None,
        'dir/subdir0/subdir02': None,
        'dir/subdir0/subdir02/text_file_020': 'hello',
        'dir/subdir0/subdir02/text_file_021': 'world',
        'dir/subdir0/subdir02/text_file_022': '!!',
        'dir/subdir1': None,
        'dir/subdir1/subdir10': None,
        'dir/subdir1/subdir11': None,
        'dir/subdir1/subdir12': None,
        'dir/subdir2': None,
        'dir/subdir2/subdir20': None,
        'dir/subdir2/subdir21': None,
        'dir/subdir2/subdir22': None,
        'dir/subdir2/subdir22/text_file_220': 'file 220',
        'dir/subdir2/subdir22/text_file_221': 'file 221',
    }

    for path_str, content in entries.items():
        path = PurePosixPath(path_str)
        storage_path_str = str(storage_dir / path)

        if content:
            file = backend.create(path, flags=os.O_CREAT)
            file.write(bytes(content, encoding='utf8'), 0)
            file.release(os.O_RDWR)
            assert os.path.isfile(storage_path_str)
        else:
            backend.mkdir(PurePosixPath(path))
            assert os.path.isdir(storage_path_str)

    # Make sure that the cache is initially empty

    assert backend.readdir_cache == {}
    assert sorted(backend.getattr_cache.keys()) == []
    assert sorted(backend.dir_expiry.keys()) == []

    # Define the test scenario by specifying both: sequence of the directories to be readdir()'ed
    # and the respective caches' content

    @dataclass
    class ExpectedCacheState:
        dir_path: PurePosixPath
        expected_listing: Iterable[str]
        expected_readdir_cache: Dict[PurePosixPath, Set[str]]
        expected_getattr_cache: Iterable[PurePosixPath]
        expected_dir_expiry: Iterable[PurePosixPath]

    steps = (
        # step 1
        ExpectedCacheState(
            dir_path=PurePosixPath('dir'),
            expected_listing=['text_file_main', 'subdir0', 'subdir1', 'subdir2'],
            expected_readdir_cache={
                # Only already referred directories are cached (NOT recursively!)
                PurePosixPath('dir'): {
                    'text_file_main', 'subdir0', 'subdir1', 'subdir2'
                }
            },
            expected_getattr_cache=[
                PurePosixPath('dir/text_file_main'),
                PurePosixPath('dir/subdir0'),
                PurePosixPath('dir/subdir1'),
                PurePosixPath('dir/subdir2')
            ],
            expected_dir_expiry=[PurePosixPath('dir')]
        ),
        # step 2
        ExpectedCacheState(
            dir_path=PurePosixPath('dir/subdir0/subdir00'),
            expected_listing=['text_file_000', 'text_file_001'],
            expected_readdir_cache={
                PurePosixPath('dir'): {
                    'text_file_main', 'subdir0', 'subdir1', 'subdir2'
                },
                PurePosixPath('dir/subdir0/subdir00'): {
                    'text_file_000', 'text_file_001'
                }
            },
            expected_getattr_cache=[
                PurePosixPath('dir/text_file_main'),
                PurePosixPath('dir/subdir0'),
                PurePosixPath('dir/subdir1'),
                PurePosixPath('dir/subdir2'),
                # Notice that the following entry is NOT in the cache:
                # PurePosixPath('dir/subdir0/subdir00'),
                PurePosixPath('dir/subdir0/subdir00/text_file_000'),
                PurePosixPath('dir/subdir0/subdir00/text_file_001')
            ],
            expected_dir_expiry=[
                PurePosixPath('dir'),
                PurePosixPath('dir/subdir0/subdir00')
            ]
        ),
        # step 3
        ExpectedCacheState(
            dir_path=PurePosixPath('.'),
            expected_listing=['dir'],
            expected_readdir_cache={
                PurePosixPath('dir'): {
                    'text_file_main', 'subdir0', 'subdir1', 'subdir2'
                },
                PurePosixPath('dir/subdir0/subdir00'): {
                    'text_file_000', 'text_file_001'
                },
                PurePosixPath('.'): {
                    'dir'
                }
            },
            expected_getattr_cache=[
                PurePosixPath('dir/text_file_main'),
                PurePosixPath('dir/subdir0'),
                PurePosixPath('dir/subdir1'),
                PurePosixPath('dir/subdir2'),
                PurePosixPath('dir/subdir0/subdir00/text_file_000'),
                PurePosixPath('dir/subdir0/subdir00/text_file_001'),
                PurePosixPath('dir')
            ],
            expected_dir_expiry=[
                PurePosixPath('dir'),
                PurePosixPath('dir/subdir0/subdir00'),
                PurePosixPath('.')
            ]
        ),
        # step 4
        ExpectedCacheState(
            dir_path=PurePosixPath('dir/subdir2/subdir22'),
            expected_listing=['text_file_220', 'text_file_221'],
            expected_readdir_cache={
                PurePosixPath('dir'): {
                    'text_file_main', 'subdir0', 'subdir1', 'subdir2'
                },
                PurePosixPath('dir/subdir0/subdir00'): {
                    'text_file_000', 'text_file_001'
                },
                PurePosixPath('.'): {
                    'dir'
                },
                PurePosixPath('dir/subdir2/subdir22'): {
                    'text_file_220', 'text_file_221'
                },
            },
            expected_getattr_cache=[
                PurePosixPath('dir/text_file_main'),
                PurePosixPath('dir/subdir0'),
                PurePosixPath('dir/subdir1'),
                PurePosixPath('dir/subdir2'),
                PurePosixPath('dir/subdir0/subdir00/text_file_000'),
                PurePosixPath('dir/subdir0/subdir00/text_file_001'),
                PurePosixPath('dir'),
                PurePosixPath('dir/subdir2/subdir22/text_file_220'),
                PurePosixPath('dir/subdir2/subdir22/text_file_221')
            ],
            expected_dir_expiry=[
                PurePosixPath('dir'),
                PurePosixPath('dir/subdir0/subdir00'),
                PurePosixPath('.'),
                PurePosixPath('dir/subdir2/subdir22')
            ]
        )
    )

    # Iterate all of the test scenario steps for the first time

    for step in steps:
        listing = backend.readdir(step.dir_path)
        assert sorted(listing) == sorted(step.expected_listing)
        assert backend.readdir_cache == step.expected_readdir_cache
        assert sorted(backend.getattr_cache.keys()) == sorted(step.expected_getattr_cache)
        assert sorted(backend.dir_expiry.keys()) == sorted(step.expected_dir_expiry)

    # Modify 'dir/subdir0/subdir02/text_file_022' to make sure that the cache will be cleared up
    # (all operations that might change the result invalidate ALL of the caches)

    file = backend.open(PurePosixPath('dir/subdir0/subdir02/text_file_022'), os.O_RDWR)
    file.write(b'mars', 0)
    file.release(os.O_RDWR)

    with open(storage_dir / 'dir/subdir0/subdir02/text_file_022') as file:
        assert file.read() == 'mars'

    assert backend.readdir_cache == {}
    assert sorted(backend.getattr_cache.keys()) == []
    assert sorted(backend.dir_expiry.keys()) == []

    # Iterate all of the test scenario steps for the second time. Each directory is visited twice to
    # make sure that the cache is actually being used when readdir() is called for the second time.

    with patch.object(LocalDirectoryCachedStorageBackend, 'info_dir',
                      wraps=backend.info_dir) as info_dir_mock:
        for step in steps:
            listing = backend.readdir(step.dir_path)
            assert sorted(listing) == sorted(step.expected_listing)
            assert backend.readdir_cache == step.expected_readdir_cache
            assert sorted(backend.getattr_cache.keys()) == sorted(step.expected_getattr_cache)
            assert sorted(backend.dir_expiry.keys()) == sorted(step.expected_dir_expiry)

            number_of_info_dir_calls = len(info_dir_mock.mock_calls)
            info_dir_mock.assert_called_with(step.dir_path)

            # Make sure that the cache is being used during the second readdir() call
            repeated_listing = backend.readdir(step.dir_path)
            assert sorted(listing) == sorted(repeated_listing)
            assert number_of_info_dir_calls == len(info_dir_mock.mock_calls)

    # Add one more file without using backend's create() API

    new_file_path = 'dir/new_text_file'
    with open(storage_dir / new_file_path, 'w') as f:
        f.write('new file!')

    assert os.path.isfile(storage_dir / new_file_path)

    # Remove one file to check whether the cache is properly refreshed

    file_path_to_remove = storage_dir / 'dir/text_file_main'
    os.remove(file_path_to_remove)
    assert not os.path.exists(file_path_to_remove)

    # Make the cache expire (+1 to make sure it actually expired)

    time.sleep(timeout_seconds + 1)

    with patch.object(LocalDirectoryCachedStorageBackend, 'info_dir',
                      wraps=backend.info_dir) as info_dir_mock:
        # Updates the readdir() cache (among the others) under the hood
        attr = backend.getattr('dir/subdir2')
        info_dir_mock.assert_called_once_with(PurePosixPath('dir'))
        assert attr.is_dir()
        # Make sure it uses cache instead of calling info_dir() again
        backend.getattr('dir/subdir2')
        info_dir_mock.assert_called_once_with(PurePosixPath('dir'))

    assert backend.readdir_cache == {
        # 'dir/text_file_main' was correctly removed + 'dir/new_text_file' was correctly added
        PurePosixPath('dir'): {
            'subdir0', 'subdir1', 'subdir2', 'new_text_file'
        },
        PurePosixPath('dir/subdir0/subdir00'): {
            'text_file_000', 'text_file_001'
        },
        PurePosixPath('dir/subdir2/subdir22'): {
            'text_file_220', 'text_file_221'
        },
        PurePosixPath('.'): {
            'dir'
        }
    }

    assert sorted(backend.getattr_cache.keys()) == [
        PurePosixPath('dir'),
        PurePosixPath('dir/new_text_file'),
        PurePosixPath('dir/subdir0'),
        PurePosixPath('dir/subdir0/subdir00/text_file_000'),
        PurePosixPath('dir/subdir0/subdir00/text_file_001'),
        PurePosixPath('dir/subdir1'),
        PurePosixPath('dir/subdir2'),
        PurePosixPath('dir/subdir2/subdir22/text_file_220'),
        PurePosixPath('dir/subdir2/subdir22/text_file_221')
    ]

    assert sorted(backend.dir_expiry.keys()) == [
            PurePosixPath('.'),
            PurePosixPath('dir'),
            PurePosixPath('dir/subdir0/subdir00'),
            PurePosixPath('dir/subdir2/subdir22')
    ]

    # Outdated cache entries

    assert backend.dir_expiry[PurePosixPath('.')] < time.time()
    assert backend.dir_expiry[PurePosixPath('dir/subdir0/subdir00')] < time.time()
    assert backend.dir_expiry[PurePosixPath('dir/subdir2/subdir22')] < time.time()

    # Up-to-date cache entries

    assert backend.dir_expiry[PurePosixPath('dir')] > time.time()

    # Read 'dir/subdir2/subdir22' content to refresh cache expiration time

    backend.readdir(PurePosixPath('dir/subdir2/subdir22'))
    assert backend.dir_expiry[PurePosixPath('dir/subdir2/subdir22')] > time.time()
