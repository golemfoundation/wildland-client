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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument,unused-import

import time
from pathlib import Path
from unittest.mock import patch

from wildland.log import init_logging
from wildland.storage_sync.naive_sync import NaiveSyncer
from wildland.tests.test_sync import make_storage, make_syncer, make_file, read_file, \
    wait_for_file, wait_for_deletion, storage_backend, cleanup

from .test_zip import make_zip
from ..backend import ZipArchiveStorageBackend

init_logging()


def test_zip_sync(tmpdir, storage_backend, cleanup):
    make_zip(tmpdir, [
        ('foo.txt', 'foo data'),
        ('dir/', ''),
        ('dir/bar.txt', 'bar data'),
    ])

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, _ = make_storage(ZipArchiveStorageBackend, tmpdir / 'archive.zip')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert wait_for_file(Path(storage_dir1 / 'foo.txt'), 'foo data')
    assert wait_for_file(Path(storage_dir1 / 'dir/bar.txt'), 'bar data')


def test_zip_sync_change(tmpdir, storage_backend, cleanup):
    make_zip(tmpdir, [
        ('foo.txt', 'foobar data'),
    ])

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, _ = make_storage(ZipArchiveStorageBackend, tmpdir / 'archive.zip')

    syncer = make_syncer(backend1, backend2)
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    assert Path(storage_dir1 / 'foo.txt').exists()
    assert read_file(storage_dir1 / 'foo.txt') == 'foobar data'

    make_zip(tmpdir, [
        ('bar.txt', 'data'),
    ])

    assert wait_for_file(Path(storage_dir1 / 'bar.txt'), 'data')
    assert wait_for_deletion(Path(storage_dir1 / 'foo.txt'))


def test_readonly_storage_sync(tmpdir, storage_backend, cleanup):
    make_zip(tmpdir, [])

    backend1, storage_dir1 = make_storage(storage_backend, tmpdir / 'storage1')
    backend2, _ = make_storage(ZipArchiveStorageBackend, tmpdir / 'archive.zip')

    syncer = NaiveSyncer(source_storage=backend1, target_storage=backend2,
                         log_prefix='Container test: ')
    cleanup(syncer.stop_sync)
    syncer.start_sync()

    with patch('wildland.storage_sync.naive_sync.logger.warning') as patched_logger:
        make_file(storage_dir1 / 'testfile', 'aaaa')

        time.sleep(1)

        # depending on the storage, we should have received one or two warnings (create or
        # create and modify)
        assert len(patched_logger.mock_calls) == 1 or len(patched_logger.mock_calls) == 2

    # however, syncing in the other direction should still work

    make_zip(tmpdir, [('testfile2', 'bbbb')])

    assert wait_for_file(Path(storage_dir1 / 'testfile2'), 'bbbb')
