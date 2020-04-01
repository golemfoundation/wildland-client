import subprocess
import tempfile
import os
import sys
import shutil
from pathlib import Path
import traceback

import pytest
import yaml


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
        self.test_dir = Path(tempfile.mkdtemp(prefix='wlfuse'))
        self.mnt_dir = self.test_dir / 'mnt'
        self.log_file = self.test_dir / 'wlfuse.log'
        self.mounted = False

        os.mkdir(self.test_dir / 'mnt')
        os.mkdir(self.test_dir / 'storage')
        with open(self.log_file, 'w'):
            pass

    def mount(self, manifests):
        assert not self.mounted, 'only one mount() at a time'
        mnt_dir = self.test_dir / 'mnt'

        options = ['manifest={}'.format(self.test_dir / manifest)
                   for manifest in manifests]

        env = os.environ.copy()
        env['WLFUSE_LOG'] = self.log_file
        try:
            subprocess.run(['/sbin/mount.fuse', ENTRY_POINT, mnt_dir,
                            '-o', ','.join(options)],
                           env=env,
                           cwd=PROJECT_PATH,
                           check=True)
        except subprocess.CalledProcessError:
            with open(self.log_file, 'r') as f:
                log = f.read()
            pytest.fail('mount failed:\n' + log, pytrace=False)

        self.mounted = True

    def create_manifest(self, name, data):
        with open(self.test_dir / name, 'w') as f:
            yaml.dump(data, f)

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

        subprocess.run(['fusermount', '-u', self.mnt_dir], check=True)
        self.mounted = False

    def dump_log(self):
        with open(self.log_file) as f:
            log = f.read()
        if log:
            sys.stderr.write('log:\n' + log)

    def destroy(self):
        self.dump_log()
        if self.mounted:
            try:
                self.unmount()
            except Exception:
                traceback.print_exc()
        shutil.rmtree(self.test_dir)
