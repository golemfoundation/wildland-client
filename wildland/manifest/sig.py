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
Module for handling signatures. Provides two backends: Signify, and a
"dummy" one.
'''

import tempfile
import shutil
from typing import TypeVar, Dict, Tuple
from pathlib import Path
import os
import subprocess
import base64
import binascii
import stat

from ..exc import WildlandError


class SigError(WildlandError):
    '''
    Exception class for problems during the signing or verification process.
    '''


T = TypeVar('T')


class SigContext:
    '''
    A class for signing and verifying signatures. Operates on 'owner'
    identifiers, serving as key fingerprints.
    '''

    def __init__(self):
        self.use_local_keys = False

    def recognize_local_keys(self):
        '''
        Recognize local keys (i.e. ones found using find()) while loading.
        '''

        self.use_local_keys = True

    def copy(self: T) -> T:
        '''
        Create a copy of the current context.
        '''
        raise NotImplementedError()

    def generate(self) -> Tuple[str, str]:
        '''
        Generate a new key pair and store it.

        Returns a pair of (owner, pubkey).
        '''
        raise NotImplementedError()

    def add_pubkey(self, pubkey: str) -> str:
        '''
        Add a public key to recognized owners. Returns a owner ID.
        '''
        raise NotImplementedError()

    def get_pubkey(self, owner: str) -> str:
        '''
        Get a public key by owner ID.
        '''
        raise NotImplementedError()

    def find(self, key_id: str) -> Tuple[str, str]:
        '''
        Find a canonical form for the key.

        Returns a pair of (owner, pubkey).
        '''
        raise NotImplementedError()

    def sign(self, owner: str, data: bytes) -> str:
        '''
        Sign data using a given owner's key.
        '''
        raise NotImplementedError()

    def verify(self, signature: str, data: bytes) -> str:
        '''
        Verify signature for data, returning the recognized owner.
        If self_signed, ignore that a owner is not recognized.
        '''
        raise NotImplementedError()


class DummySigContext(SigContext):
    '''
    A SigContext that requires a dummy signature (of the form "dummy.{owner}"),
    for testing purposes.
    '''

    def __init__(self):
        super().__init__()
        self.owners = set()

    def copy(self) -> 'DummySigContext':
        copied = DummySigContext()
        copied.owners = self.owners.copy()
        return copied

    def generate(self) -> Tuple[str, str]:
        return '0xfff', 'key.0xfff'

    def add_pubkey(self, pubkey: str) -> str:
        if not pubkey.startswith('key.'):
            raise SigError('Expected key.* key, got {!r}'.format(pubkey))

        owner = pubkey[len('key.'):]
        self.owners.add(owner)
        return owner

    def get_pubkey(self, owner: str) -> str:
        return f'key.{owner}'

    def find(self, key_id: str) -> Tuple[str, str]:
        return key_id, f'key.{key_id}'

    def sign(self, owner: str, data: bytes) -> str:
        return f'dummy.{owner}'

    def verify(self, signature: str, data: bytes) -> str:
        if not signature.startswith('dummy.'):
            raise SigError(
                'Expected dummy.* signature, got {!r}'.format(signature))

        owner = signature[len('dummy.'):]
        if not (owner in self.owners or self.use_local_keys):
            raise SigError('Unknown owner: {!r}'.format(owner))
        return owner



class SignifySigContext(SigContext):
    '''
    A Signify backend.

    The key_dir directory is for storing generated key pairs.
    '''

    def __init__(self, key_dir: Path):
        super().__init__()
        self.key_dir = key_dir
        self.binary: str = self._find_binary()
        self.owners: Dict[str, str] = {}

    @staticmethod
    def _find_binary():
        for name in ['signify-openbsd', 'signify']:
            binary = shutil.which(name)
            if binary is not None:
                return binary
        raise WildlandError('signify binary not found, please install signify-openbsd')

    @staticmethod
    def fingerprint(pubkey: str) -> str:
        '''
        Convert Signify pubkey to a owner identifier (fingerprint).
        '''
        # # strip unneeded syntactic sugar and empty lines
        pubkey_data = SignifySigContext.strip_key(pubkey)

        data = base64.b64decode(pubkey_data)
        prefix = data[:10][::-1]
        return '0x' + binascii.hexlify(prefix).decode()

    @staticmethod
    def strip_key(key: str) -> str:
        '''
        Strips empty lines and comments from a Signify-generated key
        '''
        return [line for line in key.splitlines() if line
                and not line.startswith('untrusted comment')][0]

    def generate(self) -> Tuple[str, str]:
        '''
        Generate a new key pair and store it in key_dir.

        Returns a pair of (owner, pubkey).
        '''

        with tempfile.TemporaryDirectory(prefix='wlsig.') as d:
            secret_file = Path(d) / 'key.sec'
            public_file = Path(d) / 'key.pub'
            subprocess.run(
                [self.binary,
                 '-G',
                 '-q',  # quiet
                 '-n',  # no passphrase
                 '-s', secret_file,
                 '-p', public_file],
                check=True
            )

            # strip unnecessary comments and empty lines
            for file in [secret_file, public_file]:
                key = file.read_text()
                key_data = self.strip_key(key)
                with file.open(mode='w') as f:
                    f.seek(0)
                    f.write(key_data)
                    f.truncate()

            pubkey = public_file.read_text()
            owner = self.fingerprint(pubkey)

            self.key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy(public_file, self.key_dir / f'{owner}.pub')
            shutil.copy(secret_file, self.key_dir / f'{owner}.sec')
            assert os.stat(self.key_dir / f'{owner}.sec').st_mode == stat.S_IFREG | 0o600

        self.owners[owner] = pubkey
        return owner, pubkey

    def find(self, key_id: str) -> Tuple[str, str]:
        '''
        Find a key by name.

        Looks for <name>.pub file in the specified key directory.
        '''

        public_path = self.key_dir / f'{key_id}.pub'
        if not public_path.exists():
            raise SigError(f'File not found: {public_path}')

        pubkey = self.strip_key(public_path.read_text())
        owner = self.fingerprint(pubkey)
        self.owners[owner] = pubkey
        return owner, pubkey

    def copy(self: 'SignifySigContext') -> 'SignifySigContext':
        sig = SignifySigContext(self.key_dir)
        sig.owners.update(self.owners)
        return sig

    def add_pubkey(self, pubkey: str) -> str:
        owner = self.fingerprint(pubkey)
        self.owners[owner] = pubkey
        return owner

    def get_pubkey(self, owner: str) -> str:
        '''
        Get a public key by owner ID.
        '''

        if owner not in self.owners and self.use_local_keys:
            try:
                found_owner, found_pubkey = self.find(owner)
            except SigError:
                pass
            else:
                if found_owner == owner:
                    self.owners[owner] = found_pubkey

        if owner not in self.owners:
            raise SigError(f'Public key not found: {owner}')

        return self.strip_key(self.owners[owner])


    def sign(self, owner: str, data: bytes) -> str:
        '''
        Sign data using a given owner's key.
        '''
        secret_file = Path(self.key_dir / f'{owner}.sec')
        if not secret_file.exists():
            raise SigError(f'Secret key not found: {owner}')

        secret_file_text = secret_file.read_text()
        if not secret_file_text.startswith('untrusted comment:'):
            secret_file_text = 'untrusted comment: signify secret key \n' + secret_file_text + '\n'

        with tempfile.TemporaryDirectory(prefix='wlsig.') as d:
            message_file = Path(d) / 'message'
            signature_file = Path(d) / 'message.sig'
            secret_file = Path(d) / 'secret.sec'

            secret_file.write_text(secret_file_text)

            message_file.write_bytes(data)
            subprocess.run(
                [self.binary,
                 '-S',
                 '-q',  # quiet
                 '-n',  # no passphrase
                 '-s', secret_file,
                 '-x', signature_file,
                 '-m', message_file],
                check=True
            )

            signature_content = signature_file.read_text()

        signature_base64 = self.strip_key(signature_content)
        return signature_base64

    def verify(self, signature: str, data: bytes) -> str:
        '''
        Verify signature for data, returning the recognized owner.
        If self_signed, ignore that a owner is not recognized.
        '''
        signature = self.strip_key(signature)
        owner = self.fingerprint(signature)
        pubkey = self.get_pubkey(owner)

        with tempfile.TemporaryDirectory(prefix='wlsig.') as d:
            message_file = Path(d) / 'message'
            signature_file = Path(d) / 'message.sig'
            pubkey_file = Path(d) / 'key.pub'

            message_file.write_bytes(data)
            signature_file.write_text('untrusted comment: signify signature\n' + signature + '\n')
            pubkey_file.write_text('untrusted comment: signify public key\n' + pubkey + '\n')
            try:
                subprocess.run(
                    [self.binary,
                     '-V',
                     '-q',  # quiet
                     '-p', pubkey_file,
                     '-x', signature_file,
                     '-m', message_file],
                    check=True
                )
            except subprocess.CalledProcessError:
                raise SigError(f'Could not verify signature for {owner}')
        return owner
