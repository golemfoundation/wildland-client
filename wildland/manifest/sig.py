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
Module for handling signatures. Currently provides two backends: GPG, and a
"dummy" one.
'''

import tempfile
import shutil
from typing import TypeVar, Tuple, Optional
import os

import gnupg

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

    Should be closed before exiting, so it's best to use it as a file-like
    object:

        with ...SigContext() as sig:
            ...
    '''

    def close(self):
        '''Clean up.'''

    def __enter__(self: T) -> T:
        return self

    def __exit__(self, *args):
        self.close()

    def copy(self: T) -> T:
        '''
        Create a copy of the current context.
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

    # For pylint to correctly infer the type.
    def __enter__(self: T) -> T:
        return self

    def copy(self) -> 'DummySigContext':
        copied = DummySigContext()
        copied.signers = self.signers.copy()
        return copied

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


class GpgSigContext(SigContext):
    '''
    GnuPG wrapper, using python-gnupg library:

    https://gnupg.readthedocs.io/en/latest/

    Uses keys stored in GnuPG keyring, but also allows you to add other keys.
    '''

    def __init__(self, gnupghome=None):
        super().__init__()
        self.gnupghome = gnupghome
        self.keyring_file = tempfile.NamedTemporaryFile(prefix='wlgpg.')
        self.gpg = gnupg.GPG(gnupghome=gnupghome,
                             keyring=self.keyring_file.name)
        self.signers = set()

    # For pylint to correctly infer the type.
    def __enter__(self: T) -> T:
        return self

    def close(self):
        if os.path.exists(self.keyring_file.name):
            self.keyring_file.close()
        # GPG backup
        if os.path.exists(self.keyring_file.name + '~'):
            os.unlink(self.keyring_file.name + '~')

    @staticmethod
    def convert_fingerprint(fingerprint):
        '''
        Convert GPG fingerprint to an unambiguous '0xcoffee' format.
        '''
        fingerprint = fingerprint.lower()
        if not fingerprint.startswith('0x'):
            fingerprint = '0x' + fingerprint
        return fingerprint

    def copy(self) -> 'GpgSigContext':
        copied = GpgSigContext()
        copied.signers = self.signers.copy()
        shutil.copyfile(self.keyring_file.name, copied.keyring_file.name)
        return copied

    def add_pubkey(self, pubkey: str) -> str:
        result = self.gpg.import_keys(pubkey)
        if len(result.fingerprints) > 1:
            raise SigError('More than one public key found')
        if len(result.fingerprints) == 0:
            raise SigError('Error importing public key')
        signer = self.convert_fingerprint(result.fingerprints[0])
        self.signers.add(signer)
        return signer

    def get_pubkey(self, signer: str) -> str:
        return self.gpg.export_keys([signer])

    def find(self, key_id: str) -> Tuple[str, str]:
        # Search both in local keyring and in gnupghome.

        result = (
            self._find(key_id, self.gpg) or
            self._find(key_id, gnupg.GPG(gnupghome=self.gnupghome))
        )
        if result is None:
            raise SigError('No key found for {}'.format(key_id))
        return result

    def _find(self, key_id, gpg) -> Optional[Tuple[str, str]]:
        keys = [self.convert_fingerprint(k['fingerprint'])
                for k in gpg.list_keys(keys=key_id)]
        if len(keys) > 1:
            raise SigError('Multiple keys found for {}: {}'.format(
                key_id, keys))
        if len(keys) == 0:
            return None
        return keys[0], gpg.export_keys(keys)

    def gen_test_key(self, name, passphrase: str = None) -> str:
        '''
        Generate a new key for testing purposes.
        '''

        input_data = self.gpg.gen_key_input(
            name_real=name,
            key_length=1024,
            subkey_length=1024,
            passphrase=passphrase)
        key = self.gpg.gen_key(input_data)
        if not key:
            raise Exception('gen_key failed')
        signer = self.convert_fingerprint(key.fingerprint)
        self.signers.add(signer)
        return signer

    def verify(self, signature: str, data: bytes) -> str:
        # Create a file for detached signature, because gnupg needs to get it
        # from file. NamedTemporaryFile() creates the file as 0o600, so no need
        # to set umask.
        with tempfile.NamedTemporaryFile(mode='w', prefix='wlsig.') as sig_file:
            sig_file.write(signature)
            sig_file.flush()

            verified = self.gpg.verify_data(
                sig_file.name, data)

        if not data:
            raise Exception('verify failed')

        if not verified.valid:
            raise SigError('Could not verify signature')

        signer = self.convert_fingerprint(verified.fingerprint)

        if signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))

        return signer

    def sign(self, signer: str, data: bytes, passphrase: str = None) -> str:
        # pylint: disable=arguments-differ

        if signer not in self.signers:
            raise SigError('Unknown signer: {!r}'.format(signer))

        signature = self.gpg.sign(data, keyid=signer, detach=True,
                                  passphrase=passphrase)
        if not signature:
            raise Exception('sign failed')
        return str(signature)
