# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=missing-docstring,redefined-outer-name


from pathlib import Path
import os
import uuid
import zipfile

import pytest


@pytest.fixture
def storage(base_dir):
    return {
        'type': 'zip-archive',
        'owner': '0xaaaa',
        'is-local-owner': True,
        'location': str(base_dir / 'archive.zip'),
        'backend-id': str(uuid.uuid4()),
    }


def make_zip(base_dir: Path, files):
    with zipfile.ZipFile(base_dir / 'archive.zip.new', mode='w') as zf:
        for name, data in files:
            zinfo = zipfile.ZipInfo(filename=name)
            zf.writestr(zinfo, data)
    (base_dir / 'archive.zip.new').rename(base_dir / 'archive.zip')


def test_zip_fuse(base_dir, env, storage):
    make_zip(base_dir, [
        ('foo.txt', 'foo data'),
        ('dir/', ''),
        ('dir/bar.txt', 'bar data'),
    ])
    env.mount_storage(['/zip'], storage)
    assert sorted(os.listdir(env.mnt_dir / 'zip')) == ['dir', 'foo.txt']
    assert sorted(os.listdir(env.mnt_dir / 'zip/dir')) == ['bar.txt']
    assert (env.mnt_dir / 'zip/foo.txt').read_text() == 'foo data'
    assert (env.mnt_dir / 'zip/dir/bar.txt').read_text() == 'bar data'


def test_zip_watch(base_dir, env, storage):
    make_zip(base_dir, [
        ('file1.txt', 'file1 data'),
        ('file2.txt', 'file2 data'),
        ('file3.txt', 'file3 data'),
        ('other.file', 'other'),
    ])
    env.mount_storage(['/zip'], storage)
    watch_id = env.run_control_command(
        'add-watch', {'storage-id': 1, 'pattern': '*.txt'})

    make_zip(base_dir, [
        ('file1.txt', 'file1 data'),
        ('file2.txt', 'file2 data (modified)'),
        ('file4.txt', 'file4 data'),
        ('other.file', 'other file modified'),
    ])
    event = env.recv_event()
    assert event == [
        {'type': 'delete', 'path': 'file3.txt', 'watch-id': watch_id, 'storage-id': 1},
        {'type': 'create', 'path': 'file4.txt', 'watch-id': watch_id, 'storage-id': 1},
        {'type': 'modify', 'path': 'file2.txt', 'watch-id': watch_id, 'storage-id': 1},
    ]
