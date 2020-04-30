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

import json
import os
from pathlib import Path
import shutil
import tempfile

import click.testing
import pytest
import yaml

from ..cli import main as _cli_main
from ..exc import WildlandError


@pytest.fixture
def base_dir():
    base_dir = tempfile.mkdtemp(prefix='wlcli.')
    base_dir = Path(base_dir)
    try:
        os.mkdir(base_dir / 'mnt')
        os.mkdir(base_dir / 'mnt/.control')
        with open(base_dir / 'config.yaml', 'w') as f:
            yaml.dump({
                'mount_dir': str(base_dir / 'mnt')
            }, f)
        yield base_dir
    finally:
        shutil.rmtree(base_dir)


@pytest.fixture
def cli_may_fail(base_dir):
    def cli_may_fail(*args):
        cmdline = ['--dummy', '--base-dir', base_dir, *args]
        # Convert Path to str
        cmdline = [str(arg) for arg in cmdline]
        return click.testing.CliRunner().invoke(_cli_main, cmdline)
    return cli_may_fail

@pytest.fixture
def cli(cli_may_fail):
    def cli(*args):
        result = cli_may_fail(*args)
        if result.exit_code != 0:
            raise result.exception
        return result
    return cli

@pytest.fixture
def cli_fail(cli_may_fail):
    def cli_fail(*args):
        result = cli_may_fail(*args)
        assert result.exit_code != 0
        return result
    return cli_fail


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

    assert "pubkey: '0xaaa'" in data
    assert "signer: '0xaaa'" in data

    with open(base_dir / 'config.yaml') as f:
        config = f.read()
    assert "default_user: '0xaaa'" in config


def test_user_list(cli, base_dir):
    cli('user', 'create', 'User1', '--key', '0xaaa')
    cli('user', 'create', 'User2', '--key', '0xbbb')
    result = cli('user', 'list')
    assert result.output.splitlines() == [
        '0xaaa {}'.format(base_dir / 'users/User1.yaml'),
        '0xbbb {}'.format(base_dir / 'users/User2.yaml'),
    ]


def test_user_verify(cli):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('user', 'verify', 'User')


def test_user_verify_bad_sig(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.yaml', 'dummy.0xaaa', 'dummy.0xbbb')
    cli_fail('user', 'verify', 'User')


def test_user_verify_bad_fields(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    modify_file(base_dir / 'users/User.yaml', 'pubkey:', 'pk:')
    cli_fail('user', 'verify', 'User')


def test_user_sign(cli, cli_fail, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    tmp_file = base_dir / 'tmp.yaml'
    shutil.copyfile(base_dir / 'users/User.yaml', tmp_file)

    modify_file(tmp_file, 'dummy.0xaaa', 'outdated.0xaaa')
    cli_fail('user', 'verify', tmp_file)

    cli('user', 'sign', '-i', tmp_file)
    cli('user', 'verify', tmp_file)


def test_user_edit(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = r'sed -i s,\'0xaaa\',\"0xaaa\",g'
    cli('user', 'edit', 'User', '--editor', editor)
    with open(base_dir / 'users/User.yaml') as f:
        data = f.read()
    assert '"0xaaa"' in data


def test_user_edit_bad_fields(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'sed -i s,pubkey,pk,g'
    cli_fail('user', 'edit', 'User', '--editor', editor)


def test_user_edit_editor_failed(cli, cli_fail):
    cli('user', 'create', 'User', '--key', '0xaaa')
    editor = 'false'
    cli_fail('user', 'edit', 'User', '--editor', editor)


## Storage

def test_storage_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', 'PATH',
        '--container', 'Container')
    with open(base_dir / 'storage/Storage.yaml') as f:
        data = f.read()

    assert "signer: '0xaaa'" in data
    assert "path: PATH" in data


def test_storage_create_update_container(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', 'PATH',
        '--container', 'Container', '--update-container')

    with open(base_dir / 'containers/Container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.yaml'
    assert str(storage_path) in data


def test_storage_list(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', 'PATH',
        '--container', 'Container')

    result = cli('storage', 'list')
    assert result.output.splitlines() == [
        str(base_dir / 'storage/Storage.yaml'),
        '  type: local',
        '  path: PATH',
    ]


## Container


def test_container_create(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    with open(base_dir / 'containers/Container.yaml') as f:
        data = f.read()

    assert "signer: '0xaaa'" in data
    assert "/PATH" in data
    assert "/.uuid/" in data


def test_container_update(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    cli('storage', 'create', 'local', 'Storage', '--path', 'PATH',
        '--container', 'Container')
    cli('container', 'update', 'Container', '--storage', 'Storage')

    with open(base_dir / 'containers/Container.yaml') as f:
        data = f.read()

    storage_path = base_dir / 'storage/Storage.yaml'
    assert str(storage_path) in data


def test_container_list(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    result = cli('container', 'list')
    out_lines = result.output.splitlines()
    assert str(base_dir / 'containers/Container.yaml') in out_lines
    assert '  path: /PATH' in out_lines


def test_container_mount(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')
    cli('storage', 'create', 'local', 'Storage', '--path', 'PATH',
        '--container', 'Container', '--update-container')

    cli('container', 'mount', 'Container')

    # The command should write container manifest to .control/mount.
    with open(base_dir / 'mnt/.control/mount') as f:
        data = f.read()
    assert '"signer": "0xaaa"' in data
    assert "/PATH" in data


def test_container_unmount(cli, base_dir):
    cli('user', 'create', 'User', '--key', '0xaaa')
    cli('container', 'create', 'Container', '--path', '/PATH')

    with open(base_dir / 'containers/Container.yaml') as f:
        documents = list(yaml.safe_load_all(f))
    path = documents[1]['paths'][0]

    with open(base_dir / 'mnt/.control/paths', 'w') as f:
        json.dump({
            path: 101,
            '/PATH2': 102,
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
