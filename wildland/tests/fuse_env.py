import subprocess
import tempfile
import os
import shutil
from pathlib import Path
import traceback
import time

import pytest

from ..manifest import Manifest
from ..sig import DummySigContext

PROJECT_PATH = Path(__file__).resolve().parents[2]
ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class FuseEnv:
    '''
    A class for testing wildland-fuse. Usage:

        env = FuseEnv()
        try:
            # Prepare
            env.add_manifest('manifest1.yaml', {...})
            ...
            # Mount
            env.mount(['manifest1.yaml'])

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

    def mount(self, manifests):
        assert not self.mounted, 'only one mount() at a time'
        mnt_dir = self.test_dir / 'mnt'

        options = ['manifest={}'.format(self.test_dir / manifest)
                   for manifest in manifests]
        options.append('log=-')

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

    def create_manifest(self, name, fields):
        if 'signer' not in fields:
            fields['signer'] = 'signer'
        manifest = Manifest.from_fields(fields, DummySigContext())
        with open(self.test_dir / name, 'wb') as f:
            f.write(manifest.to_bytes())

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
