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
from functools import partial

import yaml
import pytest

from ..client import Client
from ..storage_backends.base import StorageBackend
from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.generated import GeneratedStorageMixin, FuncFileEntry, FuncDirEntry
from ..wlpath import WildlandPath, PathError
from ..manifest.manifest import ManifestError
from ..search import Search, storage_glob


## Path


def test_path_from_str():
    wlpath = WildlandPath.from_str(':/foo/bar:')
    assert wlpath.signer is None
    assert wlpath.parts == [PurePosixPath('/foo/bar')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux:')
    assert wlpath.signer == '0xabcd'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('@default:/foo/bar:/baz/quux:')
    assert wlpath.signer == '@default'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('@default-signer:/foo/bar:/baz/quux:')
    assert wlpath.signer == '@default-signer'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux:/some/file.txt')
    assert wlpath.signer == '0xabcd'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path == PurePosixPath('/some/file.txt')


def test_path_from_str_fail():
    with pytest.raises(PathError, match='has to start with signer'):
        WildlandPath.from_str('/foo/bar')

    with pytest.raises(PathError, match='Unrecognized signer field'):
        WildlandPath.from_str('foo:/foo/bar:')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar:')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar:baz.txt')

    with pytest.raises(PathError, match='Path has no containers'):
        WildlandPath.from_str('0xabcd:')

    with pytest.raises(PathError, match='Path has no containers'):
        WildlandPath.from_str('0xabcd:/foo')


