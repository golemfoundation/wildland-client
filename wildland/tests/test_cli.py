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

from copy import deepcopy
from pathlib import Path
import itertools
import os
import re
import shutil
import subprocess
import time

from unittest.mock import patch

import pytest
import yaml

from ..cli.cli_base import CliError
from ..cli.cli_common import del_nested_field
from ..exc import WildlandError
from ..manifest.manifest import ManifestError, Manifest
from ..utils import load_yaml, load_yaml_all


def modify_file(path, pattern, replacement):
    with open(path) as f:
        data = f.read()
    assert pattern in data
    data = data.replace(pattern, replacement)
    with open(path, 'w') as f:
        f.write(data)


def strip_yaml(line):
    """Helper suitable for checking if some ``key: value`` is in yaml dump

    The problem this solves:

    >>> obj1 = {'outer': [{'key2': 'value2'}]}
    >>> obj2 = {'outer': [{'key1': 'value1', 'key2': 'value2'}]}
    >>> dump1 = yaml.safe_dump(obj1, default_flow_style=False)
    >>> dump2 = yaml.safe_dump(obj2, default_flow_style=False)
    >>> print(dump1)
    outer:
    - key2: value2
    >>> print(dump2)
    outer:
    - key1: value1
      key2: value2
    >>> '- key2: value2' in dump1.split('\n')
    True
    >>> '- key2: value2' in dump2.split('\n')
    False
    >>> 'key2: value2' in [strip_yaml(line) for line in dump1.split('\n')]
    True
    >>> 'key2: value2' in [strip_yaml(line) for line in dump2.split('\n')]
    True
    """

    return line.strip('\n -')

def get_container_uuid_from_uuid_path(uuid_path):
    match = re.search('/.uuid/(.+?)$', uuid_path)
    return match.group(1) if match else ''

@pytest.fixture
def cleanup():
    cleanup_functions = []

    def add_cleanup(func):
        cleanup_functions.append(func)

    yield add_cleanup

    for f in cleanup_functions:
        f()


# Users

def test_user_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data

    with open(base_dir / 'config.yaml') as f:
        config = f.read()
    assert "'@default': '0xaaa'" in config
    assert "'@default-owner': '0xaaa'" in config
    assert "- '0xaaa'" in config


def test_user_create_additional_keys(cli, base_dir):
    cli('user', 'create', 'User', '--add-pubkey', 'key.0xbbb')
    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()

    assert 'pubkeys:\n- key.0x111\n- key.0xbbb' in data


def test_user_list(cli, base_dir):
    cli('user', 'create', 'User1', '--key', '0xaaa',
        '--path', '/users/Foo', '--path', '/users/Bar')
    ok = [
        str(base_dir / 'users/User1.user.yaml') + ' (@default) (@default-owner)',
        '  owner: 0xaaa',
        '  private and public keys available',
        '   path: /users/Foo',
        '   path: /users/Bar',
        '',
        str(base_dir / 'users/User2.user.yaml'),
        '  owner: 0xbbb',
        '  private and public keys available',
        '   path: /users/User2',
        ''
    ]
    cli('user', 'create', 'User2', '--key', '0xbbb')
    result = cli('user', 'list', capture=True)
    assert result.splitlines() == ok
    result = cli('users', 'list', capture=True)
    assert result.splitlines() == ok


