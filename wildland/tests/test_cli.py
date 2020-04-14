# pylint: disable=missing-docstring,redefined-outer-name

import tempfile
import shutil
from pathlib import Path
from io import StringIO
import sys

import pytest

from ..cli import MainCommand
from ..exc import WildlandError


@pytest.fixture
def base_dir():
    base_dir = tempfile.mkdtemp(prefix='wlcli.')
    try:
        yield Path(base_dir)
    finally:
        shutil.rmtree(base_dir)


@pytest.fixture
def cli(base_dir):
    def cli(*args):
        cmdline = ['--dummy', '--base-dir', base_dir] + list(args)
        # Convert Path to str
        cmdline = [str(arg) for arg in cmdline]

        out = StringIO()
        stdout = sys.stdout
        sys.stdout = out
        try:
            MainCommand().run(cmdline)
        finally:
            sys.stdout = stdout
        # print(out.getvalue())
        return out.getvalue()

    return cli


def modify_file(path, pattern, replacement):
    with open(path) as f:
        data = f.read()
    assert pattern in data
    data = data.replace(pattern, replacement)
    with open(path, 'w') as f:
        f.write(data)


def test_user_create(cli, base_dir):
    cli('user-create', '0xaaa', '--name', 'User')
    with open(base_dir / 'users/User.yaml') as f:
        data = f.read()

    assert "pubkey: '0xaaa'" in data
    assert "signer: '0xaaa'" in data


def test_user_list(cli, base_dir):
    cli('user-create', '0xaaa', '--name', 'User1')
    cli('user-create', '0xbbb', '--name', 'User2')
    out = cli('user-list')
    assert out.splitlines() == [
        '0xaaa {}'.format(base_dir / 'users/User1.yaml'),
        '0xbbb {}'.format(base_dir / 'users/User2.yaml'),
    ]


def test_user_verify(cli):
    cli('user-create', '0xaaa', '--name', 'User')
    cli('user-verify', 'User')


def test_user_verify_bad_sig(cli, base_dir):
    cli('user-create', '0xaaa', '--name', 'User')
    modify_file(base_dir / 'users/User.yaml', 'dummy.0xaaa', 'dummy.0xbbb')
    with pytest.raises(WildlandError, match='Signature verification failed'):
        cli('user-verify', 'User')


def test_user_verify_bad_fields(cli, base_dir):
    cli('user-create', '0xaaa', '--name', 'User')
    modify_file(base_dir / 'users/User.yaml', 'pubkey:', 'pk:')
    with pytest.raises(WildlandError, match="'pubkey' is a required property"):
        cli('user-verify', 'User')


def test_user_sign(cli, base_dir):
    cli('user-create', '0xaaa', '--name', 'User')
    tmp_file = base_dir / 'tmp.yaml'
    shutil.copyfile(base_dir / 'users/User.yaml', tmp_file)

    modify_file(tmp_file, 'dummy.0xaaa', 'outdated.0xaaa')
    with pytest.raises(WildlandError, match='Signature verification failed'):
        cli('user-verify', tmp_file)

    cli('user-sign', '-i', tmp_file)
    cli('user-verify', tmp_file)

def test_user_edit(cli, base_dir):
    cli('user-create', '0xaaa', '--name', 'User')
    editor = 'sed -i s,\'0xaaa\',"0xaaa",g'
    cli('user-edit', 'User', '--editor', editor)
    with open(base_dir / 'users/User.yaml') as f:
        data = f.read()
    assert '"0xaaa"' in data

def test_user_editor_bad_fields(cli):
    cli('user-create', '0xaaa', '--name', 'User')
    editor = 'sed -i s,pubkey,pk,g'
    with pytest.raises(WildlandError, match="'pubkey' is a required property"):
        cli('user-edit', 'User', '--editor', editor)


def test_user_editor_failed(cli):
    cli('user-create', '0xaaa', '--name', 'User')
    editor = 'false'
    with pytest.raises(WildlandError, match='Running editor failed'):
        cli('user-edit', 'User', '--editor', editor)