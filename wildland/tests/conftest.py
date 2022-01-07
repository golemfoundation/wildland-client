# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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

# pylint: disable=missing-docstring,redefined-outer-name
import signal

import os
import shutil
import tempfile
import time

from contextlib import suppress
from multiprocessing import Process
from pathlib import Path, PurePosixPath
from typing import List
from unittest import mock

import pytest

from .fuse_env import FuseEnv
from ..utils import yaml_parser
from ..cli import cli_main
from ..control_client import ControlClient, ControlClientUnableToConnectError
from ..search import Search
from ..storage_sync.daemon import SyncDaemon
from ..manifest.sig import SodiumSigContext


## CLI

@pytest.fixture
def base_dir():
    base_dir_s = tempfile.mkdtemp(prefix='wlcli.')
    base_dir = Path(base_dir_s)
    try:
        os.mkdir(base_dir / 'wildland')
        with open(base_dir / 'config.yaml', 'w') as f:
            yaml_parser.dump({
                'mount-dir': str(base_dir / 'wildland'),
                'dummy': True,
            }, f)
        yield base_dir
    finally:
        shutil.rmtree(base_dir)
        Search.clear_cache()


# fixme: find a way to customize 'base_dir' and 'cli' fixtures properly for injecting 'dummy' value
#  instead of duplicating code
#
#  See Wildland/wildland-client#739
@pytest.fixture
def base_dir_sodium():
    base_dir_s = tempfile.mkdtemp(prefix='wlcli.')
    base_dir = Path(base_dir_s)
    try:
        os.mkdir(base_dir / 'wildland')
        with open(base_dir / 'config.yaml', 'w') as f:
            yaml_parser.dump({
                'mount-dir': str(base_dir / 'wildland')
            }, f)
        yield base_dir
    finally:
        shutil.rmtree(base_dir)
        Search.clear_cache()


def _sync_daemon(base_dir):
    server = SyncDaemon(base_dir)
    server.main()


def _wait_for_sync_daemon(socket_path):
    delay = 0.5
    client = ControlClient()
    for _ in range(20):
        try:
            client.connect(socket_path)
            client.disconnect()
            return
        except ControlClientUnableToConnectError:
            time.sleep(delay)
    pytest.fail('Timed out waiting for sync daemon')

# dir_userid, alice_userid and charlie_userid are fixtures
# related to user-directory-setup


@pytest.fixture
def dir_userid():
    assert os.path.exists('/tmp/dir_userid')
    with open('/tmp/dir_userid') as f:
        dir_userid = f.read().splitlines()[0]
    return dir_userid


@pytest.fixture
def alice_userid():
    assert os.path.exists('/tmp/alice_userid')
    with open('/tmp/alice_userid') as f:
        alice_userid = f.read().splitlines()[0]
    return alice_userid


@pytest.fixture
def charlie_userid():
    assert os.path.exists('/tmp/charlie_userid')
    with open('/tmp/charlie_userid') as f:
        charlie_userid = f.read().splitlines()[0]
    return charlie_userid


@pytest.fixture
def sync(base_dir):
    # this fixture is so we can easily get coverage data from the sync daemon
    socket_path = Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlsync.sock'
    daemon = Process(target=_sync_daemon, args=(base_dir,))
    daemon.start()
    # make sure sync daemon is ready and accepting connections
    # to avoid subsequent Client instances accidentally spawning another one
    _wait_for_sync_daemon(socket_path)
    # if we don't yield anything here this whole function is executed immediately,
    # and the sync daemon is prematurely killed
    yield daemon

    assert daemon.pid
    os.kill(daemon.pid, signal.SIGINT)
    daemon.join()
    socket_path.unlink(missing_ok=True)


@pytest.fixture
def cli(base_dir, capsys):
    def cli(*args, capture=False):
        cmdline = ['-v', '--base-dir', base_dir, *args]
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
        # sync daemon is started and stopped by the sync fixture
        cli('stop', '--keep-sync-daemon')
        (Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir))) / 'wlfuse.sock').unlink(missing_ok=True)


@pytest.fixture
def cli_sodium(base_dir_sodium, capsys):
    def cli(*args, capture=False):
        cmdline = ['--base-dir', base_dir_sodium, *args]
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

    if os.path.ismount(base_dir_sodium / 'wildland'):
        # sync daemon is started and stopped by the sync fixture
        cli('stop', '--keep-sync-daemon')
        (Path(os.getenv('XDG_RUNTIME_DIR', str(base_dir_sodium))) / 'wlfuse.sock'
         ).unlink(missing_ok=True)


@pytest.fixture(params=[SodiumSigContext])
def sig_sodium(base_dir_sodium, request):
    return request.param(base_dir_sodium / 'keys')


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
