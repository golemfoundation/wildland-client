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
from ..cli.cli_container import _resolve_container
from ..exc import WildlandError
from ..manifest.manifest import ManifestError, Manifest
from ..storage_backends.file_subcontainers import FileSubcontainersMixin
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

def test_version(base_dir):
    output = wl_call_output(base_dir, 'version').decode().strip('\n')
    version_regex = r'[0-9]+\.[0-9]+\.[0-9]+( \(commit [0-9a-f]+\))?$'
    assert re.match(version_regex, output) is not None


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


def test_user_list_encrypted_catalog(base_dir):
    wl_call(base_dir, 'user', 'create', '--path', '/USER', 'User')
    user_file = (base_dir / 'users/User.user.yaml')
    data = user_file.read_text()
    owner_key = re.search('owner: (.+?)\n', data).group(1)
    data = data.replace("manifests-catalog: []\n",
                        f'''
manifests-catalog:
- object: link
  storage:
    type: dummy
    access:
    - user: {owner_key}
  file: '/path'
''')
    user_file.write_text(data)

    wl_call(base_dir, 'user', 'sign', 'User')

    output = wl_call_output(base_dir, 'user', 'list').decode()
    assert 'enc' not in output
    assert 'dummy' in output


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


def test_user_add_pubkey_no_arguments(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')

    cli_fail('user', 'modify', 'add-pubkey', 'User')


def test_user_add_pubkey(cli, base_dir, cli_fail):
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

    cli_fail('user', 'modify', 'add-pubkey', 'User', '--pubkey', 'abc')


def test_user_add_pubkey_of_another_user(cli, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')

    cli('user', 'modify', 'add-pubkey', 'Alice', '--user', 'Bob')

    with open(base_dir / 'users/Alice.user.yaml') as f:
        data = [i.strip() for i in f.read().split()]

    assert data.count('key.0xaaa') == 1
    assert data.count('key.0xbbb') == 1


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


# Storage


def _create_user_container_storage(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-inline')


def test_storage_create(cli, base_dir):
    _create_user_container_storage(cli)

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
    _create_user_container_storage(cli)

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
    _create_user_container_storage(cli)

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    with pytest.raises(CliError, match='Storage is still used'):
        cli('storage', 'delete', '--no-cascade', 'Storage')

    cli('storage', 'delete', 'Storage')

    assert not storage_path.exists()


def test_storage_delete_force(cli, base_dir):
    _create_user_container_storage(cli)

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    with open(base_dir / 'containers/Container.container.yaml') as f:
        base_data = f.read().split('\n', 4)[-1]

    with pytest.raises(CliError, match='Storage is still used'):
        cli('storage', 'delete', '--no-cascade', 'Storage')

    cli('storage', 'delete', '--no-cascade', '--force', 'Storage')

    assert not storage_path.exists()
    assert str(storage_path) in base_data


def test_storage_delete_force_broken_manifest(cli, base_dir):
    _create_user_container_storage(cli)

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()

    # broke manifest
    with open(storage_path, 'r+') as f:
        f.truncate()

    with open(base_dir / 'containers/Container.container.yaml') as f:
        base_data = f.read().split('\n', 4)[-1]

    with pytest.raises(ManifestError):
        cli('storage', 'delete', 'Storage')

    cli('storage', 'delete', '--force', 'Storage')

    assert not storage_path.exists()
    assert str(storage_path) in base_data


def test_storage_delete_inline(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    with open(container_path) as f:
        documents = list(load_yaml_all(f))
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    with pytest.raises(CliError, match='Inline storage cannot be deleted'):
        cli('storage', 'delete', '--no-cascade', str(backend_id))

    cli('storage', 'delete', str(backend_id))

    assert backend_id not in container_path.read_text()


def test_storage_delete_inline_multiple_containers(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container0', '--path', '/PATH',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage0', '--location', '/PATH',
        '--container', 'Container0', '--inline')
    cli('container', 'create', 'Container1', '--path', '/PATH',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage1', '--location', '/PATH',
        '--container', 'Container1', '--inline')

    container_0_path = base_dir / 'containers/Container0.container.yaml'
    with open(container_0_path) as f:
        documents = list(load_yaml_all(f))
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    # replace backend-id in Container1
    container_1_path = base_dir / 'containers/Container1.container.yaml'
    with open(container_1_path, 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['backends']['storage'][0]['backend-id'] = backend_id
        f.seek(0)
        f.write('signature: |\n  dummy.0xaaa\n---\n')
        f.write(yaml.safe_dump(documents[1]))

    with pytest.raises(CliError, match='(...)(please specify container name with --container)'):
        cli('storage', 'delete', str(backend_id))

    cli('storage', 'delete', str(backend_id), '--container', 'Container0')

    assert backend_id in container_1_path.read_text()
    assert backend_id not in container_0_path.read_text()


def test_storage_delete_inline_many_in_one(monkeypatch, cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage0', '--location', '/PATH',
        '--container', 'Container', '--inline')
    cli('storage', 'create', 'local', 'Storage1', '--location', '/PATH',
        '--container', 'Container', '--inline')

    container_path = base_dir / 'containers/Container.container.yaml'
    with open(container_path, 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        backend_id = documents[1]['backends']['storage'][0]['backend-id']
        documents[1]['backends']['storage'][1]['backend-id'] = backend_id
        f.seek(0)
        f.write('signature: |\n  dummy.0xaaa\n---\n')
        f.write(yaml.safe_dump(documents[1]))

    monkeypatch.setattr('sys.stdin.readline', lambda: "n")
    cli('storage', 'delete', str(backend_id), '--container', 'Container')
    assert backend_id in container_path.read_text()

    monkeypatch.setattr('sys.stdin.readline', lambda: "y")
    cli('storage', 'delete', str(backend_id), '--container', 'Container')
    assert backend_id not in container_path.read_text()


def test_storage_delete_cascade(cli, base_dir):
    _create_user_container_storage(cli)

    storage_path = base_dir / 'storage/Storage.storage.yaml'
    assert storage_path.exists()
    container_path = base_dir / 'containers/Container.container.yaml'
    assert str(storage_path) in container_path.read_text()

    cli('storage', 'delete', 'Storage')
    assert not storage_path.exists()
    assert str(storage_path) not in container_path.read_text()


def test_storage_list(cli, base_dir):
    _create_user_container_storage(cli)

    ok = [
        str(base_dir / 'storage/Storage.storage.yaml'),
        '  type: local',
        '  location: /PATH',
    ]

    result = cli('storage', 'list', capture=True)
    result_lines = result.splitlines()
    backend_id_line = [line for line in result_lines if 'backend_id' in line][0]
    assert backend_id_line

    ok = [
        str(base_dir / 'storage/Storage.storage.yaml'),
        '  type: local',
        backend_id_line,
        '  location: /PATH',
    ]

    assert result.splitlines() == ok

    result = cli('storages', 'list', capture=True)
    assert result.splitlines() == ok


def test_storage_edit(cli, base_dir):
    _create_user_container_storage(cli)

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
    assert len(command) == 2
    backend3_paths = [
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id3}',
        f'/.backends/{uuid}/{backend_id3}',
    ]
    assert command[0]['paths'] == backend3_paths
    assert command[1]['paths'] == [
        backend3_paths[0] + '-pseudomanifest',
        backend3_paths[1]
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

    assert len(command) == 2

    expected_paths_backend = [
        f'/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid}',
        '/PATH',
    ]
    assert sorted(command[0]['paths']) == expected_paths_backend

    expected_paths_pseudomanifest = \
        expected_paths_backend[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid}/{backend_id2}-pseudomanifest'] + \
        expected_paths_backend[2:]
    assert sorted(command[1]['paths']) == expected_paths_pseudomanifest


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
    cli('container', 'create', 'Container', '--path', '/PATH', '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container', '--no-encrypt-manifest')

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
        old_backend_id, new_backend_id).splitlines().sort() == copy_data.splitlines().sort()


def test_container_duplicate_noinline(cli, base_dir):
    _create_user_container_storage(cli)

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


def test_container_set_title_remote_container(monkeypatch, cli, base_dir):
    # Create local forest so that container can be published somewhere
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('storage-template', 'create', 'local', '--location', base_dir, 'local-catalog',
        '--manifest-pattern', '/{path}.yaml')
    cli('container', 'create', 'Catalog', '--template', 'local-catalog',
        '--update-user', '--no-encrypt-manifest')

    with open(base_dir / 'containers/Catalog.container.yaml') as f:
        documents = list(load_yaml_all(f))

    catalog_dir = Path(documents[1]['backends']['storage'][0]['location'])

    # Create the container (with auto-publish)
    cli('container', 'create', 'Container', '--path', '/PATH')

    # Modify it right away (and auto-re-publish)
    cli('container', 'modify', 'set-title', 'Container.container', '--title', 'something')

    # Find it using forest catalog path
    with open(catalog_dir / 'PATH.yaml') as f:
        data = f.read()
    assert 'title: something' in data

    # Mock inbuilt string to pass startswith() check.
    # This is done to allow testing the is_url() logic but with local file.
    #
    # def _resolve_container(ctx: click.Context, path, callback, **callback_kwargs):
    #    if client.is_url(path) and not path.startswith('file:'):
    class MyStr(str):
        def __init__(self, *_args):
            super().__init__()
            self.visited = False

        def startswith(self, _str):
            if _str == 'file:' and not self.visited:
                self.visited = True
                return False

            return super().startswith(_str)

    def _cb(ctx, path, callback, **callback_kwargs):
        return _resolve_container(ctx, MyStr(path), callback, **callback_kwargs)

    monkeypatch.setattr("wildland.cli.cli_container._resolve_container", _cb)

    # Modify it again, although this time use file:// URL (and auto-re-publish)
    cli('container', 'modify', 'set-title', '--title', 'another thing',
        f'file://localhost/{base_dir}/containers/Container.container.yaml')

    # Check if it was re-published with updated title
    with open(catalog_dir / 'PATH.yaml') as f:
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


def test_container_delete_unpublish(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH', '--update-user')
    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'Container',
        '--inline',
        '--manifest-pattern', '/*.yaml')

    cli('container', 'publish', 'Container')

    assert len(tuple(tmp_path.glob('*.yaml'))) == 1

    cli('container', 'delete', 'Container')

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
        '--public-url', 'https://example.invalid/')

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


def test_container_publish_auto(cli, tmp_path):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'InfraContainer', '--path', '/PATH', '--update-user')
    assert not tuple(tmp_path.glob('*.yaml'))  # no infrastructure yet

    cli('storage', 'create', 'local', 'Storage',
        '--location', os.fspath(tmp_path),
        '--container', 'InfraContainer',
        '--inline',
        '--manifest-pattern', '/*.yaml')

    cli('container', 'create', 'NoPublic', '--path', '/PATH', '--no-publish')
    assert not tuple(tmp_path.glob('*.yaml'))  # --no-publish

    cli('container', 'create', 'Public', '--path', '/PATH')
    assert len(tuple(tmp_path.glob('*.yaml'))) == 1  # auto published


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
        '--public-url', 'https://example.invalid/')

    cli('container', 'publish', 'Container')

    assert (tmp_path / 'manifests/PA/TH1.yaml').exists()
    assert (tmp_path / 'manifests/PA/TH2.yaml').exists()
    assert not (tmp_path / 'manifests/PA/TH3.yaml').exists()

    # --no-publish', modification in progress
    cli('container', 'modify', 'del-path', 'Container', '--path', '/PA/TH2', '--no-publish')
    # auto republishing
    cli('container', 'modify', 'add-path', 'Container', '--path', '/PA/TH3')

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
    cli('bridge', 'create', '--target-user', 'Other',
                            '--path', '/users/other',
                            '--path', '/people:/other',
                            '--target-user-location',
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

    # add manifest catalog entry container
    with open(base_dir / 'users/Other.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['manifests-catalog'].append({
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
                            '--target-user', 'Bob',
                            '--path', '/users/bob',
                            '--path', '/people/bob',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'users/Bob.user.yaml'),
                            'br-bob')
    cli('bridge', 'create', '--owner', 'Alice',
                            '--target-user', 'Charlie',
                            '--path', '/users/charlie',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'users/Charlie.user.yaml'),
                            'br-charlie')
    cli('bridge', 'create', '--owner', 'Charlie',
                            '--target-user', 'Bob',
                            '--path', '/users/bob',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'users/Bob.user.yaml'),
                            'br-charlie-bob')
    # this should not be used, as it introduces a loop
    cli('bridge', 'create', '--owner', 'Bob',
                            '--target-user', 'Alice',
                            '--path', '/users/alice',
                            '--target-user-location',
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


def test_container_mount_catalog_err(monkeypatch, cli, base_dir, control_client):
    catalog_dir = base_dir / 'catalog'
    catalog_dir.mkdir()

    storage_dir = base_dir / 'storage_dir'
    storage_dir.mkdir()

    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Catalog', '--owner', 'User', '--path', '/CATALOG',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', str(catalog_dir),
        '--container', 'Catalog', '--manifest-pattern', '/*.yaml')

    cli('container', 'create', 'Mock1', '--owner', 'User', '--path', '/C',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', str(storage_dir),
        '--container', 'Mock1')
    cli('container', 'create', 'Mock2', '--owner', 'User', '--path', '/C',
        '--no-encrypt-manifest')
    cli('storage', 'create', 'local', 'Storage', '--location', str(storage_dir),
        '--container', 'Mock2')

    os.rename(base_dir / 'containers/Mock1.container.yaml', catalog_dir / 'Mock1.yaml')
    os.rename(base_dir / 'containers/Mock2.container.yaml', catalog_dir / 'Mock2.yaml')

    container_file = base_dir / 'containers/Catalog.container.yaml'
    cli('user', 'modify', 'add-catalog-entry', '--path', f'file://{str(container_file)}', 'User')

    # if first container is somehow broken, others should be mounted
    for file in os.listdir(catalog_dir):
        (catalog_dir / file).write_text('testdata')
        break

    control_client.expect('paths', {})
    control_client.expect('mount')

    output = []
    monkeypatch.setattr('click.echo', output.append)
    cli('container', 'mount', ':*:')

    command = control_client.calls['mount']['items']
    assert len(command) == 2
    paths_backend1 = command[0]['paths']
    paths_backend2 = command[1]['paths']
    assert [paths_backend1[0] + '-pseudomanifest'] + paths_backend1[1:] == paths_backend2