def test_path_to_str():
    wlpath = WildlandPath('0xabcd', [PurePosixPath('/foo/bar')], None)
    assert str(wlpath) == '0xabcd:/foo/bar:'

    wlpath = WildlandPath(
        None, [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')], None)
    assert str(wlpath) == ':/foo/bar:/baz/quux:'

    wlpath = WildlandPath(
        None,
        [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')],
        PurePosixPath('/some/file.txt'))
    assert str(wlpath) == ':/foo/bar:/baz/quux:/some/file.txt'


## Path resolution

@pytest.fixture
def setup(base_dir, cli):
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')
    os.mkdir(base_dir / 'storage3')

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb', '--path', '/users/User2')

    cli('container', 'create', 'Container1', '--path', '/path')
    cli('storage', 'create', 'local', 'Storage1',
        '--path', base_dir / 'storage1',
        '--container', 'Container1',
        '--trusted')

    cli('container', 'create', 'Container2',
        '--path', '/path/subpath',
        '--path', '/other/path',
        '--path', '/unsigned')
    cli('storage', 'create', 'local', 'Storage2',
        '--path', base_dir / 'storage2',
        '--container', 'Container2')

    cli('container', 'create', 'C.User2',
        '--user', 'User2',
        '--path', '/users/User2',
        '--update-user')
    cli('storage', 'create', 'local', 'Storage3',
        '--path', base_dir / 'storage3',
        '--container', 'C.User2')

    os.mkdir(base_dir / 'storage1/other/')
    # TODO copy storage manifest as well
    # (and make sure storage manifests are resolved in the local context)
    shutil.copyfile(base_dir / 'containers/Container2.container.yaml',
                    base_dir / 'storage1/other/path.yaml')

    content = (base_dir / 'containers/Container2.container.yaml').read_text()
    content = content[content.index('---'):]
    (base_dir / 'storage1/unsigned.yaml').write_text(content)
    (base_dir / 'storage2/unsigned.yaml').write_text(content)


@pytest.fixture
def client(setup, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    client.recognize_users()
    return client


def test_resolve_first(base_dir, client):
    search = Search(client, WildlandPath.from_str(':/path:'),
        aliases={'default': '0xaaa'})
    step = list(search._resolve_first())[0]
    assert step.container.paths[1] == PurePosixPath('/path')

    _, backend = search._find_storage(step)
    assert isinstance(backend, LocalStorageBackend)
    assert backend.root == base_dir / 'storage1'

    search = Search(client, WildlandPath.from_str(':/path/subpath:'),
        aliases={'default': '0xaaa'})
    step = list(search._resolve_first())[0]
    assert step.container.paths[1] == PurePosixPath('/path/subpath')

    _, backend = search._find_storage(step)
    assert isinstance(backend, LocalStorageBackend)
    assert backend.root == base_dir / 'storage2'


def test_read_file(base_dir, client):
    with open(base_dir / 'storage1/file.txt', 'w') as f:
        f.write('Hello world')
    search = Search(client, WildlandPath.from_str(':/path:/file.txt'),
        aliases={'default': '0xaaa'})
    data = search.read_file()
    assert data == b'Hello world'


def test_write_file(base_dir, client):
    search = Search(client, WildlandPath.from_str(':/path:/file.txt'),
        aliases={'default': '0xaaa'})
    search.write_file(b'Hello world')
    with open(base_dir / 'storage1/file.txt') as f:
        assert f.read() == 'Hello world'


def test_read_file_traverse(base_dir, client):
    with open(base_dir / 'storage2/file.txt', 'w') as f:
        f.write('Hello world')
    search = Search(client,
        WildlandPath.from_str(':/path:/other/path:/file.txt'),
        aliases={'default': '0xaaa'})
    data = search.read_file()
    assert data == b'Hello world'


def test_read_container_traverse(client):
    search = Search(client, WildlandPath.from_str(':/path:/other/path:'),
        aliases={'default': '0xaaa'})
    container = search.read_container()
    assert PurePosixPath('/other/path') in container.paths


def test_read_container_unsigned(base_dir, client):
    (base_dir / 'containers/Container2.container.yaml').unlink()

    search = Search(client, WildlandPath.from_str(':/path:/unsigned:'),
        aliases={'default': '0xaaa'})
    container = search.read_container()
    assert PurePosixPath('/other/path') in container.paths

    search = Search(client,
        WildlandPath.from_str(':/path:/other/path:/unsigned:'),
        aliases={'default': '0xaaa'})
    with pytest.raises(ManifestError, match='Signature expected'):
        search.read_container()


def test_mount_traverse(cli, client, base_dir, control_client):
    # pylint: disable=unused-argument
    control_client.expect('paths', {})
    control_client.expect('mount')
    cli('container', 'mount', ':/path:/other/path:')


def test_unmount_traverse(cli, client, base_dir, control_client):
    # pylint: disable=unused-argument
    with open(base_dir / 'containers/Container2.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    control_client.expect('paths', {
        f'/.users/0xaaa{path}': [101],
    })
    control_client.expect('unmount')
    cli('container', 'unmount', ':/path:/other/path:')


@pytest.mark.parametrize('location_type', ['local', 'remote'])
def test_read_file_traverse_user(cli, base_dir, client, location_type):
    os.mkdir(base_dir / 'storage1/users/')
    shutil.copyfile(base_dir / 'users/User2.user.yaml',
                    base_dir / 'storage1/users/User2.user.yaml')

    if location_type == 'local':
        location = 'User2.user.yaml'
    else:
        location = 'file://localhost' + str(base_dir / 'users/User2.user.yaml')

    cli('bridge', 'create', '--user', 'User',
        '--ref-user', 'User2',
        '--ref-user-location', location,
        '--file-path', base_dir / 'storage1/users/User2.yaml',
        'User2')

    with open(base_dir / 'storage3/file.txt', 'w') as f:
        f.write('Hello world')
    search = Search(client,
        WildlandPath.from_str(':/path:/users/User2/:/file.txt'),
        aliases={'default': '0xaaa'})
    data = search.read_file()
    assert data == b'Hello world'


def test_read_file_traverse_user_inline_container(cli, base_dir, client):
    os.mkdir(base_dir / 'storage1/users/')
    user_path = base_dir / 'storage1/users/User2.user.yaml'

    # Load user and container manifest
    with open(base_dir / 'containers/C.User2.container.yaml') as f:
        container_dict = list(yaml.safe_load_all(f))[1]
    with open(base_dir / 'users/User2.user.yaml') as f:
        user_dict = list(yaml.safe_load_all(f))[1]

    # Remove original continer manifest (so that search doesn't use it)
    (base_dir / 'containers/C.User2.container.yaml').unlink()

    # Inline the container manifest inside user manifest
    user_dict['infrastructure-containers'] = [container_dict]

    # Save the new container to storage, sign
    with open(user_path, 'w') as f:
        yaml.dump(user_dict, f)
    cli('user', 'sign', '-i', user_path)

    # Create bridge manifest
    cli('bridge', 'create', '--user', 'User',
        '--ref-user', 'User2',
        '--ref-user-location', 'file://localhost' + str(user_path),
        '--file-path', base_dir / 'storage1/users/User2.yaml',
        'User2')

    # Try reading file
    with open(base_dir / 'storage3/file.txt', 'w') as f:
        f.write('Hello world')
    search = Search(client, WildlandPath.from_str(':/path:/users/User2/:/file.txt'),
        aliases={'default': '0xaaa'})
    data = search.read_file()
    assert data == b'Hello world'


## Manifest pattern

@pytest.fixture(params=['/manifests/*.yaml', '/manifests/{path}.yaml'])
def setup_pattern(request, base_dir, cli):
    os.mkdir(base_dir / 'storage1')

    cli('user', 'create', 'User', '--key', '0xaaa')

    cli('container', 'create', 'Container1', '--path', '/path')
    cli('storage', 'create', 'local', 'Storage1',
        '--path', base_dir / 'storage1',
        '--container', 'Container1',
        '--inline',
        '--manifest-pattern', request.param)

    cli('container', 'create', 'Container2',
        '--path', '/path1')
    cli('container', 'create', 'Container3',
        '--path', '/path2')

    os.mkdir(base_dir / 'storage1/manifests/')
    shutil.copyfile(base_dir / 'containers/Container2.container.yaml',
                    base_dir / 'storage1/manifests/path1.yaml')
    shutil.copyfile(base_dir / 'containers/Container3.container.yaml',
                    base_dir / 'storage1/manifests/path2.yaml')


def test_read_container_traverse_pattern(setup_pattern, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    client.recognize_users()

    search = Search(client, WildlandPath.from_str(':/path:/path1:'),
        aliases={'default': '0xaaa'})
    container = search.read_container()
    assert PurePosixPath('/path1') in container.paths

    search = Search(client, WildlandPath.from_str(':/path:/path2:'),
        aliases={'default': '0xaaa'})
    container = search.read_container()
    assert PurePosixPath('/path2') in container.paths


## Manifests with wildland paths

def test_container_with_storage_path(base_dir, cli):
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')

    cli('user', 'create', 'User', '--key', '0xaaa')

    cli('container', 'create', 'Container1', '--path', '/path1')
    cli('storage', 'create', 'local', 'Storage1',
        '--path', base_dir / 'storage1',
        '--container', 'Container1',
        '--inline')

    cli('container', 'create', 'Container2', '--path', '/path2')
    cli('storage', 'create', 'local', 'Storage2',
        '--path', base_dir / 'storage2',
        '--container', 'Container2')

    os.rename(
        base_dir / 'storage/Storage2.storage.yaml',
        base_dir / 'storage1/Storage2.storage.yaml')

    with open(base_dir / 'storage2/testfile', 'w') as file:
        file.write('test\n')

    with open(base_dir / 'containers/Container2.container.yaml') as file:
        lines = list(file)
    with open(base_dir / 'containers/Container2.container.yaml', 'w') as file:
        for line in lines:
            if line.startswith('  - file://'):
                line = '  - wildland:0xaaa:/path1:/Storage2.storage.yaml\n'
            file.write(line)

    cli('get', '0xaaa:/path2:/testfile')

## Wildcard matching

class TestBackend(GeneratedStorageMixin, StorageBackend):
    '''
    A data-driven storage backend for tests.
    '''

    def __init__(self, content):
        super().__init__()
        self.content = content

    def get_root(self):
        return FuncDirEntry('.', partial(self._dir, self.content))

    def _dir(self, content):
        for k, v in content.items():
            if v is None:
                yield FuncFileEntry(k, lambda: b'file')
            else:
                yield FuncDirEntry(k, partial(self._dir, v))


def test_glob_simple():
    backend = TestBackend({
        'foo': {
            'bar.yaml': None,
            'baz.yaml': None,
            'README.txt': None,
        },
        'foo2': {
            'bar.yaml': None,
        },
    })

    assert list(storage_glob(backend, '/foo/bar.yaml')) == [
        PurePosixPath('foo/bar.yaml'),
    ]
    assert list(storage_glob(backend, '/foo/*.yaml')) == [
        PurePosixPath('foo/bar.yaml'),
        PurePosixPath('foo/baz.yaml'),
    ]
    assert list(storage_glob(backend, '/*/*.yaml')) == [
        PurePosixPath('foo/bar.yaml'),
        PurePosixPath('foo/baz.yaml'),
        PurePosixPath('foo2/bar.yaml'),
    ]