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

"""
Session class
"""

from pathlib import Path
from typing import Optional, Union, List

from .manifest.manifest import Manifest, ManifestError, WildlandObjectType
from .manifest.sig import SigContext
from .user import User
from .container import Container
from .storage import Storage
from .bridge import Bridge


class Session:
    """
    A low-level interface for loading and saving Wildland objects.
    """

    def __init__(self, sig: SigContext):
        self.sig = sig

    def load_object(self, data: bytes,
                    object_type: Optional[WildlandObjectType] = None,
                    local_path: Optional[Path] = None,
                    trusted_owner: Optional[str] = None,
                    local_owners: Optional[List[str]] = None,
                    allow_only_primary_key: Optional[bool] = None,
                    decrypt: bool = True) -> \
            Union[User, Bridge, Storage, Container]:
        """
        Load a WL object from raw bytes and return it.
        :param data: raw object bytes
        :param object_type: expected object type; if received object of a different type, an
        AssertionError will be raised
        :param local_path: path to local file with object manifest, if exists
        :param trusted_owner: skip signature verification for this owner (optional)
        :param local_owners: list of owners allows to access local files (optional)
        :param allow_only_primary_key: must the data be signed by owner's primary key or are
        other keys also allowed?
        :param decrypt: should we attempt to decrypt the object manifest?
        """
        if allow_only_primary_key is None:
            allow_only_primary_key = (object_type == WildlandObjectType.USER)

        manifest = Manifest.from_bytes(data, self.sig,
                                       allow_only_primary_key=allow_only_primary_key,
                                       trusted_owner=trusted_owner, decrypt=decrypt)

        assert not object_type or manifest.fields['object'] == object_type.value
        if not object_type:
            object_type = WildlandObjectType(manifest.fields['object'])

        if object_type == WildlandObjectType.USER:
            _, owner_pubkey = self.sig.load_key(manifest.fields['owner'])
            self.sig.add_pubkey(owner_pubkey)
            return User.from_manifest(manifest, owner_pubkey, local_path)

        if object_type == WildlandObjectType.BRIDGE:
            return Bridge.from_manifest(manifest, self.sig, local_path)

        if object_type == WildlandObjectType.STORAGE:
            return Storage.from_manifest(manifest, local_path, local_owners=local_owners)

        if object_type == WildlandObjectType.CONTAINER:
            return Container.from_manifest(manifest, local_path)

        raise ValueError

    def dump_user(self, user: User) -> bytes:
        """
        Create a signed manifest out of a User object.
        """

        manifest = user.to_unsigned_manifest()

        try:
            if user.manifest and user.manifest.fields == manifest.fields:
                return user.manifest.to_bytes()
        except ManifestError:
            pass

        sig_temp = self.sig.copy()
        user.add_user_keys(sig_temp)
        manifest.encrypt_and_sign(sig_temp, only_use_primary_key=True)
        return manifest.to_bytes()

    def dump_object(self, obj: Union[Bridge, Storage, Container]) -> bytes:
        """
        Create a signed manifest out of a Bridge/Container/Storage object; if the object was created
        from a signed manifest and did not change, returns that object, otherwise creates and
        signs the manifest.
        """
        manifest = obj.to_unsigned_manifest()

        try:
            if obj.manifest and obj.manifest.fields == manifest.fields:
                return obj.manifest.to_bytes()
        except ManifestError:
            pass

        manifest.encrypt_and_sign(self.sig)
        return manifest.to_bytes()