def test_container_mount_with_import(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'Other', '--key', '0xbbb')
    os.mkdir(base_dir / 'other-catalog')
    # add container to manifests catalog
    with open(base_dir / 'users/Other.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['manifests-catalog'].append({
            'paths': ['/.uuid/1111-2222-3333-4444'],
            'owner': '0xbbb',
            'object': 'container',
            'version': Manifest.CURRENT_VERSION,
            'backends': {'storage': [{
                'type': 'local',
                'location': str(base_dir / 'other-catalog'),
                'manifest-pattern': {
                    'type': 'glob',
                    'path': '/*.yaml',
                }
            }]}
        })
        f.seek(0)
        f.write('signature: |\n  dummy.0xbbb\n---\n')
        f.write(yaml.safe_dump(documents[1]))
    cli('container', 'create', 'Container', '--owner', 'Other', '--path', '/PATH', '--no-publish')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    # move user manifest out of the default path, so the bridge would be the only way to access it
    os.rename(base_dir / 'users/Other.user.yaml', base_dir / 'user-Other.user.yaml')
    # same for the container manifest
    os.rename(base_dir / 'containers/Container.container.yaml',
              base_dir / 'other-catalog/Container.container.yaml')
    cli('bridge', 'create', '--path', '/users/other',
                            '--path', '/people/other',
                            '--target-user-location',
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
    os.mkdir(base_dir / 'other-catalog')
    # add container to manifests catalog
    with open(base_dir / 'users/Other.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['manifests-catalog'].append({
            'paths': ['/.uuid/1111-2222-3333-4444'],
            'owner': '0xbbb',
            'object': 'container',
            'version': Manifest.CURRENT_VERSION,
            'backends': {'storage': [{
                'type': 'local',
                'location': str(base_dir / 'other-catalog'),
                'manifest-pattern': {
                    'type': 'glob',
                    'path': '/*.yaml',
                }
            }]}
        })
        f.seek(0)
        f.write('signature: |\n  dummy.0xbbb\n---\n')
        f.write(yaml.safe_dump(documents[1]))
    cli('container', 'create', 'Container', '--owner', 'Other', '--path', '/PATH', '--no-publish')
    cli('storage', 'create', 'local', 'Storage', '--location', '/PATH',
        '--container', 'Container')

    # move user manifest out of the default path, so the bridge would be the only way to access it
    os.rename(base_dir / 'users/Other.user.yaml', base_dir / 'user-Other.user.yaml')
    # same for the container manifest
    os.rename(base_dir / 'containers/Container.container.yaml',
              base_dir / 'other-catalog/Container.container.yaml')
    cli('bridge', 'create', '--path', '/users/other',
                            '--path', '/people/other',
                            '--target-user-location',
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


def test_container_mount_bridge_placeholder(cli, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'create', 'Other', '--key', '0xbbb')
    os.mkdir(base_dir / 'user-catalog')
    # add container to manifests catalog
    with open(base_dir / 'users/User.user.yaml', 'r+') as f:
        documents = list(yaml.safe_load_all(f))
        documents[1]['manifests-catalog'].append({
            'paths': ['/.uuid/1111-2222-3333-4444'],
            'owner': '0xaaa',
            'object': 'container',
            'version': Manifest.CURRENT_VERSION,
            'backends': {'storage': [{
                'type': 'local',
                'location': str(base_dir / 'user-catalog'),
                'manifest-pattern': {
                    'type': 'glob',
                    'path': '/*.yaml',
                }
            }]}
        })
        f.seek(0)
        f.write('signature: |\n  dummy.0xaaa\n---\n')
        f.write(yaml.safe_dump(documents[1]))

    # move user manifest out of the default path, so the bridge would be the only way to access it
    os.rename(base_dir / 'users/Other.user.yaml', base_dir / 'user-Other.user.yaml')
    cli('bridge', 'create', '--path', '/users/other',
                            '--path', '/people/other',
                            '--target-user-location',
                            'file://%s' % (base_dir / 'user-Other.user.yaml'),
                            'br-other')
    # "publish" the bridge
    os.rename(base_dir / 'bridges/br-other.bridge.yaml',
              base_dir / 'user-catalog/br-other.bridge.yaml')
    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--no-import-users', 'wildland::*:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert '/.users/0xbbb:' in command[0]['paths']
    assert '/users/other:' in command[0]['paths']
    assert '/people/other:' in command[0]['paths']

    control_client.calls = {}

    # mounting bridge specifically should work too
    cli('container', 'mount', '--no-import-users', 'wildland::/users/other:')

    command = control_client.calls['mount']['items']
    assert command[0]['storage']['owner'] == '0xbbb'
    assert command[0]['storage']['type'] == 'static'
    assert '/.users/0xbbb:' in command[0]['paths']


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

    assert len(command) == 4
    paths_backend1 = [
        f'/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid1}',
        '/.users/0xaaa:/PATH1',
        f'/.uuid/{uuid1}',
        '/PATH1'
    ]
    assert sorted(command[0]['paths']) == paths_backend1

    paths_backend2 = [
        f'/.backends/{uuid2}/{backend_id2}',
        f'/.users/0xaaa:/.backends/{uuid2}/{backend_id2}',
        f'/.users/0xaaa:/.uuid/{uuid2}',
        '/.users/0xaaa:/PATH2',
        f'/.uuid/{uuid2}',
        '/PATH2'
    ]
    assert sorted(command[1]['paths']) == paths_backend2

    assert sorted(command[2]['paths']) == \
        paths_backend1[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid1}/{backend_id1}-pseudomanifest'] + \
        paths_backend1[2:]

    assert sorted(command[3]['paths']) == \
        paths_backend2[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid2}/{backend_id2}-pseudomanifest'] + \
        paths_backend2[2:]


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

    manifest_path = base_dir / 'wildland/trusted/Container.container.yaml'

    # Write an unsigned container manifest to wildland/trusted/

    content = (base_dir / 'containers/Container.container.yaml').read_text()
    content = content[content.index('---'):]
    os.mkdir(base_dir / 'wildland/trusted')
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

    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container', '--subcontainer-manifest', '/subcontainer.yaml')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))

    uuid_path1 = documents[1]['paths'][0]
    uuid1 = get_container_uuid_from_uuid_path(uuid_path1)
    backend_id1 = documents[1]['backends']['storage'][0]['backend-id']

    with open(tmp_path / 'subcontainer.yaml', 'w') as f:
        f.write(f"""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - /.uuid/{uuid2}
 - /subcontainer
object: container
backends:
  storage:
    - type: delegate
      backend-id: {backend_id}
      reference-container: 'wildland:@default:/.uuid/{uuid1}:'
      subdirectory: '/subdir'
    """)

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--with-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 4
    assert command[0]['storage']['owner'] == '0xaaa'
    paths_backend1 = [
        f'/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.backends/{uuid1}/{backend_id1}',
        f'/.users/0xaaa:/.uuid/{uuid1}',
        '/.users/0xaaa:/PATH',
        f'/.uuid/{uuid1}',
        '/PATH',
    ]
    assert sorted(command[0]['paths']) == paths_backend1

    assert command[1]['storage']['owner'] == '0xaaa'
    assert command[1]['storage']['type'] == 'delegate'
    assert command[1]['storage']['container-path'] == f'/.uuid/{uuid2}'
    assert command[1]['storage']['reference-container'] == f'wildland:@default:/.uuid/{uuid1}:'
    assert command[1]['storage']['subdirectory'] == '/subdir'
    assert command[1]['storage']['storage'] == command[0]['storage']

    paths_backend2 = [
        f'/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid2}',
        '/.users/0xaaa:/subcontainer',
        f'/.uuid/{uuid2}',
        '/subcontainer',
    ]
    assert sorted(command[1]['paths']) == paths_backend2

    assert sorted(command[2]['paths']) == \
        paths_backend1[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid1}/{backend_id1}-pseudomanifest'] + \
        paths_backend1[2:]

    assert command[2]['storage']['owner'] == '0xaaa'
    assert command[2]['storage']['type'] == 'static'

    assert sorted(command[3]['paths']) == \
        paths_backend2[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid2}/{backend_id}-pseudomanifest'] + \
        paths_backend2[2:]

    assert command[3]['storage']['owner'] == '0xaaa'
    assert command[3]['storage']['type'] == 'static'


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
object: container
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
        cli('container', 'mount', tmp_path / 'container-*.yaml', capture=True)

    # the other container should still be mounted
    command = control_client.calls['mount']['items']
    assert len(command) == 2

    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['storage']['type'] == 'delegate'

    assert command[1]['storage']['owner'] == '0xaaa'
    assert command[1]['storage']['type'] == 'static'

    assert command[0]['paths'] == [
        '/.users/0xaaa:/.backends/0000-1111-2222-3333-4444/0000-1111-2222-3333-4444',
        '/.backends/0000-1111-2222-3333-4444/0000-1111-2222-3333-4444',
        '/.users/0xaaa:/.uuid/0000-1111-2222-3333-4444',
        '/.uuid/0000-1111-2222-3333-4444',
        '/.users/0xaaa:/container-99',
        '/container-99'
    ]
    assert command[1]['paths'] == [
        '/.users/0xaaa:/.backends/0000-1111-2222-3333-4444/0000-1111-2222-3333-4444-pseudomanifest',
        '/.backends/0000-1111-2222-3333-4444/0000-1111-2222-3333-4444',
        '/.users/0xaaa:/.uuid/0000-1111-2222-3333-4444',
        '/.uuid/0000-1111-2222-3333-4444',
        '/.users/0xaaa:/container-99',
        '/container-99'
    ]


def test_container_mount_only_subcontainers(cli, base_dir, control_client, tmp_path):
    control_client.expect('status', {})

    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    uuid2 = '0000-1111-2222-3333-4444'
    backend_id = '5555-6666-7777-8888-9999'

    with open(base_dir / 'containers/Container.container.yaml') as f:
        container_data = f.read().split('\n', 4)[-1]
        uuid1 = re.search(r'/.uuid/(.+?)\\n', container_data).group(1)

    with open(tmp_path / 'subcontainer.yaml', 'w') as f:
        f.write(f"""signature: |
  dummy.0xaaa
---
owner: '0xaaa'
paths:
 - /.uuid/{uuid2}
 - /subcontainer
object: container
backends:
  storage:
    - type: delegate
      backend-id: {backend_id}
      reference-container: 'wildland:@default:/.uuid/{uuid1}:'
      subdirectory: '/subdir'
""")
    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container', '--subcontainer-manifest', '/subcontainer.yaml')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--only-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 2
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['storage']['type'] == 'delegate'
    assert command[0]['storage']['container-path'] == f'/.uuid/{uuid2}'
    assert command[0]['storage']['reference-container'] == f'wildland:@default:/.uuid/{uuid1}:'
    assert command[0]['storage']['subdirectory'] == '/subdir'
    assert command[0]['storage']['storage']['type'] == 'local'
    assert command[0]['storage']['storage']['location'] == os.fspath(tmp_path)
    backend_paths = [
        f'/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid2}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid2}',
        '/.users/0xaaa:/subcontainer',
        f'/.uuid/{uuid2}',
        '/subcontainer',
    ]
    assert sorted(command[0]['paths']) == backend_paths

    assert command[1]['storage']['owner'] == '0xaaa'
    assert command[1]['storage']['type'] == 'static'
    assert sorted(command[1]['paths']) == \
        backend_paths[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid2}/{backend_id}-pseudomanifest'] + \
        backend_paths[2:]


def test_container_mount_local_subcontainers_trusted(cli, control_client, tmp_path, base_dir):
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
object: container
backends:
  storage:
    - type: delegate
      backend-id: {backend_id}
      reference-container: 'file://{base_dir / 'containers/Container.container.yaml'}'
      subdirectory: '/subdir'
""")
    cli('storage', 'create', 'local', 'Storage', '--location', os.fspath(tmp_path),
        '--container', 'Container', '--trusted', '--subcontainer-manifest', '/subcontainer.yaml')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('container', 'mount', '--only-subcontainers', 'Container')

    command = control_client.calls['mount']['items']
    assert len(command) == 2
    assert command[0]['storage']['owner'] == '0xaaa'
    assert command[0]['storage']['type'] == 'delegate'
    backend_paths = [
        f'/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
        f'/.users/0xaaa:/.uuid/{uuid}',
        '/.users/0xaaa:/subcontainer',
        f'/.uuid/{uuid}',
        '/subcontainer',
    ]
    assert sorted(command[0]['paths']) == backend_paths

    assert command[1]['storage']['owner'] == '0xaaa'
    assert command[1]['storage']['type'] == 'static'

    assert sorted(command[1]['paths']) == \
        backend_paths[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid}/{backend_id}-pseudomanifest'] + \
        backend_paths[2:]


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

    control_client.expect('info', {
        '101': {
            'paths': ['/PATH'],
            'type': 'local',
            'extra': {},
        },
        '102': {
            'paths': ['/PATH2'],
            'type': 'local',
            'extra': {},
        },
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
        '--target-user', 'RefUser',
        '--target-user-location', 'https://example.com/RefUser.yaml',
        '--path', '/ModifiedPath')

    data = (base_dir / 'bridges/Bridge.bridge.yaml').read_text()
    assert 'user: https://example.com/RefUser.yaml' in data
    assert 'pubkey: key.0xbbb' in data
    assert '- /ModifiedPath' in data
    assert '- /OriginalPath' not in data

    cli('user', 'create', 'ThirdUser', '--key', '0xccc', '--path', '/Third')
    cli('bridge', 'create',
        '--target-user', 'ThirdUser')

    data = (base_dir / 'bridges/Third.bridge.yaml').read_text()
    assert f'file://localhost{base_dir / "users/ThirdUser.user.yaml"}' in data
    assert 'pubkey: key.0xccc' in data
    assert '- /Third' in data


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
    cli('template', 'create', 'local', '--location', '/foo', 't1')

    with open(base_dir / 'templates/t1.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == [{
            'type': 'local',
            'location': '/foo{{ local_dir if local_dir is defined else "/" }}/{{ uuid }}',
            'read-only': False
        }]


def test_cli_storage_template_create_custom_access(cli, base_dir):
    cli('user', 'create', 'UserA', '--key', '0xaaa')
    cli('user', 'create', 'UserB', '--key', '0xbbb')
    cli('template', 'create', 'local', '--location', '/foo',
        '--access', 'UserA', '--access', 'UserB', 't1')

    with open(base_dir / 'templates/t1.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == [{
            'type': 'local',
            'location': '/foo{{ local_dir if local_dir is defined else "/" }}/{{ uuid }}',
            'read-only': False,
            'access': [{'user': '0xaaa'}, {'user': '0xbbb'}]
        }]

    cli('template', 'create', 'local', '--location', '/foo',
        '--access', '*', 't2')

    with open(base_dir / 'templates/t2.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == [{
            'type': 'local',
            'location': '/foo{{ local_dir if local_dir is defined else "/" }}/{{ uuid }}',
            'read-only': False,
            'access': [{'user': '*'}]
        }]

    with pytest.raises(CliError, match='Failed to create storage template: user not found: *'):
        cli('template', 'create', 'local', '--location', '/foo',
            '--access', '*', '--access', 'UserA', 't3')


def test_cli_remove_storage_template(cli, base_dir):
    cli('template', 'create', 'local', '--location', '/foo', 't1')

    assert Path(base_dir / 'templates/t1.template.jinja').exists()

    cli('template', 'remove', 't1')

    assert not Path(base_dir / 'templates/t1.template.jinja').exists()


def test_cli_remove_nonexisting_storage_template(cli):
    with pytest.raises(CliError, match='does not exist'):
        cli('template', 'remove', 't1')


def test_appending_to_existing_storage_template(cli, base_dir):
    cli('template', 'create', 'local', '--location', '/foo', 't1')
    cli('template', 'add', 'local', '--location', '/bar', '--read-only', 't1')

    with open(base_dir / 'templates/t1.template.jinja', 'r') as f:
        read_data = load_yaml(f)
        assert read_data == [{
            'type': 'local',
            'location': '/foo{{ local_dir if local_dir is defined else "/" }}/{{ uuid }}',
            'read-only': False
        }, {
            'type': 'local',
            'location': '/bar{{ local_dir if local_dir is defined else "/" }}/{{ uuid }}',
            'read-only': True
        }]


def test_create_existing_template(cli):
    cli('template', 'create', 'local', '--location', '/foo', 't1')

    with pytest.raises(CliError, match='already exists'):
        cli('template', 'create', 'local', '--location', '/bar', 't1')


def test_append_non_existing_template(cli):
    with pytest.raises(CliError, match='does not exist'):
        cli('template', 'add', 'local', '--location', '/foo', 't1')


def test_template_parsing(cli, base_dir):
    cli('user', 'create', 'User')
    cli('template', 'create', 'webdav',
        '--url', 'https://acme.com{{ paths|first }}/{{ title }}',
        '--login', '{{ categories | first }}',
        '--password', '{{ categories | last }}',
        't1')
    cli('container', 'create', 'Container', '--path', '/PATH',
        '--template', 't1', '--no-encrypt-manifest',
        '--title', 'foobar', '--category', '/boo!foo:hoo', '--category', '/żółć',
        '--local-dir', '/a_local_dir')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(load_yaml_all(f))
        uuid_path = documents[1]['paths'][0]

    just_uuid = uuid_path.replace('/.uuid/', '')

    data = (base_dir / 'containers/Container.container.yaml').read_text()

    assert f'url: https://acme.com{uuid_path}/foobar/a_local_dir/{just_uuid}' in data
    assert 'login: /boo!foo:hoo' in data
    assert 'password: "/\\u017C\\xF3\\u0142\\u0107"' in data


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

    assert 'Bob' in os.listdir(base_dir / 'wildland')
    assert 'Alice' not in os.listdir(base_dir / 'wildland')


def _create_user_manifest(owner: str, path: str = '/PATH',
                          catalog_path: str = None) -> bytes:
    if catalog_path:
        catalog_entry = f'''
- object: container
  owner: '{owner}'
  paths:
  - /manifests
  version: '1'
  backends:
    storage:
    - owner: '{owner}'
      container-path: /manifests
      type: local
      location: {catalog_path}
      manifest-pattern:
        type: glob
        path: /{{path}}.yaml
'''

    else:
        catalog_entry = '[]'
    data = f'''signature: |
  dummy.{owner}
---
object: user
owner: '{owner}'
paths:
- {path}
manifests-catalog: {catalog_entry}
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
    assert re.match(r'[\S\s]+paths:\n- /forests/0xbbb-PATH[\S\s]+', bridge_data)

    destination.write(_create_user_manifest('0xccc'))
    cli('user', 'import', '--path', '/IMPORT', '--path', '/FOO', str(destination))

    assert (base_dir / 'users/Bob.1.user.yaml').read_bytes() == _create_user_manifest('0xccc')

    bridge_data = (base_dir / 'bridges/Bob.1.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xaaa\'' in bridge_data
    assert f'user: file://localhost{destination}' in bridge_data
    assert 'pubkey: key.0xccc' in bridge_data
    assert re.match(r'[\S\s]+paths:\n- /IMPORT[\S\s]+', bridge_data)

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
    assert re.match(r'[\S\s]+paths:\n- /forests/0xbbb-IMPORT[\S\s]+', bridge_data)


def test_import_bridge_with_object_location(cli, base_dir, tmpdir):
    test_user_data = _create_user_manifest('0xbbb')
    user_destination = tmpdir / 'Bob.user.yaml'
    user_destination.write(test_user_data)

    test_bridge_data = _create_bridge_manifest(
        '0xbbb', f'''
  object: link
  file: /Bob.user.yaml
  storage:
    backend-id: 111-222-333
    type: local
    location: {tmpdir}
''', '0xbbb')

    bridge_destination = tmpdir / 'BobBridge.bridge.yaml'
    bridge_destination.write(test_bridge_data)

    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')
    cli('user', 'import', str(bridge_destination))

    assert (base_dir / 'users/Bob.user.yaml').read_bytes() == test_user_data

    bridge_data = (base_dir / 'bridges/BobBridge.bridge.yaml').read_text()

    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xaaa\'' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert re.match(r'[\S\s]+paths:\n- /forests/0xbbb-IMPORT[\S\s]+', bridge_data)


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
    assert re.match(r'[\S\s]+paths:\n- /forests/0xbbb-PATH[\S\s]+', bridge_data)


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
        '--target-user-location', f'file://localhost{alice_manifest_location}', 'Alice')

    modify_file(base_dir / 'config.yaml', "local-owners:\n- '0xddd'",
                "local-owners:\n- '0xddd'\n- '0xaaa'")

    cli('-vvvvv', 'bridge', 'import', 'wildland:0xddd:/ALICE:/IMPORT:')

    bridge_data = (base_dir / 'bridges/0xddd__ALICE__IMPORT_.bridge.yaml').read_text()
    assert 'object: bridge' in bridge_data
    assert 'owner: \'0xddd\'' in bridge_data
    assert f'file://localhost{bob_manifest_location}' in bridge_data
    assert 'pubkey: key.0xbbb' in bridge_data
    assert re.match(r'[\S\s]+paths:\n- /forests/0xaaa-IMPORT[\S\s]+', bridge_data)

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
    assert re.match(r'[\S\s]+paths:\n- /forests/0xbbb-PATH[\S\s]+', bridge_data)


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
        '--subcontainer-manifest', '/Child.container.yaml',
        '--subcontainer-manifest', '/MaliciousChild.container.yaml')
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
    assert len(command) == 4
    assert sorted(command[0]['paths']) == parent_paths
    assert sorted(command[1]['paths']) == child_paths

    assert command[2]['storage']['type'] == 'static'
    assert command[2]['extra']['hidden'] is True

    pseudomanifest_parent_paths = \
        parent_paths[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid_parent}/{backend_id_parent}-pseudomanifest'] + \
        parent_paths[2:]
    assert sorted(command[2]['paths']) == pseudomanifest_parent_paths

    assert command[3]['storage']['type'] == 'static'
    assert command[3]['extra']['hidden'] is True

    pseudomanifest_child_paths = \
        child_paths[:1] + \
        [f'/.users/0xaaa:/.backends/{uuid_child}/{backend_id_child}-pseudomanifest'] + \
        child_paths[2:]
    assert sorted(command[3]['paths']) == pseudomanifest_child_paths

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
    assert len(command) == 2
    assert sorted(command[0]['paths']) == child_paths
    assert sorted(command[1]['paths']) == pseudomanifest_child_paths


def test_user_refresh(cli, base_dir, tmpdir):
    cli('user', 'create', 'DefaultUser', '--key', '0xaaa')

    # Import Alice user with path /FOO
    test_data = _create_user_manifest('0xbbb', path='/FOO')
    destination = tmpdir / 'Alice.user.yaml'
    destination.write(test_data)

    # TODO: this is a very ugly way of putting a link obj into a bridge,
    # it should be replaced by native link object support for wl u import
    cli('user', 'import', str(destination))
    bridge_destination = base_dir / 'bridges/Alice.bridge.yaml'

    link_data = f'''
  storage:
    type: local
    location: {str(tmpdir)}
  object: link
  file: /Alice.user.yaml'''
    bridge_text = bridge_destination.read_text()
    bridge_text = bridge_text.replace('file://localhost' + str(destination), link_data)
    bridge_destination.write_text(bridge_text)

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

    result = cli('container', 'find', f'{base_dir}/wildland/PATH/file.txt', capture=True)

    assert result.splitlines() == [
        f'Container: wildland:0xaaa:{uuid_path}:',
        f'  Backend id: {backend_id}',
    ]

    control_client.expect('fileinfo', {})

    with pytest.raises(CliError, match='Given path was not found in any storage'):
        cli('container', 'find', f'{base_dir}/wildland/PATH/not_existing.txt', capture=True)


# Forest


def test_forest_create(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location', f'/{tmp_path}/wl-forest',
        '--manifest-pattern', '/{path}.yaml', 'forest-tpl')
    cli('template', 'add', 'local', '--location', f'/{tmp_path}/wl-forest',
        '--read-only', '--manifest-pattern', '/{path}.yaml', 'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    assert catalog_path.exists()

    catalog_dirs = list(catalog_path.glob('*'))

    assert len(catalog_dirs) == 1

    uuid_dir = str(catalog_dirs[0])

    assert Path(f'{uuid_dir}/forest-owner.yaml').exists()
    assert Path(f'{uuid_dir}/.manifests.yaml').exists()


def test_forest_bridge_to(cli, tmp_path, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('user', 'create', 'Bob', '--key', '0xbbb')
    cli('template', 'create', 'local', '--location', f'/{tmp_path}/wl-forest',
        '--manifest-pattern', '/{path}.yaml', 'forest-tpl')
    cli('forest', 'create', '--access', '*', 'Bob', 'forest-tpl')

    cli('bridge', 'create', 'Bridge', '--target-user', 'Bob', '--path', '/Bridge/To/Bob')

    bridge_data = (base_dir / 'bridges/Bridge.bridge.yaml').read_text()
    assert '/Bridge/To/Bob' in bridge_data
    assert 'object: link' in bridge_data
    assert 'forest-owner.yaml' in bridge_data


def _setup_forest_and_mount(cli, tmp_path, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location',
        f'/{tmp_path}/wl-forest', '--manifest-pattern', '/{path}.yaml', 'rw')
    cli('container', 'create', '--owner', 'Alice', 'mycapsule', '--title',
        'my_awesome_capsule', "--category", "/testing", "--template",
        "rw", '--no-encrypt-manifest')
    cli('bridge', 'create', '--owner', 'Alice', '--target-user', 'Alice',
        '--target-user-location', f'file:///{base_dir}/users/Alice.user.yaml',
        '--path', '/forests/Alice', 'self_bridge')
    cli('forest', 'create', '--access', '*', 'Alice', 'rw')
    cli('container', 'publish', 'mycapsule')

    control_client.expect('paths', {})
    control_client.expect('mount')

    cli('forest', 'mount', ':/forests/Alice:')
    command = control_client.calls['mount']['items']

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    catalog_dirs = list(catalog_path.glob('*'))
    catalog_uuid_dir = str(catalog_dirs[0])

    with open(f'{catalog_uuid_dir}/.manifests.yaml') as f:
        documents = list(load_yaml_all(f))
    entry_uuid_path = documents[1]['paths'][0]
    entry_uuid = get_container_uuid_from_uuid_path(entry_uuid_path)
    entry_backend_id = documents[1]['backends']['storage'][0]['backend-id']

    with open(base_dir / 'containers/mycapsule.container.yaml') as f:
        documents = list(load_yaml_all(f))
    uuid_path = documents[1]['paths'][0]
    uuid = get_container_uuid_from_uuid_path(uuid_path)
    backend_id = documents[1]['backends']['storage'][0]['backend-id']

    all_paths = command[0]['paths'] + command[1]['paths']
    expected_paths = {f'/.users/0xaaa:/.backends/{uuid}/{backend_id}',
                      f'/.users/0xaaa:/.backends/{entry_uuid}/{entry_backend_id}',
                      '/.users/0xaaa:/.manifests',
                      f'/.users/0xaaa:/.uuid/{uuid}',
                      f'/.users/0xaaa:/.uuid/{entry_uuid}',
                      '/.users/0xaaa:/testing/my_awesome_capsule'}
    assert expected_paths == set(all_paths)
    info = {
        "entry_uuid": entry_uuid,
        "entry_backend_id": entry_backend_id,
        "uuid": uuid,
        "backend_id": backend_id,
        "catalog_path": ".manifests",
        "path": "testing/my_awesome_capsule"
    }
    return info


def test_forest_mount(cli, tmp_path, base_dir, control_client):
    _setup_forest_and_mount(cli, tmp_path, base_dir, control_client)


def test_forest_mount_warning(monkeypatch, cli, tmp_path, base_dir, control_client):
    control_client.expect('status', {})

    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location',
        f'/{tmp_path}/wl-forest', '--manifest-pattern', '/{path}.yaml', 'rw')
    cli('container', 'create', '--owner', 'Alice', 'mycapsule', '--title',
        'my_awesome_capsule', "--category", "/testing", "--template",
        "rw", '--no-encrypt-manifest')
    cli('bridge', 'create', '--owner', 'Alice', '--target-user', 'Alice',
        '--target-user-location', f'file:///{base_dir}/users/Alice.user.yaml',
        '--path', '/forests/Alice', 'self_bridge')

    cli('container', 'create', 'unpublished')

    cli('forest', 'create', '--access', '*', 'Alice', 'rw')
    cli('container', 'publish', 'mycapsule')

    control_client.expect('paths', {})
    control_client.expect('mount')

    output = []
    monkeypatch.setattr('click.echo', output.append)
    cli('forest', 'mount', ':/forests/Alice:')
    assert any((o.startswith("WARN: Some local containers (or container updates) "
                             "are not published:") for o in output))


def test_forest_unmount(cli, tmp_path, base_dir, control_client):
    info = _setup_forest_and_mount(cli, tmp_path, base_dir, control_client)
    control_client.expect('paths', {
                f'/.users/0xaaa:/.backends/{info["uuid"]}/{info["backend_id"]}': [101],
                f'/.users/0xaaa:/.uuid/{info["uuid"]}': [102],
                f'/.users/0xaaa:/{info["path"]}': [103],
                f'/.users/0xaaa:/.backends/{info["entry_uuid"]}/{info["entry_backend_id"]}': [104],
                f'/.users/0xaaa:/.uuid/{info["entry_uuid"]}': [105],
                f'/.users/0xaaa:/{info["catalog_path"]}': [106]
            })
    control_client.expect('info', {
        '1': {
            'paths': [
                f'/.users/0xaaa:/.backends/{info["uuid"]}/{info["backend_id"]}',
                f'/.users/0xaaa:/.uuid/{info["uuid"]}',
                f'/.users/0xaaa:/{info["path"]}'
            ],
            'type': 'local',
            'extra': {},
        },
        '2': {
            'paths': [
                f'/.users/0xaaa:/.backends/{info["entry_uuid"]}/{info["entry_backend_id"]}',
                f'/.users/0xaaa:/.uuid/{info["entry_uuid"]}',
                f'/.users/0xaaa:/{info["catalog_path"]}'
            ],
            'type': 'local',
            'extra': {},
        },
    })
    control_client.expect('unmount')
    cli('forest', 'unmount', ':/forests/Alice:')


def test_forest_create_check_for_published_catalog(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location', f'/{tmp_path}/wl-forest',
        'forest-tpl')
    cli('template', 'add', 'local', '--location', f'/{tmp_path}/wl-forest',
        '--read-only', 'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    catalog_dirs = list(catalog_path.glob('*'))

    uuid_dir = catalog_dirs[0]
    assert Path(f'{uuid_dir}/.manifests.yaml').exists()

    with open(uuid_dir / '.manifests.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    published_path = uuid_dir / (Path(data["paths"][0]).name + '.yaml')

    assert published_path.exists()

    with open(str(published_path)) as f:
        data2 = list(yaml.safe_load_all(f))[1]

    assert data == data2


def test_forest_user_catalog_objects(cli, tmp_path, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        'forest-tpl')
    cli('template', 'add', 'local', '--location', f'{tmp_path}/wl-forest',
        '--public-url', f'file://{tmp_path}/wl-forest', 'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    assert catalog_path.exists()

    catalog_dirs = list(catalog_path.glob('*'))

    assert len(catalog_dirs) == 1

    uuid_dir = str(catalog_dirs[0].resolve())

    with open(base_dir / 'users/Alice.user.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    catalog = data['manifests-catalog']

    assert len(catalog) == 2

    # Without public-url thus storage template type (local)
    assert catalog[0]['object'] == 'link'
    assert catalog[0]['storage']['type'] == 'local'
    assert catalog[0]['storage']['location'] == f'{uuid_dir}'

    assert catalog[1]['object'] == 'link'
    assert catalog[1]['storage']['type'] == 'http'
    assert catalog[1]['storage']['url'] == f'file://{uuid_dir}'

def test_forest_encrypted_catalog_objects(cli, tmp_path, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        'forest-tpl')
    cli('template', 'add', 'local', '--location', f'{tmp_path}/wl-forest',
        '--public-url', f'file://{tmp_path}/wl-forest', 'forest-tpl')

    cli('forest', 'create', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    assert catalog_path.exists()

    catalog_dirs = list(catalog_path.glob('*'))

    assert len(catalog_dirs) == 1

    uuid_dir = str(catalog_dirs[0].resolve())

    with open(base_dir / 'users/Alice.user.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    catalog = data['manifests-catalog']

    assert len(catalog) == 2

    # Without public-url thus storage template type (local)
    assert catalog[0]['object'] == 'link'
    assert 'type: local' in catalog[0]['storage']['encrypted']['encrypted-data']
    assert f'location: {uuid_dir}' in catalog[0]['storage']['encrypted']['encrypted-data']

    assert 'type: http' in catalog[1]['storage']['encrypted']['encrypted-data']
    assert f'url: file://{uuid_dir}' in catalog[1]['storage']['encrypted']['encrypted-data']


def test_forest_user_ensure_manifest_pattern_tc_1(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')

    # Both storages are writable, first one will take default manifest pattern
    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        'forest-tpl')
    cli('template', 'add', 'local', '--location', f'{tmp_path}/wl-forest',
        '--manifest-pattern', '/foo.yaml', 'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    uuid_dir = list(catalog_path.glob('*'))[0].resolve()

    with open(uuid_dir / '.manifests.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    storage = data['backends']['storage']
    assert storage[0]['manifest-pattern'] == FileSubcontainersMixin.DEFAULT_MANIFEST_PATTERN
    assert storage[1]['manifest-pattern'] == FileSubcontainersMixin.DEFAULT_MANIFEST_PATTERN


def test_forest_user_ensure_manifest_pattern_tc_2(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')

    # First storage is not read-only, the second storage takes precedence with its custom template
    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        '--read-only', 'forest-tpl')
    cli('template', 'add', 'local', '--location', f'{tmp_path}/wl-forest',
        '--manifest-pattern', '/foo.yaml', 'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    uuid_dir = list(catalog_path.glob('*'))[0].resolve()

    with open(uuid_dir / '.manifests.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    storage = data['backends']['storage']
    assert storage[0]['manifest-pattern'] == {'type': 'glob', 'path': '/foo.yaml'}
    assert storage[1]['manifest-pattern'] == {'type': 'glob', 'path': '/foo.yaml'}


def test_forest_user_ensure_manifest_pattern_tc_3(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')

    # First storage is not read-only and it has manifest pattern,
    # the second storage takes precedence with the default manifest pattern
    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        '--manifest-pattern', '/foo.yaml', '--read-only', 'forest-tpl')
    cli('template', 'add', 'local', '--location', f'{tmp_path}/wl-forest',
        'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    uuid_dir = list(catalog_path.glob('*'))[0].resolve()

    with open(uuid_dir / '.manifests.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    storage = data['backends']['storage']
    assert storage[0]['manifest-pattern'] == FileSubcontainersMixin.DEFAULT_MANIFEST_PATTERN
    assert storage[1]['manifest-pattern'] == FileSubcontainersMixin.DEFAULT_MANIFEST_PATTERN


def test_forest_user_ensure_manifest_pattern_non_inline_storage_template(cli, tmp_path):
    cli('user', 'create', 'Alice', '--key', '0xaaa')

    # First storage is not read-only and it has manifest pattern,
    # the second storage takes precedence with the default manifest pattern
    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        '--manifest-pattern', '/foo.yaml', '--read-only', 'forest-tpl')
    cli('template', 'add', 'local', '--location', f'{tmp_path}/wl-forest',
        'forest-tpl')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-tpl')

    catalog_path = Path(f'/{tmp_path}/wl-forest/.manifests/')
    uuid_dir = list(catalog_path.glob('*'))[0].resolve()

    with open(uuid_dir / '.manifests.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    storage = data['backends']['storage']
    assert storage[0]['manifest-pattern'] == FileSubcontainersMixin.DEFAULT_MANIFEST_PATTERN
    assert storage[1]['manifest-pattern'] == FileSubcontainersMixin.DEFAULT_MANIFEST_PATTERN


def test_import_forest_user_with_bridge_link_object(cli, tmp_path, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')

    cli('template', 'create', 'local', '--location', f'{tmp_path}/wl-forest',
        'forest-template')

    cli('forest', 'create', '--access', '*', 'Alice', 'forest-template')

    shutil.copy(Path(f'{base_dir}/users/Alice.user.yaml'), Path(f'{tmp_path}/Alice.yaml'))

    cli('user', 'del', 'Alice', '--cascade')
    cli('user', 'create', 'Bob', '--key', '0xbbb')

    modify_file(base_dir / 'config.yaml', "local-owners:\n- '0xbbb'",
                "local-owners:\n- '0xbbb'\n- '0xaaa'")

    cli('user', 'import', f'{tmp_path}/Alice.yaml')

    with open(base_dir / 'bridges/Alice.bridge.yaml') as f:
        data = list(yaml.safe_load_all(f))[1]

    assert data['user']['object'] == 'link'
    assert data['user']['file'] == '/forest-owner.yaml'
    assert data['user']['storage']['type'] == 'local'


## Storage params sanity test


def test_storage_dropbox_params(cli, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--no-encrypt-manifest')
    cli('storage', 'create', 'dropbox',
        '--container', 'Container',
        '--inline',
        '--subcontainer-manifest', '/sub.yaml',
        '--location', '/foo-location',
        '--token', 'foo-token')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['location'] == '/foo-location'
    assert storage['token'] == 'foo-token'
    assert storage['manifest-pattern']['type'] == 'list'
    assert storage['manifest-pattern']['paths'] == ['/sub.yaml']

    cli('container', 'create', 'Container2', '--no-encrypt-manifest')
    cli('storage', 'create', 'dropbox',
        '--container', 'Container2',
        '--inline',
        '--manifest-pattern', '/*.yaml',
        '--location', '/foo-location',
        '--token', 'foo-token')

    with open(base_dir / 'containers/Container2.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['location'] == '/foo-location'
    assert storage['token'] == 'foo-token'
    assert storage['manifest-pattern']['type'] == 'glob'
    assert storage['manifest-pattern']['path'] == '/*.yaml'


def test_storage_googledrive_params(cli, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--no-encrypt-manifest')
    cli('storage', 'create', 'googledrive',
        '--container', 'Container',
        '--inline',
        '--subcontainer-manifest', '/sub.yaml',
        '--credentials', '{"token": "foo", "refresh_token": "foo", "token_uri": "foo",'
                         '"client_id": "foo", "client_secret": "foo", "scopes": "foo"}',
        '--skip-interaction')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['credentials'] == {"token": "foo", "refresh_token": "foo", "token_uri": "foo",
                                      "client_id": "foo", "client_secret": "foo", "scopes": "foo"}
    assert storage['manifest-pattern']['type'] == 'list'
    assert storage['manifest-pattern']['paths'] == ['/sub.yaml']

    cli('container', 'create', 'Container2', '--no-encrypt-manifest')
    cli('storage', 'create', 'googledrive',
        '--container', 'Container2',
        '--inline',
        '--manifest-pattern', '/*.yaml',
        '--credentials', '{"token": "foo", "refresh_token": "foo", "token_uri": "foo",'
                         '"client_id": "foo", "client_secret": "foo", "scopes": "foo"}',
        '--skip-interaction')

    with open(base_dir / 'containers/Container2.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['credentials'] == {"token": "foo", "refresh_token": "foo", "token_uri": "foo",
                                      "client_id": "foo", "client_secret": "foo", "scopes": "foo"}
    assert storage['manifest-pattern']['type'] == 'glob'
    assert storage['manifest-pattern']['path'] == '/*.yaml'


def test_storage_webdav_params(cli, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--no-encrypt-manifest')
    cli('storage', 'create', 'webdav',
        '--container', 'Container',
        '--inline',
        '--subcontainer-manifest', '/sub.yaml',
        '--url', 'http://foo-location.com',
        '--login', 'foo-login',
        '--password', 'foo-password')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['url'] == 'http://foo-location.com'
    assert storage['credentials']['login'] == 'foo-login'
    assert storage['credentials']['password'] == 'foo-password'
    assert storage['manifest-pattern']['type'] == 'list'
    assert storage['manifest-pattern']['paths'] == ['/sub.yaml']

    cli('container', 'create', 'Container2', '--no-encrypt-manifest')
    cli('storage', 'create', 'webdav',
        '--container', 'Container2',
        '--inline',
        '--manifest-pattern', '/*.yaml',
        '--url', 'http://foo-location.com',
        '--login', 'foo-login',
        '--password', 'foo-password')

    with open(base_dir / 'containers/Container2.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['url'] == 'http://foo-location.com'
    assert storage['credentials']['login'] == 'foo-login'
    assert storage['credentials']['password'] == 'foo-password'
    assert storage['manifest-pattern']['type'] == 'glob'
    assert storage['manifest-pattern']['path'] == '/*.yaml'


def test_storage_s3_params(cli, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--no-encrypt-manifest')
    cli('storage', 'create', 's3',
        '--container', 'Container',
        '--inline',
        '--subcontainer-manifest', '/sub.yaml',
        '--s3-url', 's3://foo-location',
        '--endpoint-url', 'http://foo-location.com',
        '--access-key', 'foo-access-key',
        '--secret-key', 'foo-secret-key',
        '--with-index')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['s3_url'] == 's3://foo-location'
    assert storage['endpoint_url'] == 'http://foo-location.com'
    assert storage['credentials']['access-key'] == 'foo-access-key'
    assert storage['credentials']['secret-key'] == 'foo-secret-key'
    assert storage['with-index']
    assert storage['manifest-pattern']['type'] == 'list'
    assert storage['manifest-pattern']['paths'] == ['/sub.yaml']

    cli('container', 'create', 'Container2', '--no-encrypt-manifest')
    cli('storage', 'create', 's3',
        '--container', 'Container2',
        '--inline',
        '--manifest-pattern', '/*.yaml',
        '--s3-url', 's3://foo-location',
        '--endpoint-url', 'http://foo-location.com',
        '--access-key', 'foo-access-key',
        '--secret-key', 'foo-secret-key')

    with open(base_dir / 'containers/Container2.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['s3_url'] == 's3://foo-location'
    assert storage['endpoint_url'] == 'http://foo-location.com'
    assert storage['credentials']['access-key'] == 'foo-access-key'
    assert storage['credentials']['secret-key'] == 'foo-secret-key'
    assert not storage['with-index']
    assert storage['manifest-pattern']['type'] == 'glob'
    assert storage['manifest-pattern']['path'] == '/*.yaml'

def test_storage_http_params(cli, base_dir):
    cli('user', 'create', 'Alice', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--no-encrypt-manifest')
    cli('storage', 'create', 'http',
        '--container', 'Container',
        '--inline',
        '--subcontainer-manifest', '/sub.yaml',
        '--url', 'http://foo-location.com')

    with open(base_dir / 'containers/Container.container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
        storage = documents[1]['backends']['storage'][0]

    assert storage['url'] == 'http://foo-location.com'
    assert storage['manifest-pattern']['type'] == 'list'
    assert storage['manifest-pattern']['paths'] == ['/sub.yaml']


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
