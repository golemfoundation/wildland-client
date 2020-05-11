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

from pathlib import Path
import sys

from typing import Optional, Tuple

from ..manifest.loader import ManifestLoader
from ..manifest.user import User
from ..exc import WildlandError
from ..fs_client import WildlandFSClient


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
        self.client: WildlandFSClient = WildlandFSClient(self.mount_dir, loader)

    def read_manifest_file(self,
                           name: Optional[str],
                           manifest_type: Optional[str],
                           remote: bool = False) \
                           -> Tuple[Optional[Path], bytes]:
        '''
        Read a manifest file specified by name. Recognize None as stdin.

        Returns (data, file_path).
        '''

        if name is None:
            return (None, sys.stdin.buffer.read())

        path, data = self.loader.read_manifest(name, manifest_type,
                                               remote=remote)
        print(f'Loading manifest: {path}')
        return path, data

    def find_user(self, name: Optional[str]) -> User:
        '''
        Find a user specified by name, using default if there is none.
        '''

        if name:
            user = self.loader.find_user(name)
            print(f'Using user: {user.signer}')
            return user

        default_user = self.loader.find_default_user()
        if default_user is None:
            raise CliError(
                'Default user not set, you need to provide --user')
        print(f'Using default user: {default_user.signer}')
        return default_user
