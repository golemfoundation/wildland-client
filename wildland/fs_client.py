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

'''
Wildland FS client
'''

import os
import time
from pathlib import Path, PurePosixPath
import subprocess
import logging
from typing import Dict, List, Optional
import json

from .manifest.loader import ManifestLoader
from .container import Container
from .exc import WildlandError


logger = logging.getLogger('fs_client')

PROJECT_PATH = Path(__file__).resolve().parents[1]
FUSE_ENTRY_POINT = PROJECT_PATH / 'wildland-fuse'


class WildlandFSError(WildlandError):
    '''Error while trying to control Wildland FS.'''


class WildlandFSClient:
    '''
    A class to communicate with Wildland filesystem over the .control API.
    '''

    def __init__(self, mount_dir: Path, loader: ManifestLoader):
        self.mount_dir = mount_dir
        self.control_dir = self.mount_dir / '.control'
        self.loader = loader
        self.default_user = self.loader.config.get('default_user')

    def mount(self, foreground=False, debug=False) -> subprocess.Popen:
        '''
        Mount the Wildland filesystem and wait until it is mounted.

        Returns the called process (running in case of foreground=True).

        Args:
            foreground: Run in foreground instead of daemonizing
            debug: Enable debug logs (only in case of foreground)
        '''
        cmd = [str(FUSE_ENTRY_POINT), str(self.mount_dir)]
        options = []

        if foreground:
            options.append('log=-')
            cmd.append('-f')
            if debug:
                cmd.append('-d')

        if options:
            cmd += ['-o', ','.join(options)]

        logger.info('running mount command: %s', cmd)

        # Start a new session in order to not propagate SIGINT.
        proc = subprocess.Popen(cmd, start_new_session=True)
        if foreground:
            self.wait_for_mount()
            return proc
        try:
            proc.wait()
            self.wait_for_mount()
            if proc.returncode != 0:
                raise WildlandFSError(f'Command failed: {cmd}')
            return proc
        except Exception:
            self.unmount()
            raise

    def unmount(self):
        '''
        Unmount the Wildland filesystem.
        '''
        cmd = ['umount', str(self.mount_dir)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise WildlandFSError(f'Failed to unmount: {e}')

    def is_mounted(self) -> bool:
        '''
        Check if Wildland is currently mounted.
        '''
        return os.path.isdir(self.control_dir)

    def write_control(self, name: str, data: bytes):
        '''
        Write to a .control file.
        '''

        logger.info('write %s: %s', name, data)
        control_path = self.control_dir / name
        try:
            with open(control_path, 'wb') as f:
                f.write(data)
        except IOError as e:
            raise WildlandFSError(f'Control command failed: {control_path}: {e}')

    def read_control(self, name: str) -> bytes:
        '''
        Read a .control file.
        '''

        control_path = self.control_dir / name
        try:
            with open(control_path, 'rb') as f:
                data = f.read()
                logger.info('read %s: %s', control_path, data)
                return data
        except IOError as e:
            raise WildlandFSError(f'Reading control file failed: {control_path}: {e}')

    def ensure_mounted(self):
        '''
        Check that Wildland is mounted, and raise an exception otherwise.
        '''

        if not os.path.isdir(self.mount_dir / '.control'):
            raise WildlandFSError(
                f'Wildland not mounted at {self.mount_dir}')

    def wait_for_mount(self, timeout=2):
        '''
        Wait until Wildland is mounted.
        '''

        delay = 0.1
        n_tries = int(timeout / delay)
        for _ in range(n_tries):
            if self.is_mounted():
                return
            time.sleep(delay)
        raise WildlandFSError('Timed out waiting for Wildland to mount')

    def mount_container(self, container: Container):
        '''
        Mount a container.
        '''
        if self.find_storage_id(container) is not None:
            raise WildlandFSError('Already mounted')
        command = self.get_command_for_mount_container(container)
        self.write_control('mount', json.dumps(command).encode())

    def unmount_container(self, storage_id: int):
        '''
        Unmount a container with given storage ID.
        '''

        self.write_control('unmount', str(storage_id).encode())

    def find_storage_id(self, container: Container) -> Optional[int]:
        '''
        Find storage ID for a given container.
        '''

        mount_path = self.get_user_path(container.signer, container.paths[0])
        return self.find_storage_id_by_path(mount_path)

    def find_storage_id_by_path(self, path: PurePosixPath) -> Optional[int]:
        '''
        Find storage ID for a given mount path.
        '''

        paths = self.get_paths()
        storage_ids = paths.get(path)
        if storage_ids is None:
            return None
        if len(storage_ids) > 1:
            logger.warning('multiple storages found for path: %s', path)
        return storage_ids[0]

    def get_paths(self) -> Dict[PurePosixPath, List[int]]:
        '''
        Read a path -> container ID mapping.
        '''
        data = json.loads(self.read_control('paths'))
        return {
            PurePosixPath(p): ident
            for p, ident in data.items()
        }

    def get_command_for_mount_container(self, container: Container):
        '''
        Prepare command to be written to :file:`/.control/mount` to mount
        a container

        Args:
            container (Container): the container to be mounted
        '''
        paths = [
            os.fspath(self.get_user_path(container.signer, path))
            for path in container.paths
        ]
        if container.signer == self.default_user:
            paths.extend(os.fspath(p) for p in container.paths)

        return {
            'paths': paths,
            'storage': container.select_storage(self.loader).fields,
        }

    @staticmethod
    def get_user_path(signer, path: PurePosixPath) -> PurePosixPath:
        '''
        Prepend an absolute path with signer namespace.
        '''
        return PurePosixPath('/.users/') / signer / path.relative_to('/')
