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

from ..exc import WildlandError
from ..fs_client import WildlandFSClient
from ..client import Client


class CliError(WildlandError):
    '''
    User error during CLI command execution
    '''

# pylint: disable=no-self-use


class ContextObj:
    '''Helper object for keeping state in :attr:`click.Context.obj`'''

    def __init__(self, client: Client):
        self.fs_client = client.fs_client
        self.mount_dir: Path = client.fs_client.mount_dir
        self.client = client
        self.session = client.session
