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
Wildland command-line interface - base module.
'''

import os
from pathlib import Path, PurePosixPath
import sys
import time

from typing import Optional, Tuple

import click

from ..manifest.loader import ManifestLoader
from ..manifest.user import User
from ..exc import WildlandError


class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use


class ContextObj:
    '''Helper object for keeping state in :attr:`click.Context.obj`'''

    def __init__(self, loader: ManifestLoader):
        self.loader: ManifestLoader = loader
        self.mount_dir: Path = Path(loader.config.get('mount_dir'))

    def read_manifest_file(self,
                           name: Optional[str],
                           manifest_type: Optional[str]) \
                           -> Tuple[bytes, Optional[Path]]:
        '''
        Read a manifest file specified by name. Recognize None as stdin.

        Returns (data, file_path).
        '''

        if name is None:
            return (sys.stdin.buffer.read(), None)

        path = self.loader.find_manifest(name, manifest_type)
        if not path:
            if manifest_type:
                raise CliError(
                    f'{manifest_type.title()} manifest not found: {name}')
            raise CliError(f'Manifest not found: {name}')
        print(f'Loading: {path}')
        with open(path, 'rb') as f:
            return (f.read(), path)

    def find_user(self, name: Optional[str]) -> User:
        '''
        Find a user specified by name, using default if there is none.
        '''

        if name:
            user = self.loader.find_user(name)
            if not user:
                raise CliError(f'User not found: {name}')
            print(f'Using user: {user.signer}')
            return user
        user = self.loader.find_default_user()
        if user is None:
            raise CliError(
                'Default user not set, you need to provide --user')
        print(f'Using default user: {user.signer}')
        return user

    def write_control(self, name: str, data: bytes):
        '''
        Write to a .control file.
        '''

        control_path = self.mount_dir / '.control' / name
        try:
            with open(control_path, 'wb') as f:
                f.write(data)
        except IOError as e:
            raise CliError(f'Control command failed: {control_path}: {e}')

    def read_control(self, name: str) -> bytes:
        '''
        Read a .control file.
        '''

        control_path = self.mount_dir / '.control' / name
        try:
            with open(control_path, 'rb') as f:
                return f.read()
        except IOError as e:
            raise CliError(f'Reading control file failed: {control_path}: {e}')

    def ensure_mounted(self):
        '''
        Check that Wildland is mounted, and raise an exception otherwise.
        '''

        if not os.path.isdir(self.mount_dir / '.control'):
            raise click.ClickException(
                f'Wildland not mounted at {self.mount_dir}')

    def wait_for_mount(self):
        '''
        Wait until Wildland is mounted.
        '''

        n_tries = 20
        delay = 0.1
        for _ in range(n_tries):
            if os.path.isdir(self.mount_dir / '.control'):
                return
            time.sleep(delay)
        raise CliError(f'Timed out waiting for Wildland to mount: {self.mount_dir}')


    def get_command_for_mount_container(self, container):
        '''
        Prepare command to be written to :file:`/.control/mount` to mount
        a container

        Args:
            container (Container): the container to be mounted
        '''
        signer = container.manifest.fields['signer']
        default_user = self.loader.config.get('default_user')

        paths = [
            os.fspath(self.get_user_path(signer, path))
            for path in container.paths
        ]
        if signer is not None and signer == default_user:
            paths.extend(os.fspath(p) for p in container.paths)

        return {
            'paths': paths,
            'storage': container.select_storage(self.loader).fields,
        }

    def get_user_path(self, signer, path: PurePosixPath) -> PurePosixPath:
        '''
        Prepend an absolute path with signer namespace.
        '''
        return PurePosixPath('/.users/') / signer / path.relative_to('/')
