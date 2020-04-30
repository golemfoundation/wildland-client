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

import shutil
import json

import yaml
import pytest

from ..exc import WildlandError


def modify_file(path, pattern, replacement):
    with open(path) as f:
        data = f.read()
    assert pattern in data
    data = data.replace(pattern, replacement)
    with open(path, 'w') as f:
        f.write(data)


## Users

def test_user_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    with open(base_dir / 'users/User.yaml') as f:
        data = f.read()

    assert "key.0xaaa" in data
    assert "signer: '0xaaa'" in data

    with open(base_dir / 'config.yaml') as f:
        config = f.read()
    assert "default_user: '0xaaa'" in config


def test_user_list(cli, base_dir, capsys):
    cli('user', 'create', 'User1', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb')
    capsys.readouterr()

    cli('user', 'list')
    out, _err = capsys.readouterr()
    assert out.splitlines() == [
        '0xaaa {}'.format(base_dir / 'users/User1.yaml'),
        '0xbbb {}'.format(base_dir / 'users/User2.yaml'),
    ]


def test_user_verify(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'verify', 'User')


def test_user_verify_bad_sig(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.yaml', 'dummy.0xaaa', 'dummy.0xbbb')
    with pytest.raises(WildlandError, match='Unknown signer'):
        cli('user', 'verify', 'User')


def test_user_verify_bad_fields(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.yaml', 'signer:', 'extra: xxx\nsigner:')
    with pytest.raises(WildlandError, match="Additional properties are not allowed"):
        cli('user', 'verify', 'User')


def test_user_sign(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    tmp_file = base_dir / 'tmp.yaml'
    shutil.copyfile(base_dir / 'users/User.yaml', tmp_file)

    modify_file(tmp_file, 'dummy.0xaaa', 'outdated.0xaaa')
    with pytest.raises(WildlandError, match='Signature verification failed'):
        cli('user', 'verify', tmp_file)

    cli('user', 'sign', '-i', tmp_file)
    cli('user', 'verify', tmp_file)


def test_user_edit(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = r'sed -i s,\'0xaaa\',\"0xaaa\",g'
    cli('user', 'edit', 'User', '--editor', editor)
    with open(base_dir / 'users/User.yaml') as f:
        data = f.read()
    assert '"0xaaa"' in data


def test_user_edit_bad_fields(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'sed -i s,signer,Signer,g'
    with pytest.raises(WildlandError, match="signer field not found"):
        cli('user', 'edit', 'User', '--editor', editor)


def test_user_edit_editor_failed(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'false'
    with pytest.raises(WildlandError, match='Running editor failed'):
        cli('user', 'edit', 'User', '--editor', editor)


## Storage

def test_storage_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'Storage', '--type', 'local', '--path', '/PATH',
        '--container', 'Container')
    with open(base_dir / 'storage/Storage.yaml') as f:
        data = f.read()

    assert "signer: '0xaaa'" in data
    assert "path: /PATH" in data


def test_storage_create_update_container(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'Storage', '--type', 'local', '--path', '/PATH',
        '--container', 'Container', '--update-container')

    with open(base_dir / 'containers/Container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.yaml'
    assert str(storage_path) in data


def test_storage_list(cli, base_dir, capsys):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'Storage', '--type', 'local', '--path', '/PATH',
        '--container', 'Container')
    capsys.readouterr()

    cli('storage', 'list')
    out, _err = capsys.readouterr()
    assert out.splitlines() == [
        str(base_dir / 'storage/Storage.yaml'),
        '  type: local',
        '  path: /PATH',
    ]


## Container


def test_container_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    with open(base_dir / 'containers/Container.yaml') as f:
        data = f.read()

    assert "signer: '0xaaa'" in data
    assert "- /PATH" in data
    assert "- /.uuid/" in data


def test_container_update(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'Storage', '--type', 'local', '--path', '/PATH',
        '--container', 'Container')
    cli('container', 'update', 'Container', '--storage', 'Storage')

    with open(base_dir / 'containers/Container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.yaml'
    assert str(storage_path) in data


def test_container_list(cli, base_dir, capsys):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    capsys.readouterr()

    cli('container', 'list')
    out, _err = capsys.readouterr()
    out_lines = out.splitlines()
    assert str(base_dir / 'containers/Container.yaml') in out_lines
    assert '  path: /PATH' in out_lines


def test_container_mount(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'Storage', '--type', 'local', '--path', '/PATH',
        '--container', 'Container', '--update-container')

    with open(base_dir / 'containers/Container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    cli('container', 'mount', 'Container')

    # The command should write container manifest to .control/mount.
    with open(base_dir / 'mnt/.control/mount') as f:
        command = json.load(f)
    assert command['storage']['signer'] == '0xaaa'
    assert command['paths'] == [
        f'/.users/0xaaa{path}',
        f'/.users/0xaaa/PATH',
        path,
        f'/PATH',
    ]

    modify_file(base_dir / 'config.yaml', "default_user: '0xaaa'", '')

    # The command should not contain the default path.
    cli('container', 'mount', 'Container')
    with open(base_dir / 'mnt/.control/mount') as f:
        command = json.load(f)
    assert command['storage']['signer'] == '0xaaa'
    assert command['paths'] == [
        f'/.users/0xaaa{path}',
        f'/.users/0xaaa/PATH',
    ]


def test_container_unmount(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    with open(base_dir / 'containers/Container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    with open(base_dir / 'mnt/.control/paths', 'w') as f:
        json.dump({
            f'/.users/0xaaa{path}': 101,
            path: 102,
            '/PATH2': 103,
        }, f)
    cli('container', 'unmount', 'Container')

    with open(base_dir / 'mnt/.control/unmount') as f:
        data = f.read()
    assert data == '101'

def test_container_unmount_by_path(cli, base_dir):

    with open(base_dir / 'mnt/.control/paths', 'w') as f:
        json.dump({
            '/PATH': 101,
            '/PATH2': 102,
        }, f)
    cli('container', 'unmount', '--path', '/PATH2')

    with open(base_dir / 'mnt/.control/unmount') as f:
        data = f.read()
    assert data == '102'
