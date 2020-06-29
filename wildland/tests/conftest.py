# pylint: disable=missing-docstring,redefined-outer-name

import tempfile
import shutil
from pathlib import Path
import os

import yaml
import pytest

from ..cli import cli_main

## CLI

@pytest.fixture
def base_dir():
    base_dir_s = tempfile.mkdtemp(prefix='wlcli.')
    base_dir = Path(base_dir_s)
    try:
        os.mkdir(base_dir / 'mnt')
        os.mkdir(base_dir / 'mnt/.control')
        with open(base_dir / 'config.yaml', 'w') as f:
            yaml.dump({
                'mount-dir': str(base_dir / 'mnt'),
                'dummy': True,
            }, f)
        yield base_dir
    finally:
        shutil.rmtree(base_dir)


@pytest.fixture
def cli(base_dir, capsys):
    def cli(*args, capture=False):
        cmdline = ['--base-dir', base_dir, *args]
        # Convert Path to str
        cmdline = [str(arg) for arg in cmdline]
        if capture:
            capsys.readouterr()
        try:
            cli_main.main.main(args=cmdline, prog_name='wl')
        except SystemExit as e:
            if e.code not in [None, 0]:
                if hasattr(e, '__context__'):
                    assert isinstance(e.__context__, Exception)
                    raise e.__context__
                pytest.fail(f'command failed: {args}')
        if capture:
            out, _err = capsys.readouterr()
            return out
        return None
    return cli

# TODO examine exception
@pytest.fixture
def cli_fail(cli):
    def cli_fail(*args):
        with pytest.raises(Exception):
            cli(*args)
    return cli_fail
