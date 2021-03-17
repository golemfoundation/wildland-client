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

# pylint: disable=missing-docstring

import subprocess
import tempfile
import os
import shutil
from pathlib import Path
import traceback
import time
import json
import socket
from typing import Optional, Dict, List
import pytest

PROJECT_PATH = Path(__file__).resolve().parents[2]
ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class FuseError(Exception):
    pass


class FuseEnv:
    """
    A class for testing wildland-fuse. Usage:

        env = FuseEnv()
        try:
            env.mount()
            ...

        finally:
            env.destroy()

    The above can be wrapped in a Pytest fixture, see tests.py.

    This roughly corresponds to WildlandFSClient (fs_client.py), but
    intentionally does not depend on the rest of Wildland code.
    """

    def __init__(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix='wlfuse.'))
        self.mnt_dir = self.test_dir / 'mnt'
        self.storage_dir = self.test_dir / 'storage'
        self.socket_path = self.test_dir / 'wlfuse.sock'
        self.mounted = False
        self.proc = None
        self.conn: Optional[socket.socket] = None

        os.mkdir(self.mnt_dir)
        os.mkdir(self.storage_dir)

    def mount(self):
        assert not self.mounted, 'only one mount() at a time'

        options = ['log=-', 'socket=' + str(self.socket_path)]

        self.proc = subprocess.Popen([
            ENTRY_POINT, self.mnt_dir,
            '-f', '-d',
            '-o', ','.join(options),
        ], cwd=PROJECT_PATH)
        try:
            self.conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.wait_for_mount(self.conn)
        except Exception:
            self.unmount()
            raise
        self.mounted = True

    def wait_for_mount(self, conn, timeout=1):
        start = time.time()
        now = start
        while now - start < timeout:
            try:
                conn.connect(str(self.socket_path))
                return
            except IOError:
                pass
            time.sleep(0.05)
            now = time.time()
        pytest.fail('Timed out waiting for mount', pytrace=False)

    def mount_storage(self, paths, storage, remount=False):
        self.mount_multiple_storages([(paths, storage)], remount)

    def mount_multiple_storages(self, storages, remount=False):
        items = []
        for paths, storage in storages:
            items.append({
                'paths': [str(p) for p in paths],
                'storage': storage,
                'remount': remount,
            })

        self.run_control_command('mount', {'items': items})

    def unmount_storage(self, ident):
        self.run_control_command('unmount', {'storage-id': ident})

    def refresh_storage(self, ident):
        self.run_control_command('clear-cache', {'storage-id': ident})

    def create_dir(self, name):
        os.mkdir(self.test_dir / name)

    def create_file(self, name, content='', mode=None):
        path = self.test_dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
        if mode is not None:
            os.chmod(path, mode)

    def create_symlink(self, src, dst, storage_subdir=''):
        assert '..' not in dst
        # Make symlink relative to the given subdirectory
        dir_fd = os.open(self.test_dir / self.storage_dir / storage_subdir, flags=os.O_DIRECTORY)
        os.symlink(src, dst, dir_fd=dir_fd)
        os.close(dir_fd)

    def unmount(self):
        assert self.mounted
        assert self.proc
        assert self.conn

        self.conn.close()
        self.conn = None
        subprocess.run(['fusermount', '-u', self.mnt_dir], check=False)
        self.proc.wait()
        self.proc = False
        self.mounted = False

    def destroy(self):
        if self.mounted:
            try:
                self.unmount()
            except Exception:
                traceback.print_exc()
        shutil.rmtree(self.test_dir)

    def run_control_command(self, name: str, args=None):
        """
        Connect to the control server and run a command.
        """

        assert self.conn

        request = {'cmd': name}
        if args is not None:
            request['args'] = args

        self.conn.sendall(json.dumps(request).encode() + b'\n\n')

        response_bytes = self.conn.recv(1024)
        response = json.loads(response_bytes)
        if 'error' in response:
            error_class = response['error']['class']
            error_desc = response['error']['desc']
            raise FuseError(f'{error_class}: {error_desc}')
        return response['result']

    def recv_event(self):
        """
        Receive an event from control server.
        """

        assert self.conn

        # force timeout, in case something goes very wrong with tests
        self.conn.settimeout(5)
        response_bytes = self.conn.recv(1024)
        response_list = response_bytes.split(b'\n\n')

        events: List[Dict[str, str]] = []

        for response_bytes in response_list:
            if not response_bytes:
                continue
            response = json.loads(response_bytes)
            assert 'event' in response, 'expecting an event'

            events.extend(response['event'])

        return events
