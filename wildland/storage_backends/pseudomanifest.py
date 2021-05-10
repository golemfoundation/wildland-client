# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Patryk Bęza <patryk@wildland.io>
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

"""
Storage exposing pseudomanifest in mountpoint's root directory
"""

import uuid

from ..storage_backends.static import StaticStorageBackend

class PseudoManifestStorage(StaticStorageBackend):
    """
    Storage backend responsible for exposing a hidden pseudo-manifest file in the container root
    directory.
    """

    TYPE = 'pseudomanifest'
    CONTAINER_PSEUDO_MANIFEST_NAME = '.manifest.wildland.yaml'

    def __init__(self, content: bytes):
        super().__init__(
            params={
                'backend-id': str(uuid.uuid4()),
                'type': self.TYPE,
                'content': {self.CONTAINER_PSEUDO_MANIFEST_NAME: content}
            },
        )
