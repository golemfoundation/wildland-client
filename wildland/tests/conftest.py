# pylint: disable=missing-docstring,redefined-outer-name

import tempfile
import shutil
from pathlib import Path
import os
from unittest import mock

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
    yield cli
    if os.path.ismount(base_dir / 'mnt'):
        cli('stop')
        (Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlfuse.sock').unlink()

# TODO examine exception
@pytest.fixture
def cli_fail(cli, capsys):
    def cli_fail(*args, capture=False):
        if capture:
            capsys.readouterr()

        with pytest.raises(Exception):
            cli(*args)

        if capture:
            out, err = capsys.readouterr()
            return out + err
        return None

    return cli_fail


class TestControlClient:
    '''
    A test version of ControlClient.

    Usage:

        # Set up:
        client = TestControlClient()
        client.expect('foo', 1)
        client.expect('bar')

        # Run (in code under test):
        client.run_command('foo')         # 1
        client.run_command('bar', baz=2)  # None

        # Examine:
        client.calls['foo']   # {}
        client.calls['bar']   # {'baz': 2}
        client.check()
    '''

    # pylint: disable=missing-docstring
    def __init__(self):
        self.calls = {}
        self.results = {}

    def connect(self, socket_path):
        pass

    def disconnect(self):
        pass

    def run_command(self, name, **kwargs):
        assert name in self.results, f'unrecognized command: {name}'
        self.calls[name] = kwargs
        return self.results[name]

    def expect(self, name, result=None):
        '''
        Add a command to a list of expected commands, with a result to be
        returned.
        '''

        self.results[name] = result

    def check(self):
        '''
        Check if all expected commands have been executed.
        '''
        unseen = set(self.results) - set(self.calls)
        assert not unseen, f'some commands have not been called: {unseen}'


@pytest.fixture
def control_client():
    '''
    Mock the ControlClient and return a mock run_command.
    '''

    control_client = TestControlClient()
    with mock.patch('wildland.fs_client.ControlClient') as mock_class:
        mock_class.return_value = control_client
        yield control_client
    control_client.check()
