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
    A class for signing and verifying signatures. Operates on 'signer'
    identifiers, serving as key fingerprints.
    '''

    def copy(self: T) -> T:
        '''
        Create a copy of the current context.
        '''
        raise NotImplementedError()

    def generate(self) -> Tuple[str, str]:
        '''
        Generate a new key pair and store it.

        Returns a pair of (signer, pubkey).
        '''
        raise NotImplementedError()

    def add_pubkey(self, pubkey: str) -> str:
        '''
        Add a public key to recognized signers. Returns a signer ID.
        '''
        raise NotImplementedError()

    def get_pubkey(self, signer: str) -> str:
        '''
        Get a public key by signer ID.
        '''
        raise NotImplementedError()

    def find(self, key_id: str) -> Tuple[str, str]:
        '''
        Find a canonical form for the key.

        Returns a pair of (signer, pubkey).
        '''
        raise NotImplementedError()

    def sign(self, signer: str, data: bytes) -> str:
        '''
        Sign data using a given signer's key.
        '''
        raise NotImplementedError()

    def verify(self, signature: str, data: bytes) -> str:
        '''
        Verify signature for data, returning the recognized signer.
        If self_signed, ignore that a signer is not recognized.
        '''
        raise NotImplementedError()


class DummySigContext(SigContext):
    '''
    A SigContext that requires a dummy signature (of the form "dummy.{signer}"),
    for testing purposes.
    '''

    def __init__(self):
        self.signers = set()

    def copy(self) -> 'DummySigContext':
        copied = DummySigContext()
        copied.signers = self.signers.copy()
        return copied

    def generate(self) -> Tuple[str, str]:
        return '0xfff', 'key.0xfff'

    def add_pubkey(self, pubkey: str) -> str:
        if not pubkey.startswith('key.'):
            raise SigError('Expected key.* key, got {!r}'.format(pubkey))

        signer = pubkey[len('key.'):]
        self.signers.add(signer)
        return signer

    def get_pubkey(self, signer: str) -> str:
        return f'key.{signer}'

    def find(self, key_id: str) -> Tuple[str, str]:
        return key_id, f'key.{key_id}'

    def sign(self, signer: str, data: bytes) -> str:
        return f'dummy.{signer}'

    def verify(self, signature: str, data: bytes) -> str:
        if not signature.startswith('dummy.'):
            raise SigError(
                'Expected dummy.* signature, got {!r}'.format(signature))

        signer = signature[len('dummy.'):]
        if signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))
        return signer



class SignifySigContext(SigContext):
    '''
    A Signify backend.

    The key_dir directory is for storing generated key pairs.
    '''

    def __init__(self, key_dir: Path):
        self.key_dir = key_dir
        self.binary: str = self._find_binary()
        self.signers: Dict[str, str] = {}

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
        Convert Signify pubkey to a signer identifier (fingerprint).
        '''
        pubkey_data = pubkey.splitlines()[1]
        data = base64.b64decode(pubkey_data)
        prefix = data[:10][::-1]
        return '0x' + binascii.hexlify(prefix).decode()

    def generate(self) -> Tuple[str, str]:
        '''
        Generate a new key pair and store it in key_dir.

        Returns a pair of (signer, pubkey).
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

            pubkey = public_file.read_text()
            signer = self.fingerprint(pubkey)

            self.key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy(public_file, self.key_dir / f'{signer}.pub')
            shutil.copy(secret_file, self.key_dir / f'{signer}.sec')
            assert os.stat(self.key_dir / f'{signer}.sec').st_mode == stat.S_IFREG | 0o600

        self.signers[signer] = pubkey
        return signer, pubkey

    def find(self, key_id: str) -> Tuple[str, str]:
        '''
        Find a key by name.

        Looks for <name>.pub and <name>.sec files in the specified key
        directory.
        '''

        public_path = self.key_dir / f'{key_id}.pub'
        secret_path = self.key_dir / f'{key_id}.sec'
        if not public_path.exists():
            raise SigError(f'File not found: {public_path}')
        if not secret_path.exists():
            raise SigError(f'File not found: {secret_path}')

        pubkey = public_path.read_text()
        signer = self.fingerprint(pubkey)
        self.signers[signer] = pubkey
        return signer, pubkey

    def copy(self: 'SignifySigContext') -> 'SignifySigContext':
        sig = SignifySigContext(self.key_dir)
        sig.signers.update(self.signers)
        return sig

    def add_pubkey(self, pubkey: str) -> str:
        signer = self.fingerprint(pubkey)
        self.signers[signer] = pubkey
        return signer

    def get_pubkey(self, signer: str) -> str:
        '''
        Get a public key by signer ID.
        '''
        try:
            return self.signers[signer]
        except KeyError:
            raise SigError(f'Public key not found: {signer}')

    def sign(self, signer: str, data: bytes) -> str:
        '''
        Sign data using a given signer's key.
        '''
        secret_file = Path(self.key_dir / f'{signer}.sec')
        if not secret_file.exists():
            raise SigError(f'Secret key not found: {signer}')

        with tempfile.TemporaryDirectory(prefix='wlsig.') as d:
            message_file = Path(d) / 'message'
            signature_file = Path(d) / 'message.sig'

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

        signature_base64 = signature_content.splitlines()[1]
        return f'untrusted comment: signify signature\n' + signature_base64

    def verify(self, signature: str, data: bytes) -> str:
        '''
        Verify signature for data, returning the recognized signer.
        If self_signed, ignore that a signer is not recognized.
        '''
        signer = self.fingerprint(signature)
        if signer not in self.signers:
            raise SigError(f'Unrecognized signer: {signer}')

        pubkey = self.signers[signer]
        with tempfile.TemporaryDirectory(prefix='wlsig.') as d:
            message_file = Path(d) / 'message'
            signature_file = Path(d) / 'message.sig'
            pubkey_file = Path(d) / 'key.pub'

            message_file.write_bytes(data)
            signature_file.write_text(signature + '\n')
            pubkey_file.write_text(pubkey + '\n')
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
                raise SigError(f'Could not verify signature for {signer}')
        return signer
