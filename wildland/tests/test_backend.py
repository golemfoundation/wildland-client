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
import time
from typing import Callable, List
from pathlib import PurePosixPath

import pytest

from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.base import StorageBackend
from ..storage_backends.watch import FileEvent


@pytest.fixture(params=[LocalStorageBackend])
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

# Local

def test_simple_operations(tmpdir, storage_backend):
    storage_dir = tmpdir / 'storage1'
    os.mkdir(storage_dir)
    backend: StorageBackend = storage_backend(
        params={'path': storage_dir, 'type': storage_backend.TYPE})

    backend.mkdir(PurePosixPath('newdir'), mode=0o777)
    assert (storage_dir / 'newdir').exists()

    file = backend.create('newdir/testfile', flags=os.O_CREAT, mode=0o777)
    file.release(os.O_RDWR)
    assert (storage_dir / 'newdir/testfile').exists()

    file = backend.open('newdir/testfile', os.O_RDWR)
    file.write(b'aaaa', 0)
    file.release(os.O_RDWR)

    with open(storage_dir / 'newdir/testfile') as file:
        assert file.read() == 'aaaa'

    backend.unlink('newdir/testfile')
    assert not (storage_dir / 'newdir/testfile').exists()

    backend.rmdir('newdir')
    assert not (storage_dir / 'newdir').exists()


def test_watcher_not_ignore_own(tmpdir, storage_backend, cleanup):
    storage_type = storage_backend.TYPE
    storage_dir = tmpdir / 'storage1'
    os.mkdir(storage_dir)
    backend: StorageBackend = storage_backend(
        params={'path': storage_dir, 'type': storage_type})

    received_events: List[FileEvent] = []

    backend.start_watcher(handler=received_events.extend, ignore_own_events=False)
    cleanup(backend.stop_watcher)

    backend.mkdir(PurePosixPath('newdir'), mode=0o777)

    time.sleep(1)
    assert received_events == [FileEvent('create', PurePosixPath('newdir'))]
    received_events.clear()

    with backend.create('newdir/testfile', flags=os.O_CREAT, mode=0o777):
        pass

    time.sleep(1)
    assert received_events == [FileEvent('create', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    with backend.open('newdir/testfile', os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    time.sleep(1)
    assert received_events == [FileEvent('modify', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.unlink('newdir/testfile')

    time.sleep(1)
    assert received_events == [FileEvent('delete', PurePosixPath('newdir/testfile'))]
    received_events.clear()

    backend.rmdir('newdir')

    time.sleep(1)
    assert received_events == [FileEvent('delete', PurePosixPath('newdir'))]


def test_watcher_ignore_own(tmpdir, storage_backend, cleanup):
    storage_type = storage_backend.TYPE
    storage_dir = tmpdir / 'storage1'
    os.mkdir(storage_dir)
    backend: StorageBackend = storage_backend(
        params={'path': storage_dir, 'type': storage_type})

    received_events: List[FileEvent] = []

    watcher = backend.start_watcher(handler=received_events.extend, ignore_own_events=True)
    cleanup(backend.stop_watcher)

    backend.mkdir(PurePosixPath('newdir'), mode=0o777)
    time.sleep(1)

    with backend.create('newdir/testfile', flags=os.O_CREAT, mode=0o777):
        pass

    with backend.open('newdir/testfile', os.O_RDWR) as file:
        file.write(b'bbbb', 0)

    backend.unlink('newdir/testfile')

    backend.rmdir('newdir')

    time.sleep(2)

    assert received_events == []
    assert watcher.ignore_list == []

    # perform some external operations
    os.mkdir(tmpdir / 'storage1/anotherdir')

    time.sleep(2)

    assert received_events == [FileEvent('create', PurePosixPath('anotherdir'))]
