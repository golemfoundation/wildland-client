# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Session class
"""

from pathlib import Path
from typing import Optional

from wildland.wildland_object.wildland_object import PublishableWildlandObject
from .manifest.manifest import Manifest, ManifestError
from .manifest.sig import SigContext
from .user import User


class Session:
    """
    A low-level interface for saving Wildland objects.
    """

    def __init__(self, sig: SigContext):
        self.sig = sig

    def dump_user(self, user: User, path: Optional[Path] = None) -> bytes:
        """
        Create a signed manifest out of a User object.
        """

        manifest = Manifest.from_fields(user.to_manifest_fields(inline=False), local_path=path)

        try:
            if user.manifest and user.manifest.fields == manifest.fields:
                return user.manifest.to_bytes()
        except ManifestError:
            pass

        sig_temp = self.sig.copy()
        user.add_user_keys(sig_temp)
        manifest.encrypt_and_sign(sig_temp, only_use_primary_key=True)
        user.manifest = manifest
        return manifest.to_bytes()

    def dump_object(self, obj: PublishableWildlandObject,
                    path: Optional[Path] = None) -> bytes:
        """
        Create a signed manifest out of a Bridge/Container/Storage object; if the object was created
        from a signed manifest and did not change, returns that object, otherwise creates and
        signs the manifest.
        """
        manifest = Manifest.from_fields(obj.to_manifest_fields(inline=False), local_path=path)

        try:
            if obj.manifest and obj.manifest.fields == manifest.fields:
                return obj.manifest.to_bytes()
        except ManifestError:
            pass

        manifest.encrypt_and_sign(self.sig)
        obj.manifest = manifest
        return manifest.to_bytes()
