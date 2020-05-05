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

from pathlib import PurePosixPath
import os
import shutil

import pytest

from ..manifest.loader import ManifestLoader
from ..storage.local import LocalStorage
from ..resolve import WildlandPath, PathError, resolve_local, \
    read_file, write_file


## Path


def test_path_from_str():
    wlpath = WildlandPath.from_str(':/foo/bar')
    assert wlpath.signer is None
    assert wlpath.parts == [PurePosixPath('/foo/bar')]

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux')
    assert wlpath.signer == '0xabcd'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]


def test_path_from_str_fail():
    with pytest.raises(PathError, match='has to start with signer'):
        WildlandPath.from_str('/foo/bar')

    with pytest.raises(PathError, match='Unrecognized signer field'):
        WildlandPath.from_str('foo:/foo/bar')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:')


def test_path_to_str():
    wlpath = WildlandPath('0xabcd', [PurePosixPath('/foo/bar')])
    assert str(wlpath) == '0xabcd:/foo/bar'

    wlpath = WildlandPath(None, [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')])
    assert str(wlpath) == ':/foo/bar:/baz/quux'


## Path resolution

@pytest.fixture
def setup(base_dir, cli):
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/path')
    cli('storage', 'create', 'local', 'Storage1',
        '--path', base_dir / 'storage1',
        '--container', 'Container1', '--update-container')

    cli('container', 'create', 'Container2',
        '--path', '/path/subpath',
        '--path', '/other/path')
    cli('storage', 'create', 'local', 'Storage2',
        '--path', base_dir / 'storage2',
        '--container', 'Container2', '--update-container')

    os.mkdir(base_dir / 'storage1/other/')
    # TODO copy storage manifest as well
    # (and make sure storage manifests are resolved in the local context)
    shutil.copyfile(base_dir / 'containers/Container2.yaml',
                    base_dir / 'storage1/other/path.yaml')


@pytest.fixture
def loader(setup, base_dir):
    # pylint: disable=unused-argument
    loader = ManifestLoader(base_dir=base_dir)
    try:
        loader.load_users()
        yield loader
    finally:
        loader.close()


def test_resolve_local(base_dir, loader):
    storage, relpath = resolve_local(loader, PurePosixPath('/path/foo'), '0xaaa')
    assert isinstance(storage, LocalStorage)
    assert storage.root == base_dir / 'storage1'
    assert relpath == PurePosixPath('foo')

    storage, relpath = resolve_local(loader, PurePosixPath('/path/subpath/foo'), '0xaaa')
    assert isinstance(storage, LocalStorage)
    assert storage.root == base_dir / 'storage2'
    assert relpath == PurePosixPath('foo')


def test_read_file(base_dir, loader):
    with open(base_dir / 'storage1/file.txt', 'w') as f:
        f.write('Hello world')
    data = read_file(loader, WildlandPath.from_str(':/path/file.txt'), '0xaaa')
    assert data == b'Hello world'


def test_write_file(base_dir, loader):
    write_file(b'Hello world', loader, WildlandPath.from_str(':/path/file.txt'),
               '0xaaa')
    with open(base_dir / 'storage1/file.txt') as f:
        assert f.read() == 'Hello world'


def test_read_file_traverse(base_dir, loader):
    with open(base_dir / 'storage2/file.txt', 'w') as f:
        f.write('Hello world')
    data = read_file(loader, WildlandPath.from_str(':/path:/other/path:/file.txt'), '0xaaa')
    assert data == b'Hello world'
