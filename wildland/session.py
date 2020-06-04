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
from typing import Optional, Union

from .manifest.manifest import Manifest
from .manifest.sig import SigContext
from .user import User
from .container import Container
from .storage import Storage


class Session:
    '''
    A low-level interface for loading and saving Wildland objects.
    '''

    def __init__(self, sig: SigContext):
        self.sig = sig

    def load_user(self,
                  data: bytes,
                  local_path: Optional[Path] = None) -> User:
        '''
        Load a user manifest, creating a User object.
        '''

        manifest = Manifest.from_bytes(
            data, self.sig, self_signed=Manifest.REQUIRE)
        return User.from_manifest(manifest, local_path)

    def load_container_or_user(
            self,
            data: bytes,
            local_path: Optional[Path] = None,
            trusted_signer: Optional[str] = None,
    ) -> Union[Container, User]:
        '''
        Load a manifest that cal be either a container or user manifest.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            self_signed=Manifest.ALLOW,
            trusted_signer=trusted_signer)
        assert manifest.header
        if manifest.header.pubkey is not None:
            return User.from_manifest(manifest, local_path)
        return Container.from_manifest(manifest, local_path)

    def recognize_user(self, user: User):
        '''
        Recognize the user as a valid signer.
        '''

        self.sig.add_pubkey(user.pubkey)

    def dump_user(self, user: User) -> bytes:
        '''
        Create a signed manifest out of a User object.
        '''

        manifest = user.to_unsigned_manifest()
        sig_temp = self.sig.copy()
        sig_temp.add_pubkey(user.pubkey)
        manifest.sign(sig_temp, attach_pubkey=True)
        return manifest.to_bytes()

    def load_container(
        self,
        data: bytes,
        local_path: Optional[Path] = None,
        trusted_signer: Optional[str] = None,
    ) -> Container:
        '''
        Load a container manifest, creating a Container object.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            self_signed=Manifest.DISALLOW,
            trusted_signer=trusted_signer)
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
        trusted_signer: Optional[str] = None,
    ) -> Storage:
        '''
        Load a container manifest, creating a Storage object.
        '''

        manifest = Manifest.from_bytes(
            data,
            self.sig,
            self_signed=Manifest.DISALLOW,
            trusted_signer=trusted_signer)
        return Storage.from_manifest(manifest, local_path)

    def dump_storage(self, storage: Storage) -> bytes:
        '''
        Create a signed manifest out of a Storage object.
        '''

        manifest = storage.to_unsigned_manifest()
        manifest.sign(self.sig)
        return manifest.to_bytes()
