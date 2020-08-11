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

import pytest

PROJECT_PATH = Path(__file__).resolve().parents[2]
ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class FuseEnv:
    '''
    A class for testing wildland-fuse. Usage:

        env = FuseEnv()
        try:
            env.mount()
            ...

        finally:
            env.destroy()

    The above can be wrapped in a Pytest fixture, see tests.py.
    '''

    def __init__(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix='wlfuse.'))
        self.mnt_dir = self.test_dir / 'mnt'
        self.socket_path = self.test_dir / 'wlfuse.sock'
        self.mounted = False
        self.proc = None

        os.mkdir(self.test_dir / 'mnt')
        os.mkdir(self.test_dir / 'storage')

    def mount(self):
        assert not self.mounted, 'only one mount() at a time'
        mnt_dir = self.test_dir / 'mnt'

        options = ['log=-', 'socket=' + str(self.socket_path)]

        self.proc = subprocess.Popen([
            ENTRY_POINT, mnt_dir,
            '-f', '-d',
            '-o', ','.join(options),
        ], cwd=PROJECT_PATH)
        try:
            self.wait_for_mount()
        except Exception:
            self.unmount()
            raise
        self.mounted = True

    def wait_for_mount(self, timeout=1):
        start = time.time()
        now = start
        while now - start < timeout:
            with open('/etc/mtab') as f:
                for line in f.readlines():
                    if 'wildland-fuse {} '.format(self.mnt_dir) in line:
                        return

            time.sleep(0.05)
            now = time.time()
        pytest.fail('Timed out waiting for mount', pytrace=False)

    def mount_storage(self, paths, storage, remount=False):
        self.mount_multiple_storages([(paths, storage)], remount)

    def mount_multiple_storages(self, storages, remount=False):
        cmd = []
        for paths, storage in storages:
            cmd.append({
                'paths': [str(p) for p in paths],
                'storage': storage,
                'remount': remount,
            })

        with open(self.mnt_dir / '.control/mount', 'w') as f:
            f.write(json.dumps(cmd) + '\n\n')

    def unmount_storage(self, ident):
        with open(self.mnt_dir / '.control/unmount', 'w') as f:
            f.write(str(ident))

    def refresh_storage(self, ident):
        with open(self.mnt_dir / '.control/clear-cache', 'w') as f:
            f.write(str(ident))

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

    def unmount(self):
        assert self.mounted
        assert self.proc

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

    def run_control_command(self, name: str, args: dict):
        '''
        Connect to the control server and run a command.
        '''

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(str(self.socket_path))
            conn.sendall(json.dumps({'cmd': name, 'args': args}).encode() + b'\n\n')

            response_bytes = conn.recv(1024)
            response = json.loads(response_bytes)
            if 'error' in response:
                return response['error']
            return response['result']
