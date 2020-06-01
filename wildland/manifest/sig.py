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
from typing import TypeVar, Tuple, Optional, Dict
from pathlib import Path
import os
import subprocess
import base64
import binascii
import stat

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


class SignifySigContext(SigContext):
    '''
    A Signify backend.

    The key_dir directory is for storing generated key pairs.
    '''

    def __init__(self, key_dir: Path):
        self.key_dir = key_dir
        self.binary: str = 'signify'
        self.signers: Dict[str, str] = {}

    @staticmethod
    def fingerprint(pubkey: str) -> str:
        '''
        Convert Signify pubkey to a signer identifier (fingerprint).
        '''
        pubkey_data = pubkey.splitlines()[1]
        data = base64.b64decode(pubkey_data)
        prefix = data[:10][::-1]
        return '0x' + binascii.hexlify(prefix).decode()

    def generate(self) -> str:
        '''
        Generate a new key pair and store it in key_dir.

        Returns signer.
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

            shutil.copy(public_file, self.key_dir / f'{signer}.pub')
            shutil.copy(secret_file, self.key_dir / f'{signer}.sec')
            assert os.stat(self.key_dir / f'{signer}.sec').st_mode == stat.S_IFREG | 0o600

        self.signers[signer] = pubkey
        return signer

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

    def find(self, key_id: str) -> Tuple[str, str]:
        raise NotImplementedError()

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
