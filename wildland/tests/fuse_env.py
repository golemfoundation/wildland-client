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
        self.mounted = False
        self.proc = None

        os.mkdir(self.test_dir / 'mnt')
        os.mkdir(self.test_dir / 'storage')

    def mount(self):
        assert not self.mounted, 'only one mount() at a time'
        mnt_dir = self.test_dir / 'mnt'

        options = ['log=-']

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

    def mount_storage(self, paths, storage):
        with open(self.mnt_dir / '.control/mount', 'w') as f:
            f.write(json.dumps({
                'paths': [str(p) for p in paths],
                'storage': storage
            }))

    def unmount_storage(self, ident):
        with open(self.mnt_dir / '.control/unmount', 'w') as f:
            f.write(str(ident))

    def create_dir(self, name):
        os.mkdir(self.test_dir / name)

    def create_file(self, name, content='', mode=None):
        path = self.test_dir / name
        with open(path, 'w') as f:
            f.write(content)
        if mode is not None:
            os.chmod(path, mode)

    def unmount(self):
        assert self.mounted

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
