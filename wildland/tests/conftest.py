# pylint: disable=missing-docstring,redefined-outer-name
import signal

import os
import shutil
import tempfile

from contextlib import suppress
from multiprocessing import Process
from pathlib import Path, PurePosixPath
from typing import List
from unittest import mock

import psutil
import pytest
import yaml

from .fuse_env import FuseEnv
from ..cli import cli_main
from ..search import Search

from ..storage_sync.daemon import SyncDaemon

## CLI


@pytest.fixture
def base_dir():
    base_dir_s = tempfile.mkdtemp(prefix='wlcli.')
    base_dir = Path(base_dir_s)
    try:
        os.mkdir(base_dir / 'wildland')
        with open(base_dir / 'config.yaml', 'w') as f:
            yaml.dump({
                'mount-dir': str(base_dir / 'wildland'),
                'dummy': True,
            }, f)
        yield base_dir
    finally:
        shutil.rmtree(base_dir)
        Search.clear_cache()


def _sync_daemon(base_dir):
    server = SyncDaemon(base_dir)
    server.main()


@pytest.fixture
def sync(base_dir):
    # this is so we can easily get coverage data from the sync daemon
    try:
        daemon = Process(target=_sync_daemon, args=(base_dir,))
        daemon.start()
    finally:
        daemon.terminate()
        daemon.join()


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

    if os.path.ismount(base_dir / 'wildland'):
        cli('stop')
        (Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlfuse.sock').unlink(missing_ok=True)

    syncs = [p for p in psutil.process_iter() if 'wildland.storage_sync.daemon' in p.cmdline()]
    for p in syncs:
        p.send_signal(signal.SIGTERM)
    if len(syncs) > 0:
        (Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlsync.sock').unlink(missing_ok=True)


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


@pytest.fixture
def env():
    env = FuseEnv()
    try:
        env.mount()
        yield env
    finally:
        env.destroy()


class TestControlClient:
    """
    A test version of ControlClient.

    Usage::

        # Set up:
        client = TestControlClient()
        client.expect('foo', 1)           # expect 1 when calling `foo`
        client.expect('bar')              # expect None when calling `bar`

        # Run (in the code under test):
        client.run_command('foo')         # returns 1 which is the expected returned value
        client.run_command('bar', baz=2)  # returns None

        # Examine:
        client.calls['foo']               # returns `{}` which is last argument of the `foo` command
        client.calls['bar']               # returns `{'baz': 2}`
        client.check()
    """

    # pylint: disable=missing-docstring
    def __init__(self):
        # arguments of the last call for each command
        self.calls = {}
        # accumulated arguments of each type of the command call
        self.all_calls = {}
        # expected return value of commands
        self.results = {}
        self.events = []

    def connect(self, socket_path):
        pass

    def disconnect(self):
        pass

    def run_command(self, name, **kwargs):
        assert name in self.results, f'unexpected command: {name}'
        self.calls[name] = kwargs
        self.all_calls.setdefault(name, []).append(kwargs)
        if isinstance(self.results[name], Exception):
            raise self.results[name]
        return self.results[name]

    def iter_events(self):
        while self.events:
            event = self.events.pop(0)
            if isinstance(event, BaseException):
                raise event
            yield event

    def expect(self, name: str, result=None) -> None:
        """
        Add a command to a list of expected commands, with a result to be returned.
        """
        self.results[name] = result

    def add_storage_paths(self, storage_id: int, paths: List[PurePosixPath]) -> None:
        """
        Add a storage to be returned by 'paths' command. AKA "mount storage".
        """
        self.results.setdefault('paths', {})
        for path in paths:
            storages = self.results['paths'].setdefault(path, [])
            # don't duplicate on remount request
            if storage_id not in storages:
                storages.append(storage_id)

        self.results.setdefault('info', {})
        if storage_id not in self.results['info']:
            self.results['info'][storage_id] = {
                'type': 'local',
                'paths': paths,
                'extra': {},
            }

    def del_storage(self, storage_id):
        """
        Remove storage from 'paths' command result. AKA "unmount storage".
        """
        if 'paths' not in self.results:
            return
        for path in list(self.results['paths']):
            with suppress(ValueError):
                self.results['paths'][path].remove(storage_id)
            if not self.results['paths'][path]:
                del self.results['paths'][path]

        with suppress(KeyError):
            del self.results['info'][storage_id]

    def queue_event(self, event):
        """
        Queue an event to be returned.
        """
        self.events.append(event)

    def check(self):
        """
        Check if all expected commands have been executed.
        """
        unseen = set(self.results) - set(self.calls)
        assert not unseen, f'some commands have not been called: {unseen}'


@pytest.fixture
def control_client():
    """
    Mock the ControlClient and return a mock run_command.
    """

    control_client = TestControlClient()
    with mock.patch('wildland.fs_client.ControlClient') as mock_class:
        mock_class.return_value = control_client
        yield control_client
    control_client.check()
