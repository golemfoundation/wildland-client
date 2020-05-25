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
User manifest and user management
'''

from pathlib import PurePosixPath
from typing import List

from .manifest.manifest import Manifest
from .manifest.schema import Schema


class User:
    '''Wildland user'''

    SCHEMA = Schema('user')

    def __init__(self, manifest: Manifest, manifest_path=None):
        self.manifest = manifest
        self.manifest_path = manifest_path

        assert manifest.header
        assert manifest.header.pubkey
        self.signer = manifest.fields['signer']
        self.pubkey = manifest.header.pubkey
        self.paths: List[PurePosixPath] = \
            [PurePosixPath(p) for p in manifest.fields['paths']]
        self.containers: List[str] = \
            manifest.fields['containers']
