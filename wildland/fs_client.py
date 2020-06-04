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

import yaml

from .container import Container
from .storage import Storage
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

    def __init__(self, mount_dir: Path):
        self.mount_dir = mount_dir
        self.control_dir = self.mount_dir / '.control'

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

    def mount_container(self,
                        container: Container,
                        storage: Storage,
                        is_default_user: bool = False):
        '''
        Mount a container, assuming a storage has been already selected.
        '''

        if self.find_storage_id(container) is not None:
            raise WildlandFSError('Already mounted')
        command = self.get_command_for_mount_container(container, storage, is_default_user)
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

    def find_all_storage_ids_for_path(self, path: PurePosixPath):
        '''
        Given a path, retrieve all mounted storages this path is inside.

        Note that this doesn't include synthetic directories leading up to
        mount path, e.g. if a storage is mounted under /a/b, then it will be
        included as a storage for /a/b and /a/b/c, but not for /a.
        '''

        result = []
        paths = self.get_paths()
        for mount_path, storage_ids in paths.items():
            if path == mount_path or mount_path in path.parents:
                result.extend(storage_ids)

        return result

    def find_trusted_signer(self, local_path: Path) -> Optional[str]:
        '''
        Given a path in the filesystem, check if this is a path from a trusted
        storage, and if so, return the trusted_signer value.

        If the path potentially belongs to multiple storages, this method will
        conservatively check if all of them would give the same answer.
        '''

        if not self.is_mounted():
            return None

        local_path = local_path.resolve()
        try:
            relpath = local_path.relative_to(self.mount_dir)
        except ValueError:
            # Outside our filesystem
            return None

        path = PurePosixPath('/') / relpath
        storage_ids = self.find_all_storage_ids_for_path(path)
        if len(storage_ids) == 0:
            # Outside of any storage
            return None

        trusted_signers = set()
        for storage_id in storage_ids:
            manifest = self.get_storage_manifest(storage_id)
            if not manifest:
                # No manifest
                return None

            if not manifest.get('trusted'):
                # Not a trusted storage
                return None

            signer = manifest.get('signer')
            if not signer:
                # No signer
                return None

            trusted_signers.add(signer)

        if len(trusted_signers) != 1:
            # More than one trusted signer
            return None

        return list(trusted_signers)[0]

    def get_paths(self) -> Dict[PurePosixPath, List[int]]:
        '''
        Read a path -> container ID mapping.
        '''
        data = json.loads(self.read_control('paths'))
        return {
            PurePosixPath(p): ident
            for p, ident in data.items()
        }

    def get_storage_manifest(self, storage_id: int) -> Optional[dict]:
        '''
        Read a storage manifest for a mounted storage.
        '''

        control_path = self.control_dir / f'storage/{storage_id}/manifest.yaml'
        if not control_path.exists():
            return None
        data = control_path.read_bytes()
        return yaml.safe_load(data)

    def get_command_for_mount_container(self,
                                        container: Container,
                                        storage: Storage,
                                        is_default_user: bool):
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
        if is_default_user:
            paths.extend(os.fspath(p) for p in container.paths)

        return {
            'paths': paths,
            'storage': storage.params,
        }

    @staticmethod
    def get_user_path(signer, path: PurePosixPath) -> PurePosixPath:
        '''
        Prepend an absolute path with signer namespace.
        '''
        return PurePosixPath('/.users/') / signer / path.relative_to('/')
