# pylint: disable=missing-docstring,redefined-outer-name

import tempfile
import shutil
from pathlib import Path
import os

import yaml
import pytest

from ..cli import MainCommand
from ..manifest.sig import GpgSigContext


## GPG

# The following fixtures are session-scoped for performance reasons (generating
# keys takes time).

@pytest.fixture(scope='session')
def gpg_sig():
    home_dir = tempfile.mkdtemp(prefix='wlgpg.')
    try:
        with GpgSigContext(home_dir) as gpg_sig:
            yield gpg_sig
    finally:
        shutil.rmtree(home_dir)

@pytest.fixture(scope='session')
def signer(gpg_sig):
    return gpg_sig.gen_test_key(name='Test 1', passphrase='secret')


@pytest.fixture(scope='session')
def other_signer(gpg_sig):
    return gpg_sig.gen_test_key(name='Test 2', passphrase='secret')


## CLI

@pytest.fixture
def base_dir():
    base_dir = tempfile.mkdtemp(prefix='wlcli.')
    base_dir = Path(base_dir)
    try:
        os.mkdir(base_dir / 'mnt')
        os.mkdir(base_dir / 'mnt/.control')
        with open(base_dir / 'config.yaml', 'w') as f:
            yaml.dump({
                'dummy': True,
                'mount_dir': str(base_dir / 'mnt')
            }, f)
        yield base_dir
    finally:
        shutil.rmtree(base_dir)


@pytest.fixture
def cli(base_dir):
    def cli(*args):
        cmdline = ['--base-dir', base_dir] + list(args)
        # Convert Path to str
        cmdline = [str(arg) for arg in cmdline]
        MainCommand().run(cmdline)

    return cli
