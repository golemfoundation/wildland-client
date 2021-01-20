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
Session class
'''

from pathlib import Path
from typing import Optional, Union, List

from .manifest.manifest import Manifest
from .manifest.sig import SigContext
from .user import User
from .container import Container
from .storage import Storage
from .bridge import Bridge


class Session:
    '''
    A low-level interface for loading and saving Wildland objects.
    '''

    def __init__(self, sig: SigContext):
        self.sig = sig

    def load_user(self,
                  data: bytes,
                  local_path: Optional[Path] = None
    ) -> User:
        '''
        Load a user manifest, creating a User object.
        '''

        manifest = Manifest.from_bytes(data, self.sig, allow_only_primary_key=True)

        owner, owner_pubkey = self.sig.load_key(manifest.fields['owner'])
        self.sig.add_pubkey(owner_pubkey)

        for pubkey in manifest.fields.get('pubkeys', []):
            if pubkey != owner_pubkey:
                # For backwards compatibility with old format where we did not put user's pubkey as
                # first pubkey in pubkeys
                self.sig.add_pubkey(pubkey, owner)

        return User.from_manifest(manifest, owner_pubkey, local_path)

    def load_container_or_bridge(
            self,
            data: bytes,
            local_path: Optional[Path] = None,
            trusted_owner: Optional[str] = None,
    ) -> Union[Container, Bridge]:
        '''
        Load a manifest that can be either a container or bridge manifest.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            trusted_owner=trusted_owner)
        # Unfortunately, there is no clean way of distinguishing the two.
        if 'user' in manifest.fields:
            return Bridge.from_manifest(manifest, local_path)
        return Container.from_manifest(manifest, local_path)

    def recognize_user(self, user: User):
        '''
        Recognize the user as a valid owner and add their optional pubkeys.
        '''

        user.add_user_keys(self.sig)

    def dump_user(self, user: User) -> bytes:
        '''
        Create a signed manifest out of a User object.
        '''

        manifest = user.to_unsigned_manifest()
        sig_temp = self.sig.copy()
        user.add_user_keys(sig_temp)
        manifest.sign(sig_temp, only_use_primary_key=True)
        return manifest.to_bytes()

    def load_container(
        self,
        data: bytes,
        local_path: Optional[Path] = None,
        trusted_owner: Optional[str] = None,
    ) -> Container:
        '''
        Load a container manifest, creating a Container object.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            trusted_owner=trusted_owner)
        return Container.from_manifest(manifest, local_path)

    def dump_container(self, container: Container) -> bytes:
        '''
        Create a signed manifest out of a Container object.
        '''

        manifest = container.to_unsigned_manifest()
        manifest.sign(self.sig)
        return manifest.to_bytes()

    def load_storage(
        self,
        data: bytes,
        local_path: Optional[Path] = None,
        trusted_owner: Optional[str] = None,
        local_owners: Optional[List[str]] = None,
    ) -> Storage:
        '''
        Load a container manifest, creating a Storage object.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            trusted_owner=trusted_owner)
        return Storage.from_manifest(manifest, local_path, local_owners=local_owners)

    def dump_storage(self, storage: Storage) -> bytes:
        '''
        Create a signed manifest out of a Storage object.
        '''

        manifest = storage.to_unsigned_manifest()
        manifest.sign(self.sig)
        return manifest.to_bytes()

    def load_bridge(
        self,
        data: bytes,
        local_path: Optional[Path] = None,
        trusted_owner: Optional[str] = None,
    ) -> Bridge:
        '''
        Load a bridge manifest, creating a Bridge object.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            trusted_owner=trusted_owner)
        return Bridge.from_manifest(manifest, local_path)

    def dump_bridge(self, bridge: Bridge) -> bytes:
        '''
        Create a signed manifest out of a Bridge object.
        '''

        manifest = bridge.to_unsigned_manifest()
        manifest.sign(self.sig)
        return manifest.to_bytes()
