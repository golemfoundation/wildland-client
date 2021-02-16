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

# pylint: disable=missing-docstring,redefined-outer-name

'''
Tests for conflict resolution
'''

from pathlib import PurePosixPath
import stat
import errno

import pytest

from ..conflict import ConflictResolver
from ..storage_backends.base import Attr


class TestFS(ConflictResolver):
    def __init__(self, *storages):
        super().__init__()
        self.storages = storages
        for ident, (mount_path, _data) in enumerate(self.storages):
            self.mount(mount_path, ident)

    @staticmethod
    def get(data, relpath):
        for name in relpath.parts:
            if not isinstance(data, dict) or name not in data:
                raise FileNotFoundError(errno.ENOENT, '')
            data = data[name]
        return data

    def storage_getattr(self, ident, relpath):
        _, data = self.storages[ident]
        data = self.get(data, relpath)
        if isinstance(data, dict):
            return Attr(mode=stat.S_IFDIR | 0o755)
        return Attr(mode=stat.S_IFREG | 0o644)

    def storage_readdir(self, ident, relpath):
        _, data = self.storages[ident]
        data = self.get(data, relpath)
        if not isinstance(data, dict):
            raise NotADirectoryError()
        return list(data.keys())

    # Test helpers

    def dir(self, path: str):
        return self.readdir(PurePosixPath(path))

    def mode(self, path: str):
        return self.getattr(PurePosixPath(path)).mode


def test_simple():
    fs = TestFS(
        (PurePosixPath('/mount1/mount2'), {
            'file1': None,
            'dir1': {
                'file2': None,
            }
        }),
    )

    assert fs.dir('/') == ['mount1']
    assert fs.dir('/mount1') == ['mount2']
    assert fs.dir('/mount1/mount2') == ['dir1', 'file1']
    assert fs.dir('/mount1/mount2/dir1') == ['file2']
    with pytest.raises(FileNotFoundError):
        fs.dir('/other')
    with pytest.raises(FileNotFoundError):
        fs.dir('/mount1/mount2/other')
    with pytest.raises(NotADirectoryError):
        fs.dir('/mount1/mount2/file1')

    assert fs.mode('/') == stat.S_IFDIR | 0o555
    assert fs.mode('/mount1') == stat.S_IFDIR | 0o555
    assert fs.mode('/mount1/mount2') == stat.S_IFDIR | 0o755
    assert fs.mode('/mount1/mount2/file1') == stat.S_IFREG | 0o644

    with pytest.raises(FileNotFoundError):
        fs.mode('/other')
    with pytest.raises(FileNotFoundError):
        fs.mode('/mount1/mount2/other')
    with pytest.raises(FileNotFoundError):
        fs.mode('/mount1/mount2/file1.wl_0')


def test_readdir_separate_storages():
    fs = TestFS(
        (PurePosixPath('/mount1/mount2'), {
            'file1': None,
        }),
        (PurePosixPath('/mount1/mount3'), {
            'file2': None,
        }),
    )

    assert fs.dir('/') == ['mount1']
    assert fs.dir('/mount1') == ['mount2', 'mount3']
    assert fs.dir('/mount1/mount2') == ['file1']
    assert fs.dir('/mount1/mount3') == ['file2']

    assert fs.mode('/mount1') == stat.S_IFDIR | 0o555
    assert fs.mode('/mount1/mount2') == stat.S_IFDIR | 0o755
    assert fs.mode('/mount1/mount2/file1') == stat.S_IFREG | 0o644

    with pytest.raises(FileNotFoundError):
        fs.mode('/mount1/mount2/file1.0')


def test_readdir_merged_storages():
    fs = TestFS(
        (PurePosixPath('/mount1/mount2'), {
            'file0.xyz.jpg': None,
            'file1.txt': None,
            'file2': None,
            'dir': {
                'file3': None,
                'file4': None,
                'file6': None
            },
        }),
        (PurePosixPath('/mount1/mount2'), {
            'file0.xyz.jpg': None,
            'file1.txt': None,
            'file3': None,
            'dir': {
                'file3': None,
                'file5': None,
                'file6.txt': None
            },
        }),
    )

    assert fs.dir('/') == ['mount1']
    assert fs.dir('/mount1') == ['mount2']
    assert fs.dir('/mount1/mount2') == [
        'dir',
        'file0.xyz.wl_0.jpg', 'file0.xyz.wl_1.jpg',
        'file1.wl_0.txt', 'file1.wl_1.txt',
        'file2', 'file3',
    ]
    assert fs.dir('/mount1/mount2/dir') == [
        'file3.wl_0',
        'file3.wl_1',
        'file4',
        'file5',
        'file6',
        'file6.txt',
    ]

    with pytest.raises(FileNotFoundError):
        fs.dir('/mount1/mount2/other')
    with pytest.raises(FileNotFoundError):
        fs.dir('/mount1/mount2/file1')
    with pytest.raises(NotADirectoryError):
        fs.dir('/mount1/mount2/file2')

    assert fs.mode('/mount1/mount2/dir') == stat.S_IFDIR | 0o555
    assert fs.mode('/mount1/mount2/file0.xyz.wl_0.jpg') == stat.S_IFREG | 0o0644
    assert fs.mode('/mount1/mount2/file1.wl_0.txt') == stat.S_IFREG | 0o0644
    assert fs.mode('/mount1/mount2/file1.wl_1.txt') == stat.S_IFREG | 0o0644
    assert fs.mode('/mount1/mount2/file2') == stat.S_IFREG | 0o0644

    with pytest.raises(FileNotFoundError):
        fs.mode('/mount1/mount2/file1')
    with pytest.raises(FileNotFoundError):
        fs.mode('/mount1/mount2/file2.wl_0')


def test_readdir_file_and_dir():
    fs = TestFS(
        (PurePosixPath('/mount1'), {
            'file1': None,
            'file2': None,
            'file3': {
                'file4': None,
                'file5': None
            },
        }),
        (PurePosixPath('/mount1'), {
            'file3': {
                'file4': None,
                'file6': None,
            }
        }),
        (PurePosixPath('/mount1'), {
            'file3': None,
        }),
        (PurePosixPath('/mount1'), {
            'file3': None,
        }),
    )

    assert fs.dir('/') == ['mount1']
    assert fs.dir('/mount1') == [
        'file1',
        'file2',
        'file3',
        'file3.wl_2',
        'file3.wl_3',
    ]
    assert fs.dir('/mount1/file3') == [
        'file4.wl_0',
        'file4.wl_1',
        'file5',
        'file6',
    ]


def test_readdir_mounted_subdir():
    fs = TestFS(
        (PurePosixPath('/foo'), {
            'dir1': {},
            'file1': None,
        }),
        (PurePosixPath('/foo/bar/baz'), {
            'dir2': {},
            'file2': None,
        }),
    )

    assert fs.dir('/') == ['foo']
    assert fs.dir('/foo') == ['bar', 'dir1', 'file1']

    # This should return 'baz' even though the only 'real' storage will reply
    # ENOENT for the 'bar' directory.
    assert fs.dir('/foo/bar') == ['baz']

    assert fs.dir('/foo/bar/baz') == ['dir2', 'file2']
