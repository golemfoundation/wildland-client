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

# pylint: disable=missing-docstring,redefined-outer-name,too-many-lines

from pathlib import PurePosixPath
import os
import re
import uuid
import shutil
from functools import partial
from unittest import mock

import yaml
import pytest

from .utils import PartialDict, str_re
from ..client import Client
from ..storage_backends.base import StorageBackend
from ..storage_backends.local import LocalStorageBackend
from ..storage_backends.generated import GeneratedStorageMixin, FuncFileEntry, FuncDirEntry
from ..wlpath import WildlandPath, PathError
from ..search import Search, storage_glob
from ..config import Config
from ..utils import load_yaml_all
from ..exc import WildlandError

## Path


def test_path_from_str():
    wlpath = WildlandPath.from_str(':/foo/bar:')
    assert wlpath.owner is None
    assert wlpath.hint is None
    assert wlpath.parts == [PurePosixPath('/foo/bar')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux:')
    assert wlpath.owner == '0xabcd'
    assert wlpath.hint is None
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('@default:/foo/bar:/baz/quux:')
    assert wlpath.owner == '@default'
    assert wlpath.hint is None
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('@default-owner:/foo/bar:/baz/quux:')
    assert wlpath.owner == '@default-owner'
    assert wlpath.hint is None
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path is None

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux:/some/file.txt')
    assert wlpath.owner == '0xabcd'
    assert wlpath.hint is None
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path == PurePosixPath('/some/file.txt')

    wlpath = WildlandPath.from_str('0xabcd@https{my.address}:/foo/bar:/baz/quux:/some/file.txt')
    assert wlpath.owner == '0xabcd'
    assert wlpath.hint == 'https://my.address'
    assert wlpath.parts == [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')]
    assert wlpath.file_path == PurePosixPath('/some/file.txt')


def test_path_from_str_fail():
    with pytest.raises(PathError, match='has to start with owner'):
        WildlandPath.from_str('/foo/bar')

    with pytest.raises(PathError, match='Unrecognized owner field'):
        WildlandPath.from_str('foo:/foo/bar:')

    with pytest.raises(PathError, match='Hint field requires explicit owner'):
        WildlandPath.from_str('@https{my.address}:foo/bar:baz.txt')

    with pytest.raises(PathError, match='Hint field requires explicit owner'):
        WildlandPath.from_str('@default@https{my.address}:foo/bar:baz.txt')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar:')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar:baz.txt')

    with pytest.raises(PathError, match='Path has no containers'):
        WildlandPath.from_str('0xabcd:')

    with pytest.raises(PathError, match='Path has no containers'):
        WildlandPath.from_str('0xabcd:/foo')


def test_path_to_str():
    wlpath = WildlandPath('0xabcd', None, [PurePosixPath('/foo/bar')], None)
    assert str(wlpath) == '0xabcd:/foo/bar:'

    wlpath = WildlandPath('0xabcd', 'https://my.address', [PurePosixPath('/foo/bar')], None)
    assert str(wlpath) == '0xabcd@https{my.address}:/foo/bar:'

    wlpath = WildlandPath(
        None, None, [PurePosixPath('/foo/bar'), PurePosixPath('/baz/quux')], None)
    assert str(wlpath) == ':/foo/bar:/baz/quux:'

    wlpath = WildlandPath(
        None, None,
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

    cli('container', 'create', 'Container1', '--path', '/path',
        '--path', '/.uuid/0000000000-1111-0000-1111-000000000000',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container1',
        '--manifest-pattern', '/{path}.yaml',
        '--trusted', '--no-inline')

    cli('container', 'create', 'Container2', '--no-encrypt-manifest',
        '--path', '/.uuid/0000000000-1111-1111-1111-000000000000',
        '--path', '/path/subpath',
        '--path', '/other/path',
        '--path', '/unsigned')
    cli('storage', 'create', 'local', 'Storage2',
        '--location', base_dir / 'storage2',
        '--container', 'Container2', '--no-inline')

    cli('container', 'create', 'C.User2',
        '--path', '/.uuid/0000000000-2222-0000-1111-000000000000',
        '--user', 'User2',
        '--path', '/users/User2',
        '--update-user', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage3',
        '--location', base_dir / 'storage3',
        '--container', 'C.User2', '--no-inline')

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
    return client


def test_resolve_first(base_dir, client):
    # pylint: disable=protected-access
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
    container = next(search.read_container())
    assert PurePosixPath('/other/path') in container.paths


def test_read_container_unsigned(base_dir, client):
    (base_dir / 'containers/Container2.container.yaml').unlink()

    search = Search(client, WildlandPath.from_str(':/path:/unsigned:'),
        aliases={'default': '0xaaa'})
    container = next(search.read_container())
    assert PurePosixPath('/other/path') in container.paths

    search = Search(client,
        WildlandPath.from_str(':/path:/other/path:/unsigned:'),
        aliases={'default': '0xaaa'})

    with mock.patch('wildland.search.logger.warning') as mock_logger:
        with pytest.raises(StopIteration):
            next(search.read_container())
        assert mock_logger.call_count == 1
        mock_logger.assert_called_with('%s: cannot load manifest file %s: %s',
                                       PurePosixPath('/unsigned'), mock.ANY, mock.ANY)


def test_mount_traverse(cli, client, base_dir, control_client):
    # pylint: disable=unused-argument
    control_client.expect('paths', {})
    control_client.expect('mount')
    control_client.expect('status', {})
    cli('container', 'mount', ':/path:/other/path:')


def test_unmount_traverse(cli, client, base_dir, control_client):
    # pylint: disable=unused-argument
    cont_path = base_dir / 'containers/Container2.container.yaml'
    uuid = re.search(r'/.uuid/(.+?)\n', cont_path.read_text()).group(1)

    control_client.expect('paths', {
        f'/.users/0xaaa:/{uuid}': [101],
        f'/.users/0xaaa:/.backends/{uuid}/0000-1111-2222-3333-4444': [102],
        f'/.uuid/{uuid}': [103],
        f'/.backends/{uuid}/0000-1111-2222-3333-4444': [104],
    })
    control_client.expect('unmount')
    control_client.expect('status', {})
    cli('container', 'unmount', ':/path:/other/path:', '--without-subcontainers')


def test_read_file_traverse_user(cli, base_dir, client):
    os.mkdir(base_dir / 'storage1/users/')
    shutil.copyfile(base_dir / 'users/User2.user.yaml',
                    base_dir / 'storage1/users/User2.user.yaml')

    cli('bridge', 'create', '--owner', 'User',
        '--ref-user', 'User2',
        '--ref-user-location', 'file://localhost' + str(base_dir / 'users/User2.user.yaml'),
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
        container_dict = list(load_yaml_all(f))[1]
    with open(base_dir / 'users/User2.user.yaml') as f:
        user_dict = list(load_yaml_all(f))[1]

    # Remove original continer manifest (so that search doesn't use it)
    (base_dir / 'containers/C.User2.container.yaml').unlink()

    # Inline the container manifest inside user manifest
    user_dict['infrastructures'] = [container_dict]

    # Save the new container to storage, sign
    with open(user_path, 'w') as f:
        yaml.dump(user_dict, f)
    cli('user', 'sign', '-i', user_path)

    # Create bridge manifest
    cli('bridge', 'create', '--owner', 'User',
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

    cli('container', 'create', 'Container1', '--path', '/path', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container1',
        '--manifest-pattern', request.param)

    cli('container', 'create', 'Container2',
        '--path', '/.uuid/0000000000-0000-0000-2222-000000000000',
        '--path', '/path1', '--no-encrypt-manifest')
    cli('container', 'create', 'Container3',
        '--path', '/.uuid/0000000000-0000-0000-3333-000000000000',
        '--path', '/path2', '--no-encrypt-manifest')

    os.mkdir(base_dir / 'storage1/manifests/')
    shutil.copyfile(base_dir / 'containers/Container2.container.yaml',
                    base_dir / 'storage1/manifests/path1.yaml')
    shutil.copyfile(base_dir / 'containers/Container3.container.yaml',
                    base_dir / 'storage1/manifests/path2.yaml')
    if '{path}' in request.param:
        os.mkdir(base_dir / 'storage1/manifests/.uuid/')
        shutil.copyfile(
            base_dir / 'containers/Container2.container.yaml',
            base_dir / 'storage1/manifests/.uuid/0000000000-0000-0000-2222-000000000000.yaml')
        shutil.copyfile(
            base_dir / 'containers/Container3.container.yaml',
            base_dir / 'storage1/manifests/.uuid/0000000000-0000-0000-3333-000000000000.yaml')


def test_read_container_traverse_pattern(setup_pattern, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)

    search = Search(client, WildlandPath.from_str(':/path:/path1:'),
        aliases={'default': '0xaaa'})
    container = next(search.read_container())
    assert PurePosixPath('/path1') in container.paths

    search = Search(client, WildlandPath.from_str(':/path:/path2:'),
        aliases={'default': '0xaaa'})
    container = next(search.read_container())
    assert PurePosixPath('/path2') in container.paths

def test_read_container_wildcard(setup_pattern, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)

    search = Search(client, WildlandPath.from_str(':/path:*:'),
        aliases={'default': '0xaaa'})
    containers = list(search.read_container())
    assert len(containers) == 2
    paths = sorted([p for p in c.paths if '/path' in str(p)]
                   for c in containers)
    assert paths == [[PurePosixPath('/path1')], [PurePosixPath('/path2')]]


## Manifests with wildland paths

def test_container_with_storage_path(base_dir, cli):
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')

    cli('user', 'create', 'User', '--key', '0xaaa')

    cli('container', 'create', 'Container1', '--path', '/path1', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container1')

    cli('container', 'create', 'Container2', '--path', '/path2', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage2',
        '--location', base_dir / 'storage2',
        '--container', 'Container2', '--no-inline')

    os.rename(
        base_dir / 'storage/Storage2.storage.yaml',
        base_dir / 'storage1/Storage2.storage.yaml')

    with open(base_dir / 'storage2/testfile', 'w') as file:
        file.write('test\n')

    data = (base_dir / 'containers/Container2.container.yaml').read_text()
    data = re.sub(r'file://(.+?)\n',
                  r'wildland:0xaaa:/path1:/Storage2.storage.yaml\n', data)
    (base_dir / 'containers/Container2.container.yaml').write_text(data)

    cli('get', '0xaaa:/path2:/testfile')

## Wildcard matching

class TestBackend(GeneratedStorageMixin, StorageBackend):
    """
    A data-driven storage backend for tests.
    """

    def __init__(self, content):
        super().__init__(params={'backend-id': str(uuid.uuid4()), 'type': ''})
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


# Multiple pubkeys

def modify_file(path, pattern, replacement):
    with open(path) as f:
        data = f.read()
    assert pattern in data
    data = data.replace(pattern, replacement)
    with open(path, 'w') as f:
        f.write(data)


@pytest.mark.parametrize('owner', ['0xfff', '0xbbb'])
def test_traverse_other_key(cli, base_dir, client, owner, caplog):
    cli('user', 'create', 'KnownUser', '--key', '0xddd', '--add-pubkey', 'key.0xfff')

    client.recognize_users_and_bridges()
    client.config = Config.load(base_dir)

    storage_path = base_dir / 'storage3'
    (base_dir / 'storage3/.wildland-owners').write_bytes(b'0xfff\n')
    os.mkdir(base_dir / 'storage1/users/')

    remote_user_file = base_dir / 'storage1/users/DummyUser.user.yaml'

    user_data = f'''\
signature: |
  dummy.{owner}
---
object: user
owner: '0xfff'
paths:
- /users/User2
pubkeys:
- key.0xbbb
infrastructures:
 - object: container
   owner: '0xfff'
   paths:
    - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
   backends:
    storage:
     - object: storage
       type: local
       location: {storage_path}
       owner: '0xfff'
       container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
       backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a89e2'
       manifest-pattern:
        type: glob
        path: /manifests/{{path}}/*.yaml
'''.encode()

    remote_user_file.write_bytes(user_data)

    bridge_file = base_dir / 'bridges/TestBridge1.bridge.yaml'
    bridge_file.write_bytes(f"""\
signature: |
  dummy.0xddd
---
object: 'bridge'
owner: '0xddd'
user: file://localhost{remote_user_file}
pubkey: 'key.0xfff'
paths:
- /path
""".encode())

    with open(base_dir / 'storage3/file.txt', 'w') as f:
        f.write('Hello world')

    search = Search(client,
        WildlandPath.from_str(':/path:/file.txt'),
        aliases={'default': '0xddd'})

    if owner == '0xfff':
        data = search.read_file()
        assert data == b'Hello world'

    elif owner == '0xbbb':
        with pytest.raises(FileNotFoundError):
            data = search.read_file()
        logs = '\n'.join(r.getMessage() for r in caplog.records)
        assert "Manifest owner does not have access to signing key" in logs


@pytest.mark.parametrize('owner', ['0xfff', '0xbbb'])
def test_traverse_bridge_link(cli, base_dir, client, owner, caplog):
    cli('user', 'create', 'KnownUser', '--key', '0xddd')

    client.recognize_users_and_bridges()
    client.config = Config.load(base_dir)

    storage_path = base_dir / 'storage3'
    (base_dir / 'storage3/.wildland-owners').write_bytes(b'0xfff\n')
    os.mkdir(base_dir / 'storage1/users/')

    remote_user_dir = base_dir / 'storage1/'
    (remote_user_dir / 'users/').mkdir(parents=True, exist_ok=True)
    remote_user_file = remote_user_dir / 'users/DummyUser.user.yaml'

    user_data = f'''\
signature: |
  dummy.{owner}
---
object: user
owner: '0xfff'
paths:
- /users/User2
pubkeys:
- key.0xbbb
infrastructures:
 - object: container
   owner: '0xfff'
   paths:
    - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
   backends:
    storage:
     - object: storage
       type: local
       location: {storage_path}
       owner: '0xfff'
       container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
       backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a89e2'
       manifest-pattern:
        type: glob
        path: /manifests/{{path}}/*.yaml
'''.encode()

    remote_user_file.write_bytes(user_data)

    bridge_file = base_dir / 'bridges/TestBridge1.bridge.yaml'
    bridge_file.write_bytes(f"""\
signature: |
  dummy.0xddd
---
object: 'bridge'
owner: '0xddd'
user:
  object: link
  storage:
    object: storage
    type: local
    location: {remote_user_dir}
    backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a8999'
  file: '/users/DummyUser.user.yaml'
pubkey: 'key.0xfff'
paths:
- /path
""".encode())

    (remote_user_dir / '.wildland-owners').write_bytes(b'0xfff\n')

    with open(base_dir / 'storage3/file.txt', 'w') as f:
        f.write('Hello world')

    search = Search(client,
        WildlandPath.from_str(':/path:/file.txt'),
        aliases={'default': '0xddd'})

    if owner == '0xfff':
        data = search.read_file()
        assert data == b'Hello world'

    elif owner == '0xbbb':
        with pytest.raises(FileNotFoundError):
            data = search.read_file()
        logs = '\n'.join(r.getMessage() for r in caplog.records)
        assert "Manifest owner does not have access to signing key" in logs


@pytest.mark.parametrize('owner', ['0xfff', '0xbbb'])
def test_traverse_linked_infra(cli, base_dir, client, owner, caplog):
    cli('user', 'create', 'KnownUser', '--key', '0xddd', '--add-pubkey', 'key.0xfff')

    client.recognize_users_and_bridges()
    client.config = Config.load(base_dir)

    storage_path = base_dir / 'storage3'
    (base_dir / 'storage3/.wildland-owners').write_bytes(b'0xfff\n')
    os.mkdir(base_dir / 'storage1/users/')

    container_data = f'''\
signature: |
  dummy.{owner}
---
object: container
owner: '0xfff'
paths:
- /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
backends:
  storage:
   - object: storage
     type: local
     location: {storage_path}
     owner: '0xfff'
     container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
     backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a89e2'
     manifest-pattern:
      type: glob
      path: /manifests/{{path}}/*.yaml
'''.encode()

    infra_storage_path = base_dir / 'storage_infra'
    infra_storage_path.mkdir()
    (infra_storage_path / 'cont.yaml').write_bytes(container_data)

    remote_user_file = base_dir / 'storage1/users/DummyUser.user.yaml'

    user_data = f'''\
signature: |
  dummy.{owner}
---
object: user
owner: '0xfff'
paths:
- /users/User2
pubkeys:
- key.0xbbb
infrastructures:
 - object: link
   file: '/cont.yaml'
   storage:
     object: storage
     type: local
     location: {infra_storage_path}
     backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a8933'
'''.encode()

    remote_user_file.write_bytes(user_data)

    bridge_file = base_dir / 'bridges/TestBridge1.bridge.yaml'
    bridge_file.write_bytes(f"""\
signature: |
  dummy.0xddd
---
object: 'bridge'
owner: '0xddd'
user: file://localhost{remote_user_file}
pubkey: 'key.0xfff'
paths:
- /path
""".encode())

    with open(base_dir / 'storage3/file.txt', 'w') as f:
        f.write('Hello world')

    search = Search(client,
        WildlandPath.from_str(':/path:/file.txt'),
        aliases={'default': '0xddd'})

    if owner == '0xfff':
        with pytest.raises(PermissionError):
            data = search.read_file()
        (infra_storage_path / '.wildland-owners').write_bytes(b'0xfff\n')
        data = search.read_file()
        assert data == b'Hello world'

    elif owner == '0xbbb':
        with pytest.raises(FileNotFoundError):
            data = search.read_file()
        logs = '\n'.join(r.getMessage() for r in caplog.records)
        assert "Manifest owner does not have access to signing key" in logs


def test_search_two_containers(base_dir, cli):
    os.mkdir(base_dir / 'storage1')

    cli('user', 'create', 'User', '--key', '0xaaa')

    cli('container', 'create', 'Container1', '--path', '/path1')
    cli('container', 'create', 'Container2', '--path', '/path1')

    cli('storage', 'create', 'local', 'Storage1',
        '--location', base_dir / 'storage1',
        '--container', 'Container2')

    (base_dir / 'test').write_text('testdata')

    cli('put', (base_dir / 'test'), '0xaaa:/path1:/test')

    output = cli('get', '0xaaa:/path1:/test', capture=True)

    assert output == 'testdata'


def test_search_different_default_user(base_dir, cli):
    os.mkdir(base_dir / 'storage1')
    os.mkdir(base_dir / 'storage2')

    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')

    cli('container', 'create', 'AliceContainer', '--path', '/Alice')
    cli('container', 'create', 'BobContainer', '--user', 'Bob', '--path', '/Bob')

    cli('storage', 'create', 'local', 'AliceStorage',
        '--location', base_dir / 'storage1',
        '--container', 'AliceContainer')
    cli('storage', 'create', 'local', 'BobStorage',
        '--location', base_dir / 'storage2',
        '--container', 'BobContainer')

    (base_dir / 'test').write_text('testdata')

    cli('start', '--default-user', 'Bob')
    cli('put', (base_dir / 'test'), '@default:/Bob:/test')

    output = cli('get', '0xbbb:/Bob:/test', capture=True)
    assert output == 'testdata'

DUMMY_BACKEND_UUID = '00000000-0000-0000-000000000000'

@pytest.fixture
def two_users_infra(base_dir, cli, control_client):
    """
    Create this structure:
      KnownUser(0xaaa):
        - infra: base_dir / infra-known-user
          - /users/User2: bridge -> Dummy2 (0xbbb):
            - infra: base_dir / infra2 (pattern: {path})
              - /containers/c1 -> base_dir / storage-user2-1
                - test1.txt: test1
                - test2.txt: test2
              - /containers/c2 -> base_dir / storage-user2-2
                - test3.txt: test3
          - /users/User3: bridge -> Dummy3 (0xccc):
            - infra: base_dir / infra3 (pattern: *)
              - /containers/c1 -> base_dir / storage-user3-1
                - test1.txt: 42
              - /containers/c2 -> base_dir / storage-user3-2
                - test2.txt: 42
    """
    control_client.expect('status', {})
    keys = {
        'KnownUser': '0xaaa',
        'Dummy2': '0xbbb',
        'Dummy3': '0xccc',
    }
    cli('user', 'create', 'KnownUser', '--key', keys['KnownUser'])
    cli('user', 'create', 'Dummy2', '--key', keys['Dummy2'])
    cli('user', 'create', 'Dummy3', '--key', keys['Dummy3'])

    def container_with_files(owner, name, wlpaths, location, files, c_args=(), s_args=()):
        cli('container', 'create', name, '--owner', owner,
            *['--path=' + wlpath for wlpath in wlpaths],
            '--no-encrypt-manifest', *c_args)
        cli('storage', 'create', 'local', '--container', name,
            '--location', str(location), *s_args)
        manifest_path = base_dir / 'containers' / (name + '.container.yaml')
        manifest_text = manifest_path.read_text()
        manifest_text = re.sub(r"backend-id: .*\n",
                               f"backend-id: '{DUMMY_BACKEND_UUID}'\n",
                               manifest_text)
        manifest_path.write_text(manifest_text)
        location.mkdir(parents=True, exist_ok=True)
        with open(location / '.wildland-owners', 'a') as f:
            f.write(keys[owner] + '\n')
        for filename, content in files.items():
            (location / filename).parent.mkdir(parents=True, exist_ok=True)
            (location / filename).write_text(content)
        return manifest_text

    uuid_dummy2_c1 = '00000000-2222-1111-0000-000000000000'
    manifest_dummy2_c1 = container_with_files(
        'Dummy2', 'dummy2-c1', ['/containers/c1', f'/.uuid/{uuid_dummy2_c1}'],
        base_dir / 'storage-user2-c1',
        {'test1.txt': 'test1',
         'test2.txt': 'test2'})
    uuid_dummy2_c2 = '00000000-2222-2222-0000-000000000000'
    manifest_dummy2_c2 = container_with_files(
        'Dummy2', 'dummy2-c2', ['/containers/c2', f'/.uuid/{uuid_dummy2_c2}'],
        base_dir / 'storage-user2-c2',
        {'test3.txt': 'test3'})
    uuid_dummy3_c1 = '00000000-3333-1111-0000-000000000000'
    manifest_dummy3_c1 = container_with_files(
        'Dummy3', 'dummy3-c1', ['/containers/c1', f'/.uuid/{uuid_dummy3_c1}'],
        base_dir / 'storage-user3-c1',
        {'test1.txt': '42'})
    uuid_dummy3_c2 = '00000000-3333-2222-0000-000000000000'
    manifest_dummy3_c2 = container_with_files(
        'Dummy3', 'dummy3-c2', ['/containers/c2', f'/.uuid/{uuid_dummy3_c2}'],
        base_dir / 'storage-user3-c2',
        {'test1.txt': '42'})

    # now infra containers
    (base_dir / 'manifests').mkdir(parents=True, exist_ok=True)
    (base_dir / 'manifests/.wildland-owners').write_text('0xaaa\n0xbbb\n0xccc\n')

    manifest = container_with_files(
        'Dummy2', 'dummy2-infra', ['/.infra', '/.uuid/00000000-2222-0000-0000-000000000000'],
        base_dir / 'infra2',
        {'containers/c1.yaml': manifest_dummy2_c1,
         'containers/c2.yaml': manifest_dummy2_c2,
         f'.uuid/{uuid_dummy2_c1}.yaml': manifest_dummy2_c1,
         f'.uuid/{uuid_dummy2_c2}.yaml': manifest_dummy2_c2},
        s_args=('--manifest-pattern', '/{path}.yaml'),
    )
    infra_path = (base_dir / 'manifests/dummy2-infra.yaml')
    infra_path.write_text(manifest)
    cli('user', 'modify', 'add-infrastructure', '--path', f'file://{infra_path}', 'Dummy2')

    manifest = container_with_files(
        'Dummy3', 'dummy3-infra', ['/.infra', '/.uuid/00000000-3333-0000-0000-000000000000'],
        base_dir / 'infra3',
        {'c1.yaml': manifest_dummy3_c1,
         'c2.yaml': manifest_dummy3_c2},
        s_args=('--manifest-pattern', '/*.yaml'),
    )
    infra_path = (base_dir / 'manifests/dummy3-infra.yaml')
    infra_path.write_text(manifest)
    cli('user', 'modify', 'add-infrastructure', '--path', f'file://{infra_path}', 'Dummy3')

    # and finally bridges
    container_with_files(
        'KnownUser', 'infra-known', ['/.infra', '/.uuid/00000000-1111-0000-0000-000000000000'],
        base_dir / 'infra-known', {},
        s_args=('--manifest-pattern', '/{path}.yaml'),
        c_args=('--update-user',),
    )
    (base_dir / 'infra-known/users').mkdir()
    cli('bridge', 'create', '--owner', 'KnownUser',
        '--ref-user', 'Dummy2',
        '--ref-user-path', '/users/User2',
        '--ref-user-location', f'file://{base_dir}/manifests/user2.yaml',
        '--file-path', f'{base_dir}/infra-known/users/User2.yaml')
    cli('bridge', 'create', '--owner', 'KnownUser',
        '--ref-user', 'Dummy3',
        '--ref-user-path', '/users/User3',
        '--ref-user-location', f'file://{base_dir}/manifests/user3.yaml',
        '--file-path', f'{base_dir}/infra-known/users/User3.yaml')

    # all manifests done; now move them out of standard WL config,
    # so Search() will really have some work to do
    print((base_dir / 'users/Dummy2.user.yaml').read_text())
    shutil.move(base_dir / 'users/Dummy2.user.yaml', base_dir / 'manifests/user2.yaml')
    shutil.move(base_dir / 'users/Dummy3.user.yaml', base_dir / 'manifests/user3.yaml')
    # container manifests are already published to relevant infra, remove them
    for f in (base_dir / 'containers').glob('dummy*.yaml'):
        f.unlink()


@pytest.fixture
def client2(two_users_infra, base_dir):
    # pylint: disable=unused-argument
    client = Client(base_dir=base_dir)
    return client


def test_traverse_with_fs_client_empty(client2, control_client):
    control_client.expect('status', {})
    search = Search(client2,
        WildlandPath.from_str(':/users/User2:/containers/c1:/test1.txt'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    data = search.read_file()
    assert data == b'test1'


def test_traverse_with_fs_client_mounted(base_dir, control_client, client2):
    control_client.expect('status', {})

    # simulate mounted infrastructure
    user2_infra_mount_path = base_dir / 'mnt' / \
        f'.users/0xbbb:/.backends/00000000-2222-0000-0000-000000000000/{DUMMY_BACKEND_UUID}'
    user2_infra_mount_path.parent.mkdir(parents=True)
    user2_infra_mount_path.symlink_to(base_dir / 'infra2')

    search = Search(client2,
        WildlandPath.from_str(':/users/User2:/containers/c1:/test1.txt'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    with mock.patch('wildland.storage_backends.base.StorageBackend.from_params',
                    wraps=StorageBackend.from_params) as mock_storage_backend:
        data = search.read_file()
        assert data == b'test1'
        mock_storage_backend.assert_any_call(PartialDict({
            'type': 'local',
            'location': user2_infra_mount_path
        }))
        # check if infra container was _not_ accessed directly
        direct_access = mock.call(PartialDict({'location': str(base_dir / 'infra2')}))
        assert direct_access not in mock_storage_backend.mock_calls


def test_traverse_container_with_fs_client_mounted(
        base_dir, control_client, client2):
    control_client.expect('status', {})

    # simulate mounted infrastructure
    user2_infra_mount_path = base_dir / 'mnt' / \
        f'.users/0xbbb:/.backends/00000000-2222-0000-0000-000000000000/{DUMMY_BACKEND_UUID}'
    user2_infra_mount_path.parent.mkdir(parents=True)
    user2_infra_mount_path.symlink_to(base_dir / 'infra2')

    user1_infra_mount_path = base_dir / 'mnt' / \
        f'.users/0xaaa:/.backends/00000000-1111-0000-0000-000000000000/{DUMMY_BACKEND_UUID}'
    user1_infra_mount_path.parent.mkdir(parents=True)
    user1_infra_mount_path.symlink_to(base_dir / 'infra-known')

    search = Search(client2,
        WildlandPath.from_str(':/users/User2:/containers/c1:'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    with mock.patch('wildland.storage_backends.base.StorageBackend.from_params',
                    wraps=StorageBackend.from_params) as mock_storage_backend:
        containers = list(search.read_container())
        assert len(containers) == 1
        assert containers[0].owner == '0xbbb'
        assert PurePosixPath('/containers/c1') in containers[0].paths

        assert len(mock_storage_backend.mock_calls) == 2
        mock_storage_backend.assert_any_call(PartialDict({
            'type': 'local',
            'location': user2_infra_mount_path
        }))
        mock_storage_backend.assert_any_call(PartialDict({
            'type': 'local',
            'location': user1_infra_mount_path
        }))
        # check if infra container was _not_ accessed directly
        direct_access = mock.call(PartialDict({'location': str(base_dir / 'infra2')}))
        assert direct_access not in mock_storage_backend.mock_calls


def test_get_watch_params_not_mounted(control_client, client2):
    control_client.expect('status', {})
    search = Search(client2,
        WildlandPath.from_str(':/users/User2:/containers/c1:/test1.txt'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    control_client.expect('paths', {})

    mount_cmds, patterns = search.get_watch_params()
    assert len(mount_cmds) == 3
    assert len(patterns) == 3

    expected_patterns_re = [
        str_re(r'^/.users/0xaaa:/.backends/00000000-1111-0000-.*/users/User2.yaml'),
        str_re(r'^/.users/0xbbb:/.backends/00000000-2222-0000-.*/containers/c1.yaml'),
        str_re(r'^/.users/0xbbb:/.backends/00000000-2222-1111-.*/test1.txt'),
    ]
    assert sorted(patterns) == expected_patterns_re
    expected_mounts = [
        # owner, uuid
        ('0xaaa', '00000000-1111-0000-0000-000000000000'),
        ('0xbbb', '00000000-2222-0000-0000-000000000000'),
        ('0xbbb', '00000000-2222-1111-0000-000000000000'),
    ]
    sort_key = lambda cmd: f'{cmd[0].owner}:{cmd[0].paths[0]}'
    sorted_commands = sorted(mount_cmds, key=sort_key)
    # generator here would make failure message much less useful
    # pylint: disable=use-a-generator
    assert all([
        (c[0].owner == e[0] and c[0].ensure_uuid() == e[1]  # container
         and len(c[1]) == 1  # storage
         and c[2] == []  # paths
         and c[3] is None)  # subcontainer_of
        for e, c in zip(expected_mounts, sorted_commands)
    ]), f'{sorted_commands} does not match {expected_mounts}'


def test_get_watch_params_mounted1_pattern_path(control_client, client2):
    control_client.expect('status', {})
    search = Search(client2,
        WildlandPath.from_str(':/users/User2:/containers/c1:'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    control_client.expect('paths', {
        f'/.users/0xaaa:/.backends/00000000-1111-0000-0000-000000000000/{DUMMY_BACKEND_UUID}': [0],
    })

    mount_cmds, patterns = search.get_watch_params()
    assert len(mount_cmds) == 1
    assert len(patterns) == 2

    expected_patterns_re = [
        str_re(r'^/.users/0xaaa:/.backends/00000000-1111-0000-.*/users/User2.yaml'),
        str_re(r'^/.users/0xbbb:/.backends/00000000-2222-0000-.*/containers/c1.yaml'),
    ]
    assert sorted(patterns) == expected_patterns_re
    assert mount_cmds[0][0].owner == '0xbbb'
    assert mount_cmds[0][0].ensure_uuid() == '00000000-2222-0000-0000-000000000000'


def test_get_watch_params_pattern_star(control_client, client2):
    control_client.expect('status', {})
    search = Search(client2,
        WildlandPath.from_str(':/users/User3:/containers/c1:'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    control_client.expect('paths', {})

    mount_cmds, patterns = search.get_watch_params()
    assert len(mount_cmds) == 2
    assert len(patterns) == 2

    expected_patterns_re = [
        str_re(r'^/.users/0xaaa:/.backends/00000000-1111-0000-.*/users/User3.yaml'),
        str_re(r'^/.users/0xccc:/.backends/00000000-3333-0000-.*/\*\.yaml'),
    ]
    assert sorted(patterns) == expected_patterns_re


def test_get_watch_params_wildcard_pattern_star(control_client, client2):
    control_client.expect('status', {})
    search = Search(client2,
        WildlandPath.from_str(':/users/User3:*:'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    control_client.expect('paths', {})

    mount_cmds, patterns = search.get_watch_params()
    assert len(mount_cmds) == 2
    assert len(patterns) == 2

    expected_patterns_re = [
        str_re(r'^/.users/0xaaa:/.backends/00000000-1111-0000-.*/users/User3.yaml'),
        str_re(r'^/.users/0xccc:/.backends/00000000-3333-0000-.*/\*\.yaml'),
    ]
    assert sorted(patterns) == expected_patterns_re


def test_get_watch_params_wildcard_pattern_path(control_client, client2):
    control_client.expect('status', {})
    search = Search(client2,
        WildlandPath.from_str(':/users/User2:*:'),
        aliases={'default': '0xaaa'},
        fs_client=client2.fs_client)

    control_client.expect('paths', {})

    mount_cmds, patterns = search.get_watch_params()
    assert len(mount_cmds) == 2
    assert len(patterns) == 2

    expected_patterns_re = [
        str_re(r'^/.users/0xaaa:/.backends/00000000-1111-0000-.*/users/User2.yaml'),
        str_re(r'^/.users/0xbbb:/.backends/00000000-2222-0000-.*/.uuid/\*\.yaml'),
    ]
    assert sorted(patterns) == expected_patterns_re


@pytest.mark.parametrize('owner', ['0xfff', '0xddd'])
def test_search_hint(base_dir, client, owner):
    storage_path_infra = base_dir / 'storage_infra'
    storage_path_infra.mkdir()

    user_data = f'''\
signature: |
  dummy.0xddd
---
object: user
owner: '0xddd'
pubkeys:
- key.0xddd
paths:
- /users/Remote
infrastructures:
 - object: container
   owner: '0xddd'
   paths:
    - /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
   backends:
    storage:
     - object: storage
       type: local
       location: {storage_path_infra}
       owner: '0xddd'
       container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a69
       backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a89e2'
       manifest-pattern:
        type: glob
        path: '/{{path}}.yaml'
'''.encode()

    storage_path_cont = base_dir / 'storage_container'
    storage_path_cont.mkdir()

    container_data = f'''\
signature: |
  dummy.0xddd
---
object: container
owner: '0xddd'
paths:
- /.uuid/11e69833-0152-4563-92fc-b1540fc54a70
- /path
backends:
 storage:
  - object: storage
    type: local
    location: {storage_path_cont}
    owner: '0xddd'
    container-path: /.uuid/11e69833-0152-4563-92fc-b1540fc54a70
    backend-id: '3cba7968-da34-4b8c-8dc7-83d8860a89e3'
'''

    with open(storage_path_infra / 'path.yaml', 'w') as f:
        f.write(container_data)

    with open(storage_path_cont / 'file.txt', 'w') as f:
        f.write('Hello world')

    (storage_path_infra / '.wildland-owners').write_bytes(b'0xddd\n')
    (storage_path_cont / '.wildland-owners').write_bytes(b'0xddd\n')

    search = Search(client,
                    WildlandPath.from_str(f'{owner}@https{{mock.url}}:/path:/file.txt'),
                    aliases={'default': '0xaaa'})

    with mock.patch('wildland.client.Client.read_from_url') as mock_read:
        mock_read.return_value = user_data

        if owner == '0xddd':
            data = search.read_file()
            assert data == b'Hello world'
            mock_read.assert_called_with('https://mock.url', owner)

        else:
            with pytest.raises(WildlandError):
                search.read_file()