def test_user_delete(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    user_path = base_dir / 'users/User.user.yaml'
    assert user_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()

    with pytest.raises(CliError, match='User still has manifests'):
        cli('user', 'delete', 'User')

    cli('user', 'delete', '--force', 'User')
    assert not user_path.exists()
    assert container_path.exists()

    with open(base_dir / 'config.yaml') as f:
        config = f.read()

    assert "'@default': '0xaaa'" not in config
    assert "'@default-owner': '0xaaa'" not in config
    assert "- '0xaaa'" not in config


def test_multiple_user_config_file(cli, base_dir):
    cli('user', 'create', 'UserA', '--key', '0xaaa')
    cli('user', 'create', 'UserB', '--key', '0xbbb')

    with open(base_dir / 'config.yaml') as f:
        config = f.read()

    assert "'@default': '0xaaa'" in config
    assert "'@default-owner': '0xaaa'" in config
    assert "- '0xaaa'" in config
    assert "- '0xbbb'" in config

    cli('user', 'delete', 'UserA')

    with open(base_dir / 'config.yaml') as f:
        config = f.read()

    assert "'@default': '0xaaa'" not in config
    assert "'@default-owner': '0xaaa'" not in config
    assert "- '0xaaa'" not in config
    assert "- '0xbbb'" in config  # sic!

    cli('user', 'delete', 'UserB')

    with open(base_dir / 'config.yaml') as f:
        config = f.read()

    assert "- '0xbbb'" not in config


def test_user_delete_cascade(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    user_path = base_dir / 'users/User.user.yaml'
    assert user_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()

    cli('user', 'delete', '--cascade', 'User')
    assert not user_path.exists()
    assert not container_path.exists()


def test_user_verify(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'verify', 'User')
    cli('user', 'verify', 'User.user')
    cli('user', 'verify', '0xaaa')
    cli('user', 'verify', '@default')
    cli('user', 'verify', '@default-owner')
    cli('user', 'verify', base_dir / 'users/User.user.yaml')


def test_user_verify_bad_sig(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.user.yaml', 'dummy.0xaaa', 'dummy.0xbbb')
    cli_fail('user', 'verify', 'User')


def test_user_verify_bad_fields(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.user.yaml', 'owner:', 'extra: xxx\nowner:')
    cli_fail('user', 'verify', 'User')


def test_user_sign(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    tmp_file = base_dir / 'tmp.yaml'
    shutil.copyfile(base_dir / 'users/User.user.yaml', tmp_file)

    modify_file(tmp_file, 'dummy.0xaaa', 'outdated.0xaaa')
    cli_fail('user', 'verify', tmp_file)

    cli('user', 'sign', '-i', tmp_file)
    cli('user', 'verify', tmp_file)

    user_file = base_dir / 'users/User.user.yaml'
    modify_file(user_file, 'dummy.0xaaa', 'outdated.0xaaa')
    cli_fail('user', 'verify', user_file)

    cli('user', 'sign', '-i', 'User')
    cli('user', 'verify', '0xaaa')


def test_user_edit(cli, base_dir):
    user_path = base_dir / 'users/User.user.yaml'
    cli('user', 'create', 'User', '--key', '0xaaa', '--path', '/PATH')
    editor = r'sed -i s,PATH,XYZ,g'
    cli('user', 'edit', 'User', '--editor', editor)

    assert '/XYZ' in user_path.read_text()
    assert '/PATH' not in user_path.read_text()

    editor = r'sed -i s,XYZ,PATH,g'
    cli('user', 'edit', '@default', '--editor', editor)

    assert '/PATH' in user_path.read_text()
    assert '/XYZ' not in user_path.read_text()


def test_user_edit_bad_fields(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'sed -i s,owner,Signer,g'
    cli_fail('user', 'edit', 'User', '--editor', editor)


def test_user_edit_editor_failed(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'false'
    cli_fail('user', 'edit', 'User', '--editor', editor)


def test_user_add_path(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')

    manifest_path = base_dir / 'users/User.user.yaml'

    cli('user', 'modify', 'add-path', 'User', '--path', '/abc')
    assert '/abc' in manifest_path.read_text()

    cli('user', 'modify', 'add-path', '@default', '--path', '/xyz')
    assert '/xyz' in manifest_path.read_text()

    # duplicates should be ignored
    cli('user', 'modify', 'add-path', 'User', '--path', '/xyz')
    data = manifest_path.read_text()
    assert data.count('/xyz') == 1

    # multiple paths
    cli('user', 'modify', 'add-path', 'User.user', '--path', '/abc', '--path', '/def')
    data = manifest_path.read_text()
    assert data.count('/abc') == 1
    assert data.count('/def') == 1

    # invalid path
    cli_fail('user', 'modify', 'add-path', 'User', '--path', 'abc')


def test_user_del_path(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')

    manifest_path = base_dir / 'users/User.user.yaml'
    cli('user', 'modify', 'add-path', 'User', '--path', '/abc')

    cli('user', 'modify', 'del-path', 'User', '--path', '/abc')
    with open(manifest_path) as f:
        data = f.read()
    assert '/abc' not in data

    # non-existent paths should be ignored
    cli('user', 'modify', 'del-path', 'User.user', '--path', '/xyz')

    # multiple paths
    cli('user', 'modify', 'add-path', 'User', '--path', '/abc', '--path', '/def', '--path', '/xyz')
    cli('user', 'modify', 'del-path', manifest_path, '--path', '/abc', '--path', '/def')
    with open(manifest_path) as f:
        data = [i.strip() for i in f.read().split()]
    assert data.count('/abc') == 0
    assert data.count('/def') == 0
    assert data.count('/xyz') == 1

    # FIXME: invalid path
    # cli_fail('user', 'modify', 'del-path', 'User', '--path', 'abc')


def test_user_add_pubkey(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')

    pubkey1 = 'key.0xbbb'
    pubkey2 = 'key.0xccc'
    manifest_path = base_dir / 'users/User.user.yaml'

    cli('user', 'modify', 'add-pubkey', 'User', '--pubkey', pubkey1)
    with open(manifest_path) as f:
        data = f.read()
    assert pubkey1 in data

    # duplicates should be ignored
    cli('user', 'modify', 'add-pubkey', manifest_path, '--pubkey', pubkey1)
    with open(manifest_path) as f:
        data = [i.strip() for i in f.read().split()]
    assert data.count(pubkey1) == 1

    # multiple keys
    cli('user', 'modify', 'add-pubkey', 'User.user', '--pubkey', pubkey1, '--pubkey', pubkey2)
    with open(manifest_path) as f:
        data = [i.strip() for i in f.read().split()]
    assert data.count(pubkey1) == 1
    assert data.count(pubkey2) == 1

    # TODO: invalid key
    #cli_fail('user', 'modify', 'add-pubkey', 'User', '--pubkey', 'abc')


def test_user_del_pubkey(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')

    pubkey1 = 'key.0xbbb'
    pubkey2 = 'key.0xccc'
    pubkey3 = 'key.0xddd'
    manifest_path = base_dir / 'users/User.user.yaml'
    cli('user', 'modify', 'add-pubkey', 'User', '--pubkey', pubkey1)

    cli('user', 'modify', 'del-pubkey', 'User', '--pubkey', pubkey1)
    with open(manifest_path) as f:
        data = f.read()
    assert pubkey1 not in data

    # non-existent keys should be ignored
    cli('user', 'modify', 'del-pubkey', 'User.user', '--pubkey', pubkey2)

    # multiple keys
    cli('user', 'modify', 'add-pubkey', 'User', '--pubkey', pubkey1, '--pubkey', pubkey2,
        '--pubkey', pubkey3)
    cli('user', 'modify', 'del-pubkey', manifest_path, '--pubkey', pubkey1, '--pubkey', pubkey2)
    with open(manifest_path) as f:
        data = [i.strip() for i in f.read().split()]
    assert data.count(pubkey1) == 0
    assert data.count(pubkey2) == 0
    assert data.count(pubkey3) == 1

    # FIXME: invalid path
    #cli_fail('user', 'modify', 'del-path', 'User', '--path', 'abc')

# Test CLI common methods (units)


def test_del_nested_field():
    nested_list = {'a': {'b': {'c': ['a', 'b', 'c']}}}
    nested_set = {'a': {'b': {'c': {'a': 1, 'b': 'c'}}}}

    res = del_nested_field(deepcopy(nested_list), ['a', 'b', 'c'], values=['b', 'xxx'])
    assert res['a']['b']['c'] == ['a', 'c']

    res = del_nested_field(deepcopy(nested_list), ['a', 'b', 'c'], keys=[0, 2, 99])
    assert res['a']['b']['c'] == ['b']

    # Nested field doesn't exist. Expect unchanged object
    res = del_nested_field(deepcopy(nested_list), ['a', 'c'], keys=[0, 2])
    assert res == nested_list

    res = del_nested_field(deepcopy(nested_set), ['a', 'b', 'c'], values=['c', 'xxx'])
    assert res['a']['b']['c'] == {'a': 1}

    res = del_nested_field(deepcopy(nested_set), ['a', 'b', 'c'], keys=[0, 'a', 'c'])
    assert res['a']['b']['c'] == {'b': 'c'}

    # Nested field doesn't exist. Expect unchanged object
    res = del_nested_field(deepcopy(nested_set), ['a', 'b', 'd'], keys=[0, 'a', 'c'])
    assert res == nested_set

    # Attempt to change both keys and values. Expect unchanged object
    res = del_nested_field(deepcopy(nested_set), ['a', 'b', 'd'], ['c', 'xxx'], [0, 'a', 'c'])
    assert res == nested_set


## Storage

def test_storage_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')
    with open(base_dir / 'storage/Storage.storage.yaml') as f:
        data = f.read()

    assert "owner: ''0xaaa''" in data
    assert "location: /PATH" in data
    assert "backend-id:" in data

    cli('storage', 'create', 'zip-archive', 'ZipStorage', '--location', '/zip',
        '--container', 'Container', '--no-inline')
    with open(base_dir / 'storage/ZipStorage.storage.yaml') as f:
        data = f.read()

    assert "owner: ''0xaaa''" in data
    assert "location: /zip" in data
    assert "backend-id:" in data


def test_storage_create_not_inline(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert str(storage_path) in data


def test_storage_create_inline(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/STORAGE',
        '--container', 'Container', '--inline')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    assert '/STORAGE' in data
    # inline storage shouldn't have owner repeated
    assert '  owner:' not in data
    assert '  container-path:' not in data


def test_storage_delete(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    with pytest.raises(CliError, match='Storage is still used'):
        cli('storage', 'delete', 'Storage')

    cli('storage', 'delete', '--force', 'Storage')
    assert not storage_path.exists()


def test_storage_delete_cascade(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert str(storage_path) in container_path.read_text()

    cli('storage', 'delete', '--cascade', 'Storage')
    assert not storage_path.exists()
    assert str(storage_path) not in container_path.read_text()


def test_storage_list(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    ok = [
        str(base_dir / 'storage/Storage.storage.yaml'),
        '  type: local',
        '  location: /PATH',
    ]

    result = cli('storage', 'list', capture=True)
    assert result.splitlines() == ok
    result = cli('storages', 'list', capture=True)
    assert result.splitlines() == ok


def test_storage_edit(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    manifest = base_dir / 'storage/Storage.storage.yaml'

    editor = r'sed -i s,PATH,HTAP,g'
    cli('storage', 'edit', 'Storage', '--editor', editor)
    with open(manifest) as f:
        data = f.read()
    assert "location: /HTAP" in data

    editor = r'sed -i s,HTAP,PATH,g'
    cli('storage', 'edit', manifest, '--editor', editor)
    with open(manifest) as f:
        data = f.read()
    assert "location: /PATH" in data


def test_storage_edit_fail(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/LOCATION',
        '--container', 'Container')

    editor = r'sed -i s,/LOCATION,WRONGLOCATION,g'
    with patch('click.confirm', return_value=False) as mock:
        cli('container', 'edit', 'Container', '--editor', editor)
        mock.assert_called()


def test_storage_set_location(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/LOC',
        '--container', 'Container', '--no-inline')

    manifest_path = base_dir / 'storage/Storage.storage.yaml'

    cli('storage', 'modify', 'set-location', 'Storage', '--location', '/OTHER')
    with open(manifest_path) as f:
        data = f.read()
    assert 'location: /OTHER' in data

def test_multiple_storage_mount(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_1',
        '--container', 'Container')
    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_2',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    assert documents[1]['paths'][1] == '/PATH'

    backend_id1 = documents[1]['backends']['storage'][0]['backend-id']
    backend_id2 = documents[1]['backends']['storage'][1]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'

    paths_1 = [
        f'/.backends/{uuid}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]

    paths_2 = [
        f'/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}',
    ]

    assert sorted(command[0]['paths']) == paths_1
    assert sorted(command[1]['paths']) == paths_2

    # Add 3rd storage while first two are already mounted and remount.

    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_3',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    backend_id3 = documents[1]['backends']['storage'][2]['backend-id']

    control_client.expect('paths', {
        **{x: [1] for x in paths_1},
        **{x: [2] for x in paths_2}
    })

    control_client.expect('info', {
        '1': {
            'paths': paths_1,
            'type': 'local',
            'extra': {
                'tag': command[0]['extra']['tag'],
                'primary': command[0]['extra']['primary'],
            },
        },
        '2': {
            'paths': paths_2,
            'type': 'local',
            'extra': {
                'tag': command[1]['extra']['tag'],
                'primary': command[1]['extra']['primary'],
            },
        },
    })

    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 1
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id3}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id3}',
    ]


def test_storage_mount_remove_primary_and_remount(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_1',
        '--container', 'Container')
    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_2',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    assert documents[1]['paths'][1] == '/PATH'

    backend_id1 = documents[1]['backends']['storage'][0]['backend-id']
    backend_id2 = documents[1]['backends']['storage'][1]['backend-id']

    paths_1 = [
        f'/.backends/{uuid}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]

    paths_2 = [
        f'/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}',
    ]

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']

    cli('container', 'modify', 'del-storage', 'Container', '--storage', backend_id1)

    control_client.expect('paths', {
        f'/.backends/{uuid}/{backend_id1}': [1],
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id1}': [1],
        f'/.users/0xaaa:/.uuid/{uuid}': [1],
        '/.users/0xaaa:/PATH': [1],
        f'/.uuid/{uuid}': [1],
        '/PATH': [1],
        f'/.backends/{uuid}/{backend_id2}': [2],
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}': [2],
    })

    control_client.expect('info', {
        '1': {
            'paths': paths_1,
            'type': 'local',
            'extra': {
                'tag': command[0]['extra']['tag'],
                'primary': command[0]['extra']['primary'],
            },
        },
        '2': {
            'paths': paths_2,
            'type': 'local',
            'extra': {
                'tag': command[1]['extra']['tag'],
                'primary': command[1]['extra']['primary'],
            },
        },
    })
    control_client.expect('unmount')
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 1
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]

def test_storage_mount_remove_secondary_and_remount(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_1',
        '--container', 'Container')
    cli('storage', 'create', 'local', 'Storage', '--location', '/loc_2',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    assert documents[1]['paths'][1] == '/PATH'

    backend_id1 = documents[1]['backends']['storage'][0]['backend-id']
    backend_id2 = documents[1]['backends']['storage'][1]['backend-id']

    paths_1 = [
        f'/.backends/{uuid}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]

    paths_2 = [
        f'/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}',
    ]

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']

    cli('container', 'modify', 'del-storage', 'Container', '--storage', backend_id2)

    control_client.expect('paths', {
        f'/.backends/{uuid}/{backend_id1}': [1],
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id1}': [1],
        f'/.users/0xaaa:/.uuid/{uuid}': [1],
        '/.users/0xaaa:/PATH': [1],
        f'/.uuid/{uuid}': [1],
        '/PATH': [1],
        f'/.backends/{uuid}/{backend_id2}': [2],
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}': [2],
    })

    control_client.expect('info', {
        '1': {
            'paths': paths_1,
            'type': 'local',
            'extra': {
                'tag': command[0]['extra']['tag'],
                'primary': command[0]['extra']['primary'],
            },
        },
        '2': {
            'paths': paths_2,
            'type': 'local',
            'extra': {
                'tag': command[1]['extra']['tag'],
                'primary': command[1]['extra']['primary'],
            },
        },
    })
    control_client.expect('unmount')
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command == []


## Container


def test_container_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data
    assert "/PATH" in data
    assert "/.uuid/" in data


def test_container_create_access(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'UserB', '--key', '0xbbb')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data
    assert "/PATH" in data
    assert "/.uuid/" in data
    assert not 'encrypted' in data

    cli('container', 'create', 'Container2', '--path', '/PATH', '--access', 'UserB')

    with open(base_dir / 'containers/Container2.container.yaml') as f:
        base_data = f.read().split('\n', 3)[-1]
        data = yaml.safe_load(base_data)

    assert 'encrypted' in data.keys()
    assert len(data['encrypted']['encrypted-keys']) == 2


def test_container_duplicate(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('container', 'duplicate', '--new-name', 'Duplicate', 'Container')
    with open(base_dir / 'containers/Container.container.yaml') as f:
        base_data = f.read().split('\n', 4)[-1]
    with open(base_dir / 'containers/Duplicate.container.yaml') as f:
        copy_data = f.read().split('\n', 4)[-1]

    old_uuid = re.search('/.uuid/(.+?)\n', base_data).group(1)
    new_uuid = re.search('/.uuid/(.+?)\n', copy_data).group(1)

    assert old_uuid != new_uuid
    assert base_data.replace(old_uuid, new_uuid) == copy_data


def test_container_duplicate_storage(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    cli('container', 'duplicate', '--new-name', 'Duplicate', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        base_data = f.read().split('\n', 4)[-1]
    with open(base_dir / 'containers/Duplicate.container.yaml') as f:
        copy_data = f.read().split('\n', 4)[-1]

    old_uuid = re.search('/.uuid/(.+?)\n', base_data).group(1)
    new_uuid = re.search('/.uuid/(.+?)\n', copy_data).group(1)

    old_backend_id = re.search('backend-id:(.+?)\n', base_data).group(1)
    new_backend_id = re.search('backend-id:(.+?)\n', copy_data).group(1)

    assert old_backend_id != new_backend_id
    assert base_data.replace(old_uuid, new_uuid).replace(
        old_backend_id, new_backend_id) == copy_data


def test_container_duplicate_noinline(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    cli('container', 'duplicate', '--new-name', 'Duplicate', 'Container')

    storage_path = base_dir / 'storage/Duplicate.storage.yaml'
    container_path = base_dir / 'containers/Duplicate.container.yaml'
    with open(container_path) as f:
        container_data = f.read().split('\n', 4)[-1]
    with open(storage_path) as f:
        storage_data = f.read().split('\n', 4)[-1]

    uuid = re.search(r'/.uuid/(.+?)\\n', container_data).group(1)

    assert f'container-path: /.uuid/{uuid}' in storage_data
    assert f'- file://localhost{str(storage_path)}' in container_data


def test_container_duplicate_mount(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')
    cli('container', 'duplicate', '--new-name', 'Duplicate', 'Container')

    with open(base_dir / 'containers/Duplicate.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    assert documents[1]['paths'][1] == '/PATH'

    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Duplicate')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]


def test_container_edit(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    manifest = base_dir / 'containers/Container.container.yaml'

    editor = r'sed -i s,PATH,HTAP,g'
    cli('container', 'edit', 'Container', '--editor', editor)
    with open(manifest) as f:
        data = f.read()
    assert "/HTAP" in data

    editor = r'sed -i s,HTAP,PATH,g'
    cli('container', 'edit', 'Container.container', '--editor', editor)
    with open(manifest) as f:
        data = f.read()
    assert "/PATH" in data


def test_container_edit_encryption(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', '--path', '/PATH', 'Container')

    editor = r'sed -i s,encrypted,FAILURE,g'

    cli('container', 'edit', 'Container', '--editor', editor)
    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()
    assert '"FAILURE"' not in data


def test_container_add_path(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    manifest_path = base_dir / 'containers/Container.container.yaml'

    cli('container', 'modify', 'add-path', 'Container', '--path', '/abc')
    assert '/abc' in manifest_path.read_text()

    cli('container', 'modify', 'add-path', 'Container.container', '--path', '/xyz')
    assert '/xyz' in manifest_path.read_text()

    # duplicates should be ignored
    cli('container', 'modify', 'add-path', 'Container', '--path', '/xyz')
    data = manifest_path.read_text()
    assert data.count('/xyz') == 1

    # multiple paths
    cli('container', 'modify', 'add-path', manifest_path, '--path', '/abc', '--path', '/def')
    data = manifest_path.read_text()
    assert data.count('/abc') == 1
    assert data.count('/def') == 1

    # invalid path
    cli_fail('container', 'modify', 'add-path', 'Container', '--path', 'abc')


def test_container_del_path(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    manifest_path = base_dir / 'containers/Container.container.yaml'
    cli('container', 'modify', 'add-path', 'Container', '--path', '/abc')

    cli('container', 'modify', 'del-path', 'Container', '--path', '/abc')
    assert '/abc' not in manifest_path.read_text()

    # non-existent paths should be ignored
    cli('container', 'modify', 'del-path', 'Container.container', '--path', '/xyz')

    # multiple paths
    cli('container', 'modify', 'add-path', 'Container', '--path', '/abc', '--path', '/def',
        '--path', '/xyz')
    cli('container', 'modify', 'del-path', manifest_path, '--path', '/abc', '--path', '/def')
    data = manifest_path.read_text()
    assert data.count('/abc') == 0
    assert data.count('/def') == 0
    assert data.count('/xyz') == 1

    # FIXME: invalid path
    # cli_fail('container', 'modify', 'del-path', 'Container', '--path', 'abc')


def test_container_set_title(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    manifest_path = base_dir / 'containers/Container.container.yaml'

    cli('container', 'modify', 'set-title', 'Container.container', '--title', 'something')
    with open(manifest_path) as f:
        data = f.read()
    assert 'title: something' in data

    cli('container', 'modify', 'set-title', 'Container', '--title', 'another thing')
    with open(manifest_path) as f:
        data = f.read()
    assert 'title: another thing' in data


def test_container_add_category(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'TITLE')

    manifest_path = base_dir / 'containers/Container.container.yaml'

    cli('container', 'modify', 'add-category', 'Container', '--category', '/abc')
    with open(manifest_path) as f:
        data = f.read()
    assert '- /abc' in data

    cli('container', 'modify', 'add-category', 'Container.container', '--category', '/xyz')
    with open(manifest_path) as f:
        data = f.read()
    assert '- /xyz' in data

    # duplicates should be ignored
    cli('container', 'modify', 'add-category', 'Container', '--category', '/xyz')
    with open(manifest_path) as f:
        data = f.read()
    assert data.count('- /xyz') == 1

    # multiple values
    cli('container', 'modify', 'add-category', manifest_path, '--category', '/abc',
        '--category', '/def')
    with open(manifest_path) as f:
        data = f.read()
    assert data.count('- /abc') == 1
    assert data.count('- /def') == 1

    # invalid category
    cli_fail('container', 'modify', 'add-category', 'Container', '--category', 'abc')


def test_container_del_category(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'TITLE')

    manifest_path = base_dir / 'containers/Container.container.yaml'
    cli('container', 'modify', 'add-category', 'Container', '--category', '/abc')

    cli('container', 'modify', 'del-category', 'Container', '--category', '/abc')
    with open(manifest_path) as f:
        data = f.read()
    assert '- /abc' not in data

    # non-existent paths should be ignored
    cli('container', 'modify', 'del-category', 'Container.container', '--category', '/xyz')

    # multiple values
    cli('container', 'modify', 'add-category', 'Container', '--category', '/abc',
        '--category', '/def', '--category', '/xyz')
    cli('container', 'modify', 'del-category', manifest_path, '--category', '/abc',
        '--category', '/def')
    with open(manifest_path) as f:
        data = f.read()
    assert data.count('- /abc') == 0
    assert data.count('- /def') == 0
    assert data.count('- /xyz') == 1

    # FIXME: invalid path
    # cli_fail('container', 'modify', 'del-path', 'Container', '--path', 'abc')


def test_container_modify_access(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'TITLE')

    manifest_path = base_dir / 'containers/Container.container.yaml'

    cli('container', 'modify', 'add-access', 'Container', '--access', 'User2')
    base_data = manifest_path.read_text().split('\n', 3)[-1]
    data = yaml.safe_load(base_data)
    assert len(data['encrypted']['encrypted-keys']) == 2

    cli('container', 'modify', 'del-access', 'Container', '--access', 'User2')
    base_data = manifest_path.read_text().split('\n', 3)[-1]
    data = yaml.safe_load(base_data)
    assert len(data['encrypted']['encrypted-keys']) == 1

    cli('container', 'modify', 'set-no-encrypt-manifest', 'Container')
    assert 'encrypted' not in manifest_path.read_text()

    cli('container', 'modify', 'set-encrypt-manifest', 'Container')
    assert 'encrypted' in manifest_path.read_text()


def test_container_create_update_user(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--update-user')

    with open(base_dir / 'users/User.user.yaml') as f:
        data = f.read()

    assert 'containers/Container.container.yaml' in data


def test_container_create_no_path(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Sky', '--category', '/colors/blue')

    with open(base_dir / 'containers/Sky.container.yaml') as f:
        data = f.read()

    assert "owner: '0xaaa'" in data
    assert "categories:\\n- /colors/blue" in data
    assert "title: Sky\\n" in data
    assert "paths:\\n- /.uuid/" in data


def test_container_update(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('container', 'create', 'Container2', '--path', '/PATH2')

    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH2',
        '--container', 'Container2', '--no-inline')
    cli('container', 'update', 'Container', '--storage', 'Storage')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert str(storage_path) in data


def test_container_publish_unpublish(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--update-user')
    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'Container',
        '--inline',
        '--manifest-pattern', '/*.yaml')

    cli('container', 'publish', 'Container')

    assert len(tuple(tmp_path.glob('*.yaml'))) == 1

    cli('container', 'unpublish', 'Container')

    assert not tuple(tmp_path.glob('*.yaml'))


def test_container_publish_rewrite(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--update-user',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'Container',
        '--no-inline',
        '--manifest-pattern', '/m-*.yaml',
        '--base-url', 'https://example.invalid/')

    cli('container', 'publish', 'Container')

    # “Always two there are. No more, no less. A master and an apprentice.”
    m1, m2 = tmp_path.glob('*.yaml')

    # “But which was destroyed, the master or the apprentice?”
    with open(m1) as file1:
        with open(m2) as file2:
            for line in itertools.chain(file1, file2):
                print(line)
                if re.fullmatch(
                        r'- https://example\.invalid/m-([A-Za-z0-9-]+\.){2}yaml',
                        line.strip()):
                    break
            else:
                assert False

def test_container_republish_paths(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container',
        '--path', '/PA/TH1',
        '--path', '/PA/TH2',
        '--update-user',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'Container',
        '--no-inline',
        '--manifest-pattern', '/manifests/{path}.yaml',
        '--base-url', 'https://example.invalid/')

    cli('container', 'publish', 'Container')

    assert (tmp_path / 'manifests/PA/TH1.yaml').exists()
    assert (tmp_path / 'manifests/PA/TH2.yaml').exists()
    assert not (tmp_path / 'manifests/PA/TH3.yaml').exists()

    cli('container', 'modify', 'del-path', 'Container', '--path', '/PA/TH2')
    cli('container', 'modify', 'add-path', 'Container', '--path', '/PA/TH3')

    cli('container', 'publish', 'Container')

    assert (tmp_path / 'manifests/PA/TH1.yaml').exists()
    assert not (tmp_path / 'manifests/PA/TH2.yaml').exists()
    assert (tmp_path / 'manifests/PA/TH3.yaml').exists()


def test_container_delete(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()
    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    with pytest.raises(CliError, match='Container refers to local manifests'):
        cli('container', 'delete', 'Container')

    # Should not complain if the storage manifest does not exist
    storage_path.unlink()
    cli('container', 'delete', 'Container')
    assert not container_path.exists()


def test_container_delete_force(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()
    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    cli('container', 'delete', '--force', 'Container')
    assert not container_path.exists()
    assert storage_path.exists()


def test_container_delete_cascade(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert container_path.exists()
    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    cli('container', 'delete', '--cascade', 'Container')
    assert not container_path.exists()
    assert not storage_path.exists()


def test_container_delete_umount(cli, base_dir, control_client):
    control_client.expect('status', {})
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    with open(base_dir / 'storage/Storage.storage.yaml') as f:
        documents = list(yaml.safe_load_all(f))

    backend_id = documents[1]['backend-id']

    (base_dir / 'storage/Storage.storage.yaml').unlink()

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)

    paths_obj = {
        f'/.backends/{uuid}/{backend_id}': [101],
        f'/.uuid/{uuid}': [102],
        f'/.users/0xaaa:/.uuid/{uuid}': [103],
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}': [104],
        '/PATH2': [105],
    }

    control_client.expect('unmount')
    control_client.expect('paths', paths_obj)
    control_client.expect('info', {
        '1': {
            'paths': paths_obj.keys(),
            'type': 'local',
            'extra': {},
        },
    })

    cli('container', 'delete', 'Container')

    container_path = base_dir / 'containers/Container.container.yaml'
    assert not container_path.exists()


def test_container_list(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    result = cli('container', 'list', capture=True)
    out_lines = result.splitlines()
    assert str(base_dir / 'containers/Container.container.yaml') in out_lines
    assert '  path: /PATH' in out_lines
    result = cli('containers', 'list', capture=True)
    out_lines = result.splitlines()
    assert str(base_dir / 'containers/Container.container.yaml') in out_lines
    assert '  path: /PATH' in out_lines


def test_container_mount(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    assert documents[1]['paths'][1] == '/PATH'

    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]

    modify_file(base_dir / 'config.yaml', "'@default': '0xaaa'", '')

    # The command should not contain the default path.
    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert sorted(command[0]['paths']) == [
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
    ]
    assert command[0]['extra']['trusted_owner'] is None


def test_container_mount_with_bridges(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'Other', '--key', '0xbbb')
    cli('bridge', 'create', '--ref-user', 'Other',
                            '--ref-user-path', '/users/other',
                            '--ref-user-path', '/people:/other',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'users/Other.user.yaml'),
                            'br-other')
    cli('container', 'create', 'Container', '--owner', 'Other', '--path', '/PATH',
        '--path', '/other:/path',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents_container = list(load_yaml_all(f))

    uuid_path = documents_container[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    assert documents_container[1]['paths'][1] == '/PATH'

    backend_id = documents_container[1]['backends']['storage'][0]['backend-id']

    # add infrastructure container
    with open(base_dir / 'users/Other.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['infrastructures'].append({
            'paths': ['/.uuid/1111-2222-3333-4444'],
            'object': 'container',
            'version': Manifest.CURRENT_VERSION,
            'owner': '0xbbb',
            'backends': {'storage': [{
                'type': 'local',
                'location': str(base_dir / 'containers'),
                'manifest-pattern': {
                    'type': 'glob',
                    'path': '/*.yaml',
                }
            }]}
        })
        f.seek(0)
        f.write('signature: |\n  dummy.0xbbb\n---\n')
        f.write(yaml.safe_dump(documents[1]))

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'wildland::/users/other:/PATH:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert sorted(command[0]['paths']) == [
        f'/.users/0xbbb:/.backends/{uuid}/{backend_id}',
        f'/.users/0xbbb:/.uuid/{uuid}',
        '/.users/0xbbb:/PATH',
        '/.users/0xbbb:/other_/path',
        f'/people_/other:/.backends/{uuid}/{backend_id}',
        f'/people_/other:/.uuid/{uuid}',
        '/people_/other:/PATH',
        '/people_/other:/other_/path',
        f'/users/other:/.backends/{uuid}/{backend_id}',
        f'/users/other:/.uuid/{uuid}',
        '/users/other:/PATH',
        '/users/other:/other_/path',
    ]


def test_container_mount_with_multiple_bridges(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')
    cli('user', 'create', 'Charlie', '--key', '0xccc')
    cli('bridge', 'create', '--owner', 'Alice',
                            '--ref-user', 'Bob',
                            '--ref-user-path', '/users/bob',
                            '--ref-user-path', '/people/bob',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'users/Bob.user.yaml'),
                            'br-bob')
    cli('bridge', 'create', '--owner', 'Alice',
                            '--ref-user', 'Charlie',
                            '--ref-user-path', '/users/charlie',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'users/Charlie.user.yaml'),
                            'br-charlie')
    cli('bridge', 'create', '--owner', 'Charlie',
                            '--ref-user', 'Bob',
                            '--ref-user-path', '/users/bob',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'users/Bob.user.yaml'),
                            'br-charlie-bob')
    # this should not be used, as it introduces a loop
    cli('bridge', 'create', '--owner', 'Bob',
                            '--ref-user', 'Alice',
                            '--ref-user-path', '/users/alice',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'users/Alice.user.yaml'),
                            'br-alice-bob')
    cli('container', 'create', 'Container', '--owner', 'Bob', '--path', '/PATH',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents_container = list(load_yaml_all(f))

    uuid_path = documents_container[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    backend_id = documents_container[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert sorted(command[0]['paths']) == [
        f'/.users/0xbbb:/.backends/{uuid}/{backend_id}',
        f'/.users/0xbbb:/.uuid/{uuid}',
        '/.users/0xbbb:/PATH',
        f'/people/bob:/.backends/{uuid}/{backend_id}',
        f'/people/bob:/.uuid/{uuid}',
        '/people/bob:/PATH',
        f'/users/bob:/.backends/{uuid}/{backend_id}',
        f'/users/bob:/.uuid/{uuid}',
        '/users/bob:/PATH',
        f'/users/charlie:/users/bob:/.backends/{uuid}/{backend_id}',
        f'/users/charlie:/users/bob:/.uuid/{uuid}',
        '/users/charlie:/users/bob:/PATH',
    ]


def test_container_mount_infra_err(cli, base_dir, control_client):
    infra_dir = base_dir / 'infra'
    infra_dir.mkdir()

    storage_dir = base_dir / 'storage_dir'
    storage_dir.mkdir()

    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Infra', '--owner', 'User', '--path', '/INFRA',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', str(infra_dir),
        '--container', 'Infra', '--manifest-pattern', '/*.yaml')

    cli('container', 'create', 'Mock1', '--owner', 'User', '--path', '/C',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', str(storage_dir),
        '--container', 'Mock1')
    cli('container', 'create', 'Mock2', '--owner', 'User', '--path', '/C',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', str(storage_dir),
        '--container', 'Mock2')

    os.rename(base_dir / 'containers/Mock1.container.yaml', infra_dir / 'Mock1.yaml')
    os.rename(base_dir / 'containers/Mock2.container.yaml', infra_dir / 'Mock2.yaml')

    container_file = base_dir / 'containers/Infra.container.yaml'
    cli('user', 'modify', 'add-infrastructure', '--path', f'file://{str(container_file)}', 'User')

    # if first container is somehow broken, others should be mounted
    for file in os.listdir(infra_dir):
        (infra_dir / file).write_text('testdata')
        break

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', ':*:')

    command = control_client.calls['mount']['items']
    assert len(command) == 1


def test_container_mount_with_import(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'Other', '--key', '0xbbb')
    os.mkdir(base_dir / 'other-infra')
    # add infrastructure container
    with open(base_dir / 'users/Other.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['infrastructures'].append({
            'paths': ['/.uuid/1111-2222-3333-4444'],
            'owner': '0xbbb',
            'object': 'container',
            'version': Manifest.CURRENT_VERSION,
            'backends': {'storage': [{
                'type': 'local',
                'location': str(base_dir / 'other-infra'),
                'manifest-pattern': {
                    'type': 'glob',
                    'path': '/*.yaml',
                }
            }]}
        })
        f.seek(0)
        f.write('signature: |\n  dummy.0xbbb\n---\n')
        f.write(yaml.safe_dump(documents[1]))
    cli('container', 'create', 'Container', '--owner', 'Other', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    # move user manifest out of the default path, so the bridge would be the only way to access it
    os.rename(base_dir / 'users/Other.user.yaml', base_dir / 'user-Other.user.yaml')
    # same for the container manifest
    os.rename(base_dir / 'containers/Container.container.yaml',
              base_dir / 'other-infra/Container.container.yaml')
    cli('bridge', 'create', '--ref-user-path', '/users/other',
                            '--ref-user-path', '/people/other',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'user-Other.user.yaml'),
                            'br-other')

    control_client.expect('paths', {})
    control_client.expect('mount')

    # first mount without importing - should still work
    cli('container', 'mount', '--no-import-users', 'wildland::/users/other:/PATH:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert '/.users/0xbbb:/PATH' in command[0]['paths']

    users = cli('user', 'list', capture=True)
    assert users.count('0xbbb') == 0

    control_client.calls = {}

    cli('container', 'mount', 'wildland::/users/other:/PATH:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert '/.users/0xbbb:/PATH' in command[0]['paths']

    control_client.calls = {}

    # now the user should be imported and mounting directly should work
    cli('container', 'mount', 'wildland:0xbbb:/PATH:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert '/.users/0xbbb:/PATH' in command[0]['paths']

    users = cli('user', 'list', capture=True)
    assert users.count('0xbbb') > 0

    bridges = cli('bridge', 'list', capture=True)
    assert bridges.count('/people/other') == 2


def test_container_mount_with_import_delegate(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'Other', '--key', '0xbbb')
    os.mkdir(base_dir / 'other-infra')
    # add infrastructure container
    with open(base_dir / 'users/Other.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['infrastructures'].append({
            'paths': ['/.uuid/1111-2222-3333-4444'],
            'owner': '0xbbb',
            'object': 'container',
            'version': Manifest.CURRENT_VERSION,
            'backends': {'storage': [{
                'type': 'local',
                'location': str(base_dir / 'other-infra'),
                'manifest-pattern': {
                    'type': 'glob',
                    'path': '/*.yaml',
                }
            }]}
        })
        f.seek(0)
        f.write('signature: |\n  dummy.0xbbb\n---\n')
        f.write(yaml.safe_dump(documents[1]))
    cli('container', 'create', 'Container', '--owner', 'Other', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    # move user manifest out of the default path, so the bridge would be the only way to access it
    os.rename(base_dir / 'users/Other.user.yaml', base_dir / 'user-Other.user.yaml')
    # same for the container manifest
    os.rename(base_dir / 'containers/Container.container.yaml',
              base_dir / 'other-infra/Container.container.yaml')
    cli('bridge', 'create', '--ref-user-path', '/users/other',
                            '--ref-user-path', '/people/other',
                            '--ref-user-location',
                            'file://%s' % (base_dir / 'user-Other.user.yaml'),
                            'br-other')

    cli('container', 'create', 'Container', '--owner', 'User', '--path', '/PROXY-PATH')
    cli('storage', 'create', 'delegate', 'Storage',
        '--reference-container-url', 'wildland:0xaaa:/users/other:/PATH:',
        '--container', 'Container')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'wildland::/PROXY-PATH:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['storage']['owner'] == '0xbbb'
    assert '/.users/0xaaa:/PROXY-PATH' in command[0]['paths']

    control_client.calls = {}

    # now the user should be imported and mounting directly should work
    cli('container', 'mount', 'wildland:0xbbb:/PATH:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert '/.users/0xbbb:/PATH' in command[0]['paths']

    bridges = cli('bridge', 'list', capture=True)
    assert bridges.count('/people/other') == 2


def test_container_mount_store_trusted_owner(cli, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--trusted')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['extra']['trusted_owner'] == '0xaaa'


def test_container_mount_glob(cli, base_dir, control_client):
    # The glob pattern will be normally expanded by shell,
    # but this feature is also used with default_containers.
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container1', '--path', '/PATH1', '--no-encrypt-manifest')
    cli('container', 'create', 'Container2', '--path', '/PATH2', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container1')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container2')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', base_dir / 'containers' / '*.yaml')

    command = control_client.calls['mount']['items']

    with open(base_dir / 'containers/Container1.container.yaml') as f:
        documents_container1 = list(load_yaml_all(f))

    with open(base_dir / 'containers/Container2.container.yaml') as f:
        documents_container2 = list(load_yaml_all(f))

    uuid_path1 = documents_container1[1]['paths'][0]
    uuid1 = get_container_uuid_from_uuid_path(uuid_path1)
    assert documents_container1[1]['paths'][1] == '/PATH1'

    uuid_path2 = documents_container2[1]['paths'][0]
    uuid2 = get_container_uuid_from_uuid_path(uuid_path2)
    assert documents_container2[1]['paths'][1] == '/PATH2'

    backend_id1 = documents_container1[1]['backends']['storage'][0]['backend-id']
    backend_id2 = documents_container2[1]['backends']['storage'][0]['backend-id']

    assert len(command) == 2
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid1}',
        '/.users/0xaaa:/PATH1',
        f'/.uuid/{uuid1}',
        '/PATH1'
    ]
    assert sorted(command[1]['paths']) == [
        f'/.backends/{uuid2}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid2}/{backend_id2}',
        f'/.users/0xaaa:/.uuid/{uuid2}',
        '/.users/0xaaa:/PATH2',
        f'/.uuid/{uuid2}',
        '/PATH2'
    ]


def test_container_mount_save(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--save', 'Container')

    with open(base_dir / 'config.yaml') as f:
        config = load_yaml(f)
    assert config['default-containers'] == ['Container']

    # Will not add the same container twice
    cli('container', 'mount', '--save', 'Container')

    with open(base_dir / 'config.yaml') as f:
        config = load_yaml(f)
    assert config['default-containers'] == ['Container']


def test_container_mount_inline_storage(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/STORAGE',
        '--container', 'Container', '--inline')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]


def test_container_mount_check_trusted_owner(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    manifest_path = base_dir / 'mnt/trusted/Container.container.yaml'

    # Write an unsigned container manifest to mnt/trusted/

    content = (base_dir / 'containers/Container.container.yaml').read_text()
    content = content[content.index('---'):]
    os.mkdir(base_dir / 'mnt/trusted')
    with open(manifest_path, 'w') as f:
        f.write(content)

    # Prepare data in .control

    def make_info(trusted_owner):
        return {
            '1': {
                'paths': ['/PATH'],
                'type': 'local',
                'extra': {'trusted_owner': trusted_owner}
            }
        }

    control_client.expect('paths', {'/trusted': [1]})
    control_client.expect('mount')

    # Should not mount if the storage is not trusted

    control_client.expect('info', make_info(None))
    with pytest.raises(WildlandError, match='Signature expected'):
        cli('container', 'mount', manifest_path)

    # Should not mount if the owner is different

    control_client.expect('info', make_info('0xbbb'))
    with pytest.raises(WildlandError, match='Wrong owner for manifest without signature'):
        cli('container', 'mount', manifest_path)

    # Should mount if the storage is trusted and with right owner

    control_client.expect('info', make_info('0xaaa'))
    cli('container', 'mount', manifest_path)


def test_container_mount_no_subcontainers(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--without-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]


def test_container_mount_subcontainers(cli, base_dir, control_client, tmp_path):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')

    uuid2 = '0000-1111-2222-3333-4444'
    backend_id = '5555-6666-7777-8888-9999'
    with open(tmp_path / 'subcontainer.yaml', 'w') as f:
        f.write(f"""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - /.uuid/{uuid2}
 - /subcontainer
backends:
  storage:
    - type: delegate
      backend-id: {backend_id}
      reference-container: 'wildland:@default:@parent-container:'
      subdirectory: '/subdir'
""")
    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container', '--subcontainer', './subcontainer.yaml')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path1 = documents[1]['paths'][0]
    uuid1 = get_container_uuid_from_uuid_path(uuid_path1)
    backend_id1 = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--with-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 2
    assert command[0]['storage']['owner'] == '0xaaa'
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid1}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid1}',
        '/PATH',
    ]

    assert command[1]['storage']['owner'] == '0xaaa'
    assert command[1]['storage']['type'] == 'delegate'
    assert command[1]['storage']['container-path'] == f'/.uuid/{uuid2}'
    assert command[1]['storage']['reference-container'] == f'wildland:@default:/.uuid/{uuid1}:'
    assert command[1]['storage']['subdirectory'] == '/subdir'
    assert command[1]['storage']['storage'] == command[0]['storage']

    assert sorted(command[1]['paths']) == [
        f'/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid2}',
        '/.users/0xaaa:/subcontainer',
        f'/.uuid/{uuid2}',
        '/subcontainer',
    ]


def test_container_mount_errors(cli, base_dir, control_client, tmp_path):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container')
    path2 = '/.uuid/0000-1111-2222-3333-4444'
    # put the correct one last, to check if mount errors do not interrupt mount
    with open(tmp_path / 'container-99.yaml', 'w') as f:
        f.write(f"""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - {path2}
 - /container-99
backends:
  storage:
    - type: delegate
      backend-id: 0000-1111-2222-3333-4444
      reference-container: 'file://{base_dir / 'containers/Container.container.yaml'}'
      subdirectory: '/subdir1'
""")

    subpath = tmp_path / 'container-2.yaml'
    shutil.copyfile(tmp_path / 'container-99.yaml', subpath)
    modify_file(subpath, 'container-99', 'container-2')
    modify_file(subpath, 'subdir1', 'subdir2')
    # corrupt signature so this one won't load
    modify_file(subpath, 'dummy.0xaaa', 'dummy.0xZZZ')

    subpath = tmp_path / 'container-3.yaml'
    shutil.copyfile(tmp_path / 'container-99.yaml', subpath)
    modify_file(subpath, 'container-99', 'container-3')
    modify_file(subpath, 'subdir1', 'subdir3')
    # corrupt storage, so it will load but will fail to mount
    modify_file(subpath, 'Container.container', 'NoSuchContainer')

    control_client.expect('paths', {})
    control_client.expect('mount')

    # TODO: cli_fail doesn't capture stderr now...
    with pytest.raises(WildlandError, match='Failed to load some container manifests'):
        output = cli('container', 'mount', tmp_path / 'container-*.yaml', capture=True)
        assert 'Traceback' not in output

    # the other container should still be mounted
    command = control_client.calls['mount']['items']
    assert len(command) == 1
    assert command[0]['storage']['owner'] == '0xaaa'
    assert '/container-99' in command[0]['paths']


def test_container_mount_only_subcontainers(cli, base_dir, control_client, tmp_path):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    uuid2 = '0000-1111-2222-3333-4444'
    backend_id = '5555-6666-7777-8888-9999'
    with open(tmp_path / 'subcontainer.yaml', 'w') as f:
        f.write(f"""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - /.uuid/{uuid2}
 - /subcontainer
backends:
  storage:
    - type: delegate
      backend-id: {backend_id}
      reference-container: 'wildland:@default:@parent-container:'
      subdirectory: '/subdir'
""")
    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container', '--subcontainer', './subcontainer.yaml')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        container_data = f.read().split('\n', 4)[-1]
        uuid1 = re.search(r'/.uuid/(.+?)\\n', container_data).group(1)

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--only-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 1
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['storage']['type'] == 'delegate'
    assert command[0]['storage']['container-path'] == f'/.uuid/{uuid2}'
    assert command[0]['storage']['reference-container'] == f'wildland:@default:/.uuid/{uuid1}:'
    assert command[0]['storage']['subdirectory'] == '/subdir'
    assert command[0]['storage']['storage']['type'] == 'local'
    assert command[0]['storage']['storage']['location'] == os.fspath(tmp_path)
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid2}',
        '/.users/0xaaa:/subcontainer',
        f'/.uuid/{uuid2}',
        '/subcontainer',
    ]


def test_container_mount_local_subcontainers_trusted(cli, control_client, tmp_path):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    uuid = '0000-1111-2222-3333-4444'
    backend_id = '5555-6666-7777-8888-9999'
    with open(tmp_path / 'subcontainer.yaml', 'w') as f:
        f.write(f"""---
owner: '0xaaa'
paths:
 - /.uuid/{uuid}
 - /subcontainer
backends:
  storage:
    - type: delegate
      backend-id: {backend_id}
      reference-container: 'wildland:@default:@parent-container:'
      subdirectory: '/subdir'
""")
    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container', '--trusted', '--subcontainer', './subcontainer.yaml')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--only-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 1
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['storage']['type'] == 'delegate'
    assert sorted(command[0]['paths']) == [
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/subcontainer',
        f'/.uuid/{uuid}',
        '/subcontainer',
    ]


def test_container_mount_container_without_storage(cli, control_client):
    control_client.expect('status', {})
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    with pytest.raises(WildlandError, match='No valid storages found'):
        cli('container', 'mount', 'Container')


def test_container_unmount(cli, base_dir, control_client):
    control_client.expect('status', {})
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {
        f'/.users/0xaaa:/.uuid/{uuid}': [101],
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}': [102],
        f'/.uuid/{uuid}': [103],
        f'/.backends/{uuid}/{backend_id}': [104],
        '/PATH': [105],
    })
    control_client.expect('unmount')
    cli('container', 'unmount', 'Container', '--without-subcontainers')

    # /.users/{owner}:/.backends/{cont_uuid}/{backend_uuid} is always the primary path
    assert control_client.calls['unmount']['storage_id'] == 102


def test_container_other_signer(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa', '--add-pubkey', 'key.0xbbb')
    cli('user', 'create', 'User2', '--key', '0xbbb')

    cli('container', 'create', 'Container', '--path', '/PATH', '--owner', 'User2')

    modify_file(base_dir / 'containers/Container.container.yaml',
                "owner: '0xbbb'", "owner: '0xaaa'")

    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')


def test_container_unmount_by_path(cli, control_client):
    control_client.expect('paths', {
        '/PATH': [101],
        '/PATH2': [102],
    })
    control_client.expect('unmount')
    control_client.expect('status', {})
    cli('container', 'unmount', '--path', '/PATH2', '--without-subcontainers')

    assert control_client.calls['unmount']['storage_id'] == 102


def test_container_create_missing_params(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')

    with pytest.raises(CliError, match='--category option requires --title'
                                       ' or container name'):
        cli('container', 'create', '--path', '/PATH',
            '--category', '/c1/c2', '--category', '/c3')


def test_container_extended_paths(cli, control_client, base_dir):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'title',
        '--category', '/c1/c2', '--category', '/c3', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'

    assert sorted(command[0]['paths']) == sorted([
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        '/.users/0xaaa:/c1/c2/@c3/title',
        '/.users/0xaaa:/c1/c2/title',
        '/.users/0xaaa:/c3/@c1/c2/title',
        '/.users/0xaaa:/c3/title',
        f'/.uuid/{uuid}',
        '/PATH',
        '/c1/c2/@c3/title',
        '/c1/c2/title',
        '/c3/@c1/c2/title',
        '/c3/title'
    ])

    modify_file(base_dir / 'config.yaml', "'@default': '0xaaa'", '')

    # The command should not contain the default path.
    cli('container', 'mount', 'Container')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xaaa'
    assert sorted(command[0]['paths']) == [
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        '/.users/0xaaa:/c1/c2/@c3/title',
        '/.users/0xaaa:/c1/c2/title',
        '/.users/0xaaa:/c3/@c1/c2/title',
        '/.users/0xaaa:/c3/title',
    ]
    assert command[0]['extra']['trusted_owner'] is None


def test_container_wrong_signer(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb')

    cli('container', 'create', 'Container', '--path', '/PATH', '--owner', 'User2')

    modify_file(base_dir / 'containers/Container.container.yaml',
                "owner: '0xbbb'", "owner: '0xaaa'")

    with pytest.raises(ManifestError, match='Manifest owner does not have access to signing key'):
        cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
            '--container', 'Container')


## Status


def test_status(cli, control_client):
    control_client.expect('status', {})
    control_client.expect('info', {
        '1': {
            'paths': ['/path1', '/path1.1'],
            'type': 'local',
            'extra': {},
        },
        '2': {
            'paths': ['/path2', '/path2.1'],
            'type': 's3',
            'extra': {},
        },
    })

    result = cli('status', capture=True)
    out_lines = result.splitlines()
    assert '/path1' in out_lines
    assert '  storage: local' in out_lines
    assert '    /path1' in out_lines
    assert '    /path1.1' in out_lines
    assert '/path2' in out_lines
    assert '  storage: s3' in out_lines
    assert '    /path2' in out_lines
    assert '    /path2.1' in out_lines


## Bridge


def test_bridge_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'RefUser', '--key', '0xbbb', '--path', '/OriginalPath')

    cli('bridge', 'create', 'Bridge',
        '--ref-user', 'RefUser',
        '--ref-user-location', 'https://example.com/RefUser.yaml',
        '--ref-user-path', '/ModifiedPath',
    )

    data = (base_dir / 'bridges/Bridge.bridge.yaml').read_text()
    assert 'user: https://example.com/RefUser.yaml' in data
    assert 'pubkey: key.0xbbb' in data
    assert '- /ModifiedPath' in data
    assert '- /OriginalPath' not in data


# Test the CLI tools directly (cannot easily use above-mentioned methods because of demonization)

def wl_call(base_config_dir, *args):
    subprocess.check_call(['./wl', '--base-dir', base_config_dir, *args])


def wl_call_output(base_config_dir, *args):
    return subprocess.check_output(['./wl', '--base-dir', base_config_dir, *args])


# container-sync


def test_cli_container_sync(tmpdir, cleanup):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'
    storage2_data = base_data_dir / 'storage2'

    os.mkdir(base_config_dir)
    os.mkdir(base_data_dir)
    os.mkdir(storage1_data)
    os.mkdir(storage2_data)

    cleanup(lambda: wl_call(base_config_dir, 'container', 'stop-sync', 'AliceContainer'))

    wl_call(base_config_dir, 'user', 'create', 'Alice')
    wl_call(base_config_dir, 'container', 'create',
            '--owner', 'Alice', '--path', '/Alice', 'AliceContainer')
    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage1_data)
    wl_call(base_config_dir, 'storage', 'create', 'local-cached',
            '--container', 'AliceContainer', '--location', storage2_data)
    wl_call(base_config_dir, 'container', 'sync', '--target-storage', 'local-cached',
            'AliceContainer')

    time.sleep(1)

    with open(storage1_data / 'testfile', 'w') as f:
        f.write("test data")

    time.sleep(1)

    assert (storage2_data / 'testfile').exists()
    with open(storage2_data / 'testfile') as file:
        assert file.read() == 'test data'


def test_cli_container_sync_oneshot(tmpdir):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'
    storage2_data = base_data_dir / 'storage2'

    os.mkdir(base_config_dir)
    os.mkdir(base_data_dir)
    os.mkdir(storage1_data)
    os.mkdir(storage2_data)

    wl_call(base_config_dir, 'user', 'create', 'Alice')
    wl_call(base_config_dir, 'container', 'create',
            '--owner', 'Alice', '--path', '/Alice', 'AliceContainer')
    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage1_data)
    wl_call(base_config_dir, 'storage', 'create', 'local-cached',
            '--container', 'AliceContainer', '--location', storage2_data)

    with open(storage1_data / 'testfile', 'w') as f:
        f.write("test data")

    wl_call(base_config_dir, 'container', 'sync', '--target-storage', 'local-cached', '--one-shot',
            'AliceContainer')

    time.sleep(1)

    assert (storage2_data / 'testfile').exists()
    with open(storage2_data / 'testfile') as file:
        assert file.read() == 'test data'

    with open(storage1_data / 'testfile2', 'w') as f:
        f.write("test data2")

    time.sleep(1)

    assert not (storage2_data / 'testfile2').exists()


def test_cli_container_sync_tg_remote(tmpdir, cleanup):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'
    storage2_data = base_data_dir / 'storage2'
    storage3_data = base_data_dir / 'storage3'

    os.mkdir(base_config_dir)
    os.mkdir(base_data_dir)
    os.mkdir(storage1_data)
    os.mkdir(storage2_data)
    os.mkdir(storage3_data)

    cleanup(lambda: wl_call(base_config_dir, 'container', 'stop-sync', 'AliceContainer'))

    wl_call(base_config_dir, 'user', 'create', 'Alice')
    wl_call(base_config_dir, 'container', 'create',
            '--owner', 'Alice', '--path', '/Alice', 'AliceContainer', '--no-encrypt-manifest')
    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage1_data)
    wl_call(base_config_dir, 'storage', 'create', 'local-cached',
            '--container', 'AliceContainer', '--location', storage2_data)
    wl_call(base_config_dir, 'storage', 'create', 'local-dir-cached',
            '--container', 'AliceContainer', '--location', storage3_data)
    wl_call(base_config_dir, 'container', 'sync', '--target-storage', 'local-dir-cached',
            'AliceContainer')

    time.sleep(1)

    with open(storage1_data / 'testfile', 'w') as f:
        f.write("test data")

    time.sleep(1)

    assert (storage3_data / 'testfile').exists()
    assert not (storage2_data / 'testfile').exists()
    with open(storage3_data / 'testfile') as file:
        assert file.read() == 'test data'

    with open(base_config_dir / 'containers/AliceContainer.container.yaml') as f:
        cont_data = f.read().split('\n', 4)[-1]
        cont_yaml = load_yaml(cont_data)

    container_id = cont_yaml['paths'][0][7:]
    assert cont_yaml['backends']['storage'][2]['type'] == 'local-dir-cached'
    backend_id = cont_yaml['backends']['storage'][2]['backend-id']

    with open(base_config_dir / 'config.yaml') as f:
        data = f.read()

    config = load_yaml(data)
    default_storage = config["default-remote-for-container"]
    assert default_storage[container_id] == backend_id

    wl_call(base_config_dir, 'container', 'stop-sync', 'AliceContainer')
    wl_call(base_config_dir, 'container', 'sync', 'AliceContainer')

    time.sleep(1)

    with open(storage1_data / 'testfile2', 'w') as f:
        f.write("get value from config")

    time.sleep(1)

    assert (storage3_data / 'testfile2').exists()
    assert not (storage2_data / 'testfile2').exists()
    with open(storage3_data / 'testfile2') as file:
        assert file.read() == "get value from config"


def test_container_list_conflicts(tmpdir):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'
    storage2_data = base_data_dir / 'storage2'
    storage3_data = base_data_dir / 'storage3'

    os.mkdir(base_config_dir)
    os.mkdir(base_data_dir)
    os.mkdir(storage1_data)
    os.mkdir(storage2_data)
    os.mkdir(storage3_data)

    wl_call(base_config_dir, 'user', 'create', 'Alice')
    wl_call(base_config_dir, 'container', 'create',
            '--owner', 'Alice', '--path', '/Alice', 'AliceContainer', '--no-encrypt-manifest')
    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage1_data)
    wl_call(base_config_dir, 'storage', 'create', 'local-cached',
            '--container', 'AliceContainer', '--location', storage2_data)
    wl_call(base_config_dir, 'storage', 'create', 'local-dir-cached',
            '--container', 'AliceContainer', '--location', storage3_data)

    with open(storage1_data / 'file1', mode='w') as f:
        f.write('aaaa')
    with open(storage2_data / 'file1', mode='w') as f:
        f.write('bbbb')
    with open(storage3_data / 'file1', mode='w') as f:
        f.write('cccc')

    output = wl_call_output(base_config_dir, 'container', 'list-conflicts', 'AliceContainer')
    conflicts = output.decode().splitlines()
    assert len(conflicts) == 4
    assert conflicts[1] != conflicts[2] and conflicts[2] != conflicts[3]

    os.unlink(storage1_data / 'file1')
    os.unlink(storage2_data / 'file1')
    os.mkdir(storage2_data / 'file1')

    output = wl_call_output(base_config_dir, 'container', 'list-conflicts', 'AliceContainer')
    conflicts = output.decode().splitlines()
    assert len(conflicts) == 2
    assert 'file1' in conflicts[1]


# Encryption of inline storage manifests


def test_container_edit_inline_storage(tmpdir):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'

    alice_output = wl_call_output(base_config_dir, 'user', 'create', 'Alice')
    alice_key = alice_output.decode().splitlines()[0].split(' ')[2]
    wl_call(base_config_dir, 'user', 'create', 'Bob')

    wl_call(base_config_dir, 'container', 'create',
            '--owner', 'Alice', '--path', '/Alice', '--access', 'Bob', 'AliceContainer')

    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage1_data, '--access', 'Alice')

    os.unlink(base_config_dir / f'keys/{alice_key}.sec')

    container_list = wl_call_output(base_config_dir, 'container', 'list').decode()
    assert '/Alice' in container_list  # main container data is decrypted
    assert 'encrypted' in container_list  # but the storage is encrypted
    assert 'location' not in container_list  # and it's data is inaccesible


def test_dump(tmpdir):
    base_config_dir = tmpdir / '.wildland'
    base_data_dir = tmpdir / 'wldata'
    storage1_data = base_data_dir / 'storage1'

    alice_output = wl_call_output(base_config_dir, 'user', 'create', 'Alice')
    alice_key = alice_output.decode().splitlines()[0].split(' ')[2]
    wl_call(base_config_dir, 'user', 'create', 'Bob')

    wl_call(base_config_dir, 'container', 'create',
            '--owner', 'Alice', '--path', '/Alice', '--access', 'Bob', 'AliceContainer')

    wl_call(base_config_dir, 'storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage1_data, '--access', 'Alice')

    dump_container = wl_call_output(base_config_dir, 'container', 'dump', 'AliceContainer').decode()
    yaml_container = yaml.safe_load(dump_container)
    assert 'enc' not in dump_container
    assert '/Alice' in dump_container

    assert yaml_container['object'] == 'container'

    os.unlink(base_config_dir / f'keys/{alice_key}.sec')

    dump_container = wl_call_output(base_config_dir, 'container', 'dump', 'AliceContainer').decode()
    yaml_container = yaml.safe_load(dump_container)

    assert 'encrypted' in dump_container
    assert yaml_container['object'] == 'container'

# Storage sets/templates


def test_cli_storage_template_create(cli, base_dir):
    cli('storage-template', 'create', 'local', '--location', '/foo', 't1')

    with open(base_dir / 'templates/t1.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == {'type': 'local',
                             'location': '/foo{{ local_dir if local_dir is defined else \'/\' }}',
                             'read-only': False}


def test_cli_storage_template_create_custom_access(cli, base_dir):
    cli('user', 'create', 'UserA', '--key', '0xaaa')
    cli('user', 'create', 'UserB', '--key', '0xbbb')
    cli('storage-template', 'create', 'local', '--location', '/foo',
        '--access', 'UserA', '--access', 'UserB', 't1')

    with open(base_dir / 'templates/t1.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == {'type': 'local',
                             'location': '/foo{{ local_dir if local_dir is defined else \'/\' }}',
                             'read-only': False,
                             'access': [{'user': '0xaaa'}, {'user': '0xbbb'}]}

    cli('storage-template', 'create', 'local', '--location', '/foo',
        '--access', '*', 't2')

    with open(base_dir / 'templates/t2.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == {'type': 'local',
                             'location': '/foo{{ local_dir if local_dir is defined else \'/\' }}',
                             'read-only': False,
                             'access': [{'user': '*'}]}

    with pytest.raises(CliError, match='Failed to create storage template: user not found: *'):
        cli('storage-template', 'create', 'local', '--location', '/foo',
            '--access', '*', '--access', 'UserA', 't3')


def test_cli_storage_template_filename_exists(cli):
    cli('storage-template', 'create', 'local', '--location', '/foo', 't1')

    with pytest.raises(CliError, match='already exists'):
        cli('storage-template', 'create', 'local', '--location', '/foo', 't1')


def test_cli_remove_storage_template(cli, base_dir):
    cli('storage-template', 'create', 'local', '--location', '/foo', 't1')

    assert Path(base_dir / 'templates/t1.template.jinja').exists()

    cli('storage-template', 'remove', 't1')

    assert not Path(base_dir / 'templates/t1.template.jinja').exists()


def test_cli_remove_nonexisting_storage_template(cli):
    with pytest.raises(CliError, match='does not exist'):
        cli('storage-template', 'remove', 't1')


def test_cli_remove_assigned_storage_template(cli):
    cli('storage-template', 'create', 'local', '--location', '/foo', 't1')
    cli('storage-set', 'add', '--template', 't1', 'set1')

    with pytest.raises(CliError, match=r'Template (.+?) is attached to following sets: (.+?)'):
        cli('storage-template', 'remove', 't1')


def test_cli_remove_assigned_storage_template_force(cli, base_dir):
    cli('storage-template', 'create', 'local', '--location', '/foo', 't1')
    cli('storage-set', 'add', '--template', 't1', 'set1')

    cli('storage-template', 'remove', 't1', '--force')

    assert not Path(base_dir / 'templates/t1.template.jinja').exists()
    assert Path(base_dir / 'templates/set1.set.yaml').exists()


def test_cli_remove_assigned_storage_template_cascade(cli, base_dir):
    cli('storage-template', 'create', 'local', '--location', '/foo', 't1')
    cli('storage-set', 'add', '--template', 't1', 'set1')

    cli('storage-template', 'remove', 't1', '--cascade')

    assert not Path(base_dir / 'templates/t1.template.jinja').exists()
    assert not Path(base_dir / 'templates/set1.set.yaml').exists()


def test_template_parsing(cli, base_dir):
    cli('user', 'create', 'User')
    cli('storage-template', 'create', 'webdav',
        '--url', 'https://{{ paths|first }}/{{ title }}',
        '--login', '{{ categories | first }}',
        '--password', '{{ categories | last }}',
        't1')
    cli('storage-set', 'add', '--inline', 't1', 'set1')
    cli('container', 'create', 'Container', '--path', '/PATH',
        '--storage-set', 'set1', '--no-encrypt-manifest',
        '--title', 'foobar', '--category', '/boo!foo:hoo', '--category', '/żółć')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))
        uuid_path = documents[1]['paths'][0]

    data = (base_dir / 'containers/Container.container.yaml').read_text()

    assert f'url: https://{uuid_path}/foobar' in data
    assert 'login: /boo!foo:hoo' in data
    assert 'password: "/\\u017C\\xF3\\u0142\\u0107"' in data


def setup_storage_sets(cli, config_dir):
    cli('storage-template', 'create', 'local', '--location', f'{config_dir}' + '/{{ uuid }}', 't1')
    cli('storage-template', 'create', 'local', '--location', f'{config_dir}' + '/{{ uuid }}', 't2')
    cli('storage-template', 'create', 'local', '--location', f'{config_dir}' + '/{{ uuid }}', 't3')


def test_cli_set_add(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set1')
    cli('storage-set', 'add', '--inline', 't3', '--inline', 't2', 'set2')

    with open(base_dir / 'templates/set1.set.yaml', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == {'name': 'set1',
                             'templates':
                                 [{'file': 't1.template.jinja', 'type': 'file'},
                                  {'file': 't2.template.jinja', 'type': 'inline'}]}
    with open(base_dir / 'templates/set2.set.yaml', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == {'name': 'set2',
                             'templates':
                                 [{'file': 't3.template.jinja', 'type': 'inline'},
                                  {'file': 't2.template.jinja', 'type': 'inline'}]}


def test_cli_set_modify(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('storage-set', 'add', '--template', 't1', 'set1')

    with open(base_dir / 'templates/set1.set.yaml', 'r') as f:
        read_data = yaml.load(f, Loader=yaml.SafeLoader)
        assert read_data == {'name': 'set1',
                             'templates':
                                 [{'file': 't1.template.jinja', 'type': 'file'}]}

    cli('storage-set', 'modify', 'add-template', '-t', 't2', '-i', 't3', 'set1')
    with open(base_dir / 'templates/set1.set.yaml', 'r') as f:
        read_data = yaml.load(f, Loader=yaml.SafeLoader)
        assert read_data == {'name': 'set1',
                             'templates':
                                 [{'file': 't1.template.jinja', 'type': 'file'},
                                  {'file': 't2.template.jinja', 'type': 'file'},
                                  {'file': 't3.template.jinja', 'type': 'inline'}]}

    cli('storage-set', 'modify', 'del-template', '-t', 't2', 'set1')
    with open(base_dir / 'templates/set1.set.yaml', 'r') as f:
        read_data = yaml.load(f, Loader=yaml.SafeLoader)
        assert read_data == {'name': 'set1',
                             'templates':
                                 [{'file': 't1.template.jinja', 'type': 'file'},
                                  {'file': 't3.template.jinja', 'type': 'inline'}]}

    with pytest.raises(WildlandError):
        cli('storage-set', 'modify', 'add-template', '-t', 't2', 'set123')
    with pytest.raises(WildlandError):
        cli('storage-set', 'modify', 'del-template', '-t', 't2', 'set123')
    with pytest.raises(WildlandError):
        cli('storage-set', 'modify', 'add-template', '-t', 't2123', 'set1')
    with pytest.raises(WildlandError):
        cli('storage-set', 'modify', 'del-template', '-t', 't2', 'set123')


def test_cli_set_list(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set1')
    cli('storage-set', 'add', '--inline', 't3', '--inline', 't2', 'set2')

    result = cli('storage-set', 'list', capture=True)
    out_lines = [l.strip() for l in result.splitlines()]
    assert 't1' in out_lines
    assert 't2' in out_lines
    assert 't3' in out_lines
    assert 'set1 (file: t1) (inline: t2)' in out_lines
    assert 'set2 (inline: t3, t2)' in out_lines


def test_cli_set_del(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set1')

    expected_file = base_dir / 'templates/set1.set.yaml'
    assert expected_file.exists()

    cli('storage-set', 'remove', 'set1')

    assert not expected_file.exists()


def test_cli_set_use_inline(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'object': 'storage',
        'location':  f'{base_dir}' + '/{{ title }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test',
        '--storage-set', 'set1', '--no-encrypt-manifest')

    data = (base_dir / 'containers/Container.container.yaml').read_text()
    assert f'location: {base_dir}/Test' in data
    assert 'type: local' in data

    assert (base_dir / 'Test').exists()


def test_cli_set_use_file(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'object': 'storage',
        'location':  f'{base_dir}' + '/{{ title }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--template', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test',
        '--storage-set', 'set1')

    data = (base_dir / 'containers/Container.container.yaml').read_text()
    assert f'file://localhost{base_dir}/storage/set1.storage.yaml' in data

    assert (base_dir / 'Test').exists()


def test_cli_set_missing_title(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'object': 'storage',
        'location':  f'{base_dir}' +
                 '/{% if title is defined -%} {{ title }} {% else -%} test {% endif %}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH',
        '--storage-set', 'set1', '--no-encrypt-manifest')

    data = (base_dir / 'containers/Container.container.yaml').read_text()

    assert f'location: {base_dir}/test' in data
    assert 'type: local' in data


def test_cli_set_missing_param(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'object': 'storage',
        'location':  f'{base_dir}' + '{{ title }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    with pytest.raises(WildlandError, match='\'title\' is undefined'):
        cli('container', 'create',
            'Container', '--path', '/PATH', '--storage-set', 'set1', capture=True)

    assert not (base_dir / 'containers/Container.container.yaml').exists()


def test_cli_set_local_dir(cli, base_dir):
    os.mkdir(base_dir / 'templates')
    data_dict = {
        'object': 'storage',
        'location':  f'{base_dir}' + '/{{ local_dir[1:] }}',
        'type': 'local'
    }

    yaml.dump(data_dict, open(base_dir / 'templates/title.template.jinja', 'w'))
    cli('storage-set', 'add', '--inline', 'title', 'set1')
    cli('user', 'create', 'User')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test',
        '--storage-set', 'set1', '--local-dir', '/test/test')

    data = (base_dir / 'containers/Container.container.yaml').read_text()

    assert f'location: {base_dir}/test/test' in data
    assert 'type: local' in data

    assert (base_dir / 'test/test').exists()


def test_user_create_default_set(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('user', 'create', 'User')
    cli('storage-set', 'add', '--template', 't1', '--inline', 't2', 'set')
    cli('storage-set', 'set-default', '--user', 'User', 'set')

    with open(base_dir / 'config.yaml') as f:
        data = f.read()

    config = load_yaml(data)
    default_user = config["@default-owner"]
    assert f'\'{default_user}\': set' in data


def test_cli_set_use_default(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('user', 'create', 'User')
    cli('storage-set', 'add', '--template', 't1', 'set')
    cli('storage-set', 'set-default', '--user', 'User', 'set')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test')

    data = (base_dir / 'containers/Container.container.yaml').read_text()

    assert f'file://localhost{base_dir}/storage/set.storage.yaml' in data


def test_cli_set_use_def_storage(cli, base_dir):
    setup_storage_sets(cli, base_dir)
    cli('user', 'create', 'User')
    cli('storage-set', 'add', '--template', 't1', 'set')
    cli('storage-set', 'set-default', '--user', 'User', 'set')

    cli('container', 'create', 'Container', '--path', '/PATH', '--title', 'Test')
    cli('storage', 'create-from-set', 'Container')

    data = (base_dir / 'containers/Container.container.yaml').read_text()

    assert f'file://localhost{base_dir}/storage/set.storage.yaml' in data


def test_different_default_user(cli, base_dir):
    storage_dir = base_dir / 'storage_dir'
    os.mkdir(storage_dir)

    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')
    cli('container', 'create',
            '--owner', 'Bob', '--path', '/Bob', 'BobContainer')
    cli('storage', 'create', 'local',
            '--container', 'BobContainer', '--location', storage_dir)
    cli('container', 'create',
            '--owner', 'Alice', '--path', '/Alice', 'AliceContainer')
    cli('storage', 'create', 'local',
            '--container', 'AliceContainer', '--location', storage_dir)

    cli('start', '--default-user', 'Bob')
    cli('container', 'mount', 'BobContainer')
    cli('container', 'mount', 'AliceContainer')

    assert 'Bob' in os.listdir(base_dir / 'mnt')
    assert 'Alice' not in os.listdir(base_dir / 'mnt')


def _create_user_manifest(owner: str, path: str = '/PATH',
                          infrastructure_path: str = None) -> bytes:
    if infrastructure_path:
        infrastructure = f'''
- object: container
  owner: '{owner}'
  paths:
  - /manifests
  backends:
    storage:
    - owner: '{owner}'
      container-path: /manifests
      type: local
      location: {infrastructure_path}
      manifest-pattern:
        type: glob
        path: /{{path}}.yaml
'''

    else:
        infrastructure = '[]'
    data = f'''signature: |
  dummy.{owner}
---
object: user
owner: '{owner}'
paths:
- {path}
infrastructures: {infrastructure}
pubkeys:
- key.{owner}
'''
    return data.encode()


def _create_bridge_manifest(owner: str, location: str, pubkey: str) -> bytes:
    test_bridge_data = f'''signature: |
  dummy.{owner}
---
object: bridge
owner: '{owner}'
user: {location}
pubkey: key.{pubkey}
paths:
- /IMPORT
'''

    return test_bridge_data.encode()


def test_import_user(cli, base_dir, tmpdir):
    test_data = _create_user_manifest('0xbbb')
    destination = tmpdir / 'Bob.user.yaml'
    destination.write(test_data)

    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')
    cli('user', 'import', str(destination))

    assert (base_dir / 'users/Bob.user.yaml').read_bytes() == test_data

    bridge_data = (base_dir / 'bridges/Bob.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xaaa\'' in bridge_data
    assert f'user: file://localhost{destination}' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert 'paths:\n- /PATH' in bridge_data

    destination.write(_create_user_manifest('0xccc'))
    cli('user', 'import', '--path', '/IMPORT', str(destination))

    assert (base_dir / 'users/Bob.1.user.yaml').read_bytes() == _create_user_manifest('0xccc')

    bridge_data = (base_dir / 'bridges/Bob.1.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xaaa\'' in bridge_data
    assert f'user: file://localhost{destination}' in bridge_data
    assert 'pubkey: key.0xccc' in bridge_data
    assert 'paths:\n- /IMPORT' in bridge_data

    destination.write(_create_user_manifest('0xeee'))
    cli('user', 'import', '--path', '/IMPORT', 'file://' + str(destination))

    assert (base_dir / 'users/Bob.2.user.yaml').read_bytes() == _create_user_manifest('0xeee')


def test_import_bridge(cli, base_dir, tmpdir):
    test_user_data = _create_user_manifest('0xbbb')
    user_destination = tmpdir / 'Bob.user.yaml'
    user_destination.write(test_user_data)

    test_bridge_data = _create_bridge_manifest(
        '0xbbb', f"file://localhost{str(user_destination)}", '0xbbb')

    bridge_destination = tmpdir / 'BobBridge.bridge.yaml'
    bridge_destination.write(test_bridge_data)

    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')
    cli('user', 'import', str(bridge_destination))

    assert (base_dir / 'users/Bob.user.yaml').read_bytes() == test_user_data

    bridge_data = (base_dir / 'bridges/BobBridge.bridge.yaml').read_text()

    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xaaa\'' in bridge_data
    assert f'user: file://localhost{user_destination}' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert 'paths:\n- /IMPORT' in bridge_data


def test_import_user_wl_path(cli, base_dir, tmpdir):
    test_data = _create_user_manifest('0xbbb')

    storage_dir = tmpdir / 'storage'
    os.mkdir(storage_dir)
    destination = storage_dir / 'Bob.user.yaml'
    destination.write(test_data)

    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')
    cli('container', 'create', '--path', '/STORAGE', 'Cont')
    cli('storage', 'create', 'local', '--container', 'Cont', '--location', storage_dir)

    cli('user', 'import', 'wildland:0xaaa:/STORAGE:/Bob.user.yaml')

    assert (base_dir / 'users/Bob.user.yaml').read_bytes() == test_data

    bridge_data = (base_dir / 'bridges/Bob.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xaaa\'' in bridge_data
    assert 'user: wildland:0xaaa:/STORAGE:/Bob.user.yaml' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert 'paths:\n- /PATH' in bridge_data


def test_import_bridge_wl_path(cli, base_dir, tmpdir):
    bob_dir = tmpdir / 'bob'
    os.mkdir(bob_dir)
    bob_manifest_location = bob_dir / 'Bob.user.yaml'
    bob_user_manifest = _create_user_manifest('0xbbb', '/BOB')
    bob_manifest_location.write(bob_user_manifest)

    alice_dir = tmpdir / 'alice'
    os.mkdir(alice_dir)
    alice_manifest_location = alice_dir / 'Alice.user.yaml'

    bob_bridge_dir = tmpdir / 'manifests'
    os.mkdir(bob_bridge_dir)
    bob_bridge_location = bob_bridge_dir / 'IMPORT.yaml'
    bob_bridge_location.write(_create_bridge_manifest(
        '0xaaa', f'file://localhost{bob_manifest_location}', '0xbbb'))

    alice_manifest_location.write(_create_user_manifest('0xaaa', '/ALICE', str(bob_bridge_dir)))

    cli('user', 'create', 'DefaultUser', '--key', '0xddd')

    cli('bridge', 'create', '--owner', 'DefaultUser',
        '--ref-user-location', f'file://localhost{alice_manifest_location}', 'Alice')

    modify_file(base_dir / 'config.yaml', "local-owners:\n- '0xddd'",
                "local-owners:\n- '0xddd'\n- '0xaaa'")

    cli('-vvvvv', 'user', 'import', 'wildland:0xddd:/ALICE:/IMPORT:')

    bridge_data = (base_dir / 'bridges/0xddd__ALICE__IMPORT_.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xddd\'' in bridge_data
    assert f'file://localhost{bob_manifest_location}' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert 'paths:\n- /IMPORT' in bridge_data

    assert (base_dir / 'users/Bob.user.yaml').read_bytes() == bob_user_manifest


def test_import_user_bridge_owner(cli, base_dir, tmpdir):
    test_data = _create_user_manifest('0xbbb')
    destination = tmpdir / 'Bob.user.yaml'
    destination.write(test_data)

    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')
    cli('user', 'create', 'Carol', '--key', '0xccc')
    cli('user', 'import', '--bridge-owner', 'Carol', str(destination))

    assert (base_dir / 'users/Bob.user.yaml').read_bytes() == test_data

    bridge_data = (base_dir / 'bridges/Bob.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xccc\'' in bridge_data
    assert f'user: file://localhost{destination}' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert 'paths:\n- /PATH' in bridge_data


def test_import_user_existing(cli, base_dir, tmpdir):
    test_data = _create_user_manifest('0xbbb')
    destination = tmpdir / 'Bob.user.yaml'
    destination.write(test_data)

    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')
    cli('user', 'import', str(destination))

    # nothing should be imported if the user already exists locally
    assert len(os.listdir(base_dir / 'users')) == 2


def test_only_subcontainers(cli, base_dir, control_client):
    control_client.expect('status', {})

    parent_container_path = base_dir / 'containers/Parent.container.yaml'
    child_container_path = base_dir / 'containers/Child.container.yaml'
    child_storage_dir = base_dir / 'foo'
    child_storage_file = base_dir / 'foo/file'

    child_storage_dir.mkdir()
    child_storage_file.write_text('hello')

    cli('user', 'create', 'User',
        '--key', '0xaaa')
    cli('user', 'create', 'Malicious',
        '--key', '0xbbb')
    cli('container', 'create', 'Parent',
        '--no-encrypt-manifest',
        '--path', '/PATH_PARENT',
        '--owner', '0xaaa')
    cli('storage', 'create', 'local',
        '--location', base_dir / 'containers',
        '--container', 'Parent',
        '--subcontainer', './Child.container.yaml',
        '--subcontainer', './MaliciousChild.container.yaml')
    cli('container', 'create', 'Child',
        '--no-encrypt-manifest',
        '--path', '/PATH_CHILD',
        '--owner', '0xaaa')
    cli('storage', 'create', 'local',
        '--location', base_dir / 'foo',
        '--container', 'Child')
    cli('container', 'create', 'MaliciousChild',
        '--no-encrypt-manifest',
        '--path', '/PATH_CHILD_B',
        '--owner', '0xbbb')
    cli('storage', 'create', 'local',
        '--location', base_dir / 'foo',
        '--container', 'MaliciousChild')

    # Sanity check of container files
    assert parent_container_path.exists()
    assert child_container_path.exists()

    # Extract containers auto-generated UUIDs
    with open(base_dir / 'containers/Parent.container.yaml') as f:
        documents = list(load_yaml_all(f))
        uuid_path_parent = documents[1]['paths'][0]
        backend_id_parent = documents[1]['backends']['storage'][0]['backend-id']

    with open(base_dir / 'containers/Child.container.yaml') as f:
        documents = list(load_yaml_all(f))
        uuid_path_child = documents[1]['paths'][0]
        backend_id_child = documents[1]['backends']['storage'][0]['backend-id']

    # Mount the parent container with subcontainers INCLUDING itself
    control_client.expect('paths', {})
    control_client.expect('mount')
    cli('container', 'mount', 'Parent')

    uuid_parent = get_container_uuid_from_uuid_path(uuid_path_parent)
    uuid_child = get_container_uuid_from_uuid_path(uuid_path_child)

    parent_paths = [
        f'/.backends/{uuid_parent}/{backend_id_parent}',
        f'/.users/0xaaa:/.backends/{uuid_parent}/{backend_id_parent}',
        f'/.users/0xaaa:/.uuid/{uuid_parent}',
        '/.users/0xaaa:/PATH_PARENT',
        f'/.uuid/{uuid_parent}',
        '/PATH_PARENT',
    ]

    child_paths = [
        f'/.backends/{uuid_child}/{backend_id_child}',
        f'/.users/0xaaa:/.backends/{uuid_child}/{backend_id_child}',
        f'/.users/0xaaa:/.uuid/{uuid_child}',
        '/.users/0xaaa:/PATH_CHILD',
        f'/.uuid/{uuid_child}',
        '/PATH_CHILD',
    ]

    # Verify the mounted paths
    command = control_client.calls['mount']['items']
    assert len(command) == 2
    assert sorted(command[0]['paths']) == parent_paths
    assert sorted(command[1]['paths']) == child_paths

    control_client.expect('info', {
        '1': {
            'paths': parent_paths,
            'type': 'local',
            'extra': {},
        },
        '2': {
            'paths': child_paths,
            'type': 'local',
            'extra': {'subcontainer_of': f'0xaaa:{uuid_path_parent}'},
        },
    })
    control_client.expect('unmount')

    # Unmount the parent+subcontainers mount
    cli('container', 'unmount', 'Parent')

    # Mount the parent container with subcontainers EXCLUDING itself
    cli('container', 'mount', 'Parent', '--only-subcontainers')

    # Verify the mounted paths
    command = control_client.calls['mount']['items']
    assert len(command) == 1
    assert sorted(command[0]['paths']) == child_paths


def test_user_refresh(cli, base_dir, tmpdir):
    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')

    # Import Alice user with path /FOO
    test_data = _create_user_manifest('0xbbb', path='/FOO')
    destination = tmpdir / 'Alice.user.yaml'
    destination.write(test_data)

    cli('user', 'import', str(destination))

    user_data = (base_dir / 'users/Alice.user.yaml').read_text()
    assert 'paths:\n- /FOO' in user_data

    # Refresh *all* users
    test_data = _create_user_manifest('0xbbb', path='/BAR')
    destination.write(test_data)

    cli('user', 'refresh')

    user_data = (base_dir / 'users/Alice.user.yaml').read_text()
    assert 'paths:\n- /BAR' in user_data

    # Refresh *only Alice*
    test_data = _create_user_manifest('0xbbb', path='/MEH')
    destination.write(test_data)

    cli('user', 'refresh', 'Alice')

    user_data = (base_dir / 'users/Alice.user.yaml').read_text()
    assert 'paths:\n- /MEH' in user_data


def test_file_find(cli, base_dir, control_client, tmpdir):
    control_client.expect('status', {})
    storage_dir = tmpdir / 'storage'
    os.mkdir(storage_dir)
    (storage_dir / 'file.txt').write('foo')

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', storage_dir,
        '--container', 'Container')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    uuid_path  = documents[1]['paths'][0]
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', 'Container')

    control_client.expect('fileinfo', {
        'storage': {
            'container-path': uuid_path,
            'backend-id': backend_id,
            'owner': '0xaaa',
            'read-only': False,
            'id': 'aaa',
        },
        'token': 'bbb'
    })

    result = cli('container', 'find', f'{base_dir}/mnt/PATH/file.txt', capture=True)

    assert result.splitlines() == [
        f'Container: wildland:0xaaa:{uuid_path}:',
        f'  Backend id: {backend_id}',
    ]

    control_client.expect('fileinfo', {})

    with pytest.raises(CliError, match='Given path was not found in any storage'):
        cli('container', 'find', f'{base_dir}/mnt/PATH/not_existing.txt', capture=True)

# Forest

def test_forest_create(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('storage-template', 'create', 'local', '--location', f'/{tmp_path}/wl-forest',
        '--base-url', f'file:///{tmp_path}/wl-forest', '--manifest-pattern', '/{path}.yaml', 'rw')
    cli('storage-template', 'create', 'local', '--location', f'/{tmp_path}/wl-forest',
        '--read-only', '--manifest-pattern', '/{path}.yaml', 'ro')
    cli('storage-set', 'add', '--inline', 'rw', '--inline', 'ro', 'my-set')

    cli('forest', 'create', '--manifest-local-dir', '/manifests', '--data-local-dir', '/storage',
        'Alice', 'my-set')

    assert Path(f'/{tmp_path}/wl-forest/manifests/Alice.yaml').exists()
    assert Path(f'/{tmp_path}/wl-forest/manifests/Alice-index.yaml').exists()
    assert Path(f'/{tmp_path}/wl-forest/manifests/.manifests/.manifests.yaml').exists()
    assert Path(f'/{tmp_path}/wl-forest/manifests/.manifests/home/Alice.yaml').exists()

## Global options (--help, --version etc.)

def test_wl_help(cli):
    result = cli('--help', capture=True)
    assert 'Usage:' in result
    assert 'Options:' in result
    assert 'Commands:' in result
    assert 'Aliases:' in result


def test_wl_version(cli):
    result = cli('--version', capture=True)
    assert 'version' in result
