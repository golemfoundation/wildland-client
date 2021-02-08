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
Module for handling signatures. Provides two backends: Signify, and a
"dummy" one.
"""

import tempfile
import shutil
from typing import Optional, TypeVar, Dict, Tuple, List
from pathlib import Path
import os
import subprocess
import base64
import binascii
import stat
import logging

from ..exc import WildlandError

logger = logging.getLogger('sig')

class SigError(WildlandError):
    """
    Exception class for problems during the signing or verification process.
    """


T = TypeVar('T')


class SigContext:
    """
    A class for signing and verifying signatures. Operates on 'owner'
    identifiers, serving as key fingerprints.
    """

    def __init__(self):
        self.keys: Dict[str, str] = {}
        self.key_ownership: Dict[str, List[str]] = {}
        self.use_local_keys = False

    def recognize_local_keys(self):
        """
        Recognize local keys (i.e. ones found using find()) while loading.
        """

        self.use_local_keys = True

    def copy(self: T) -> T:
        """
        Create a copy of the current context.
        """
        raise NotImplementedError()

    def generate(self) -> Tuple[str, str]:
        """
        Generate a new key pair and store it.

        Returns a pair of (owner, pubkey).
        """
        raise NotImplementedError()

    def add_pubkey(self, pubkey: str, owner: str = None) -> str:
        """
        Add a public key to recognized keys. Optionally, can associate key with an
        owner (by default, a key is owned by itself).
        pubkey should be the actual public key, not its hash.
        Returns a key signer ID.
        """
        raise NotImplementedError()

    def get_primary_pubkey(self, owner: str) -> str:
        """
        Get owner's primary/own pubkey.
        """
        raise NotImplementedError()

    def load_key(self, key_id: str) -> Tuple[str, str]:
        """
        Find a canonical form for the key.
        If the key is to be used in verification and signing, it must be added to
        SigContext with add_pubkey.

        Returns a pair of (owner, pubkey).
        """
        raise NotImplementedError()

    def sign(self, owner: str, data: bytes, only_use_primary_key: bool = False) -> str:
        """
        Sign data using a given owner's key. If not only_use_primary_key, will use the first
        available key, if multiple are available.
        Returns owner.
        """
        raise NotImplementedError()

    def verify(self, signature: str, data: bytes, pubkey: Optional[str] = None) -> str:
        """
        Verify signature for data, returning the recognized owner.
        If self_signed, pass pubkey to verify the message integrity.
        """
        raise NotImplementedError()

    def get_possible_owners(self, signer: str) -> List[str]:
        """
        List key_ids that can be owners of the provided key_id.
        """
        owners = [signer]
        if signer in self.key_ownership:
            owners.extend(self.key_ownership[signer])
        return owners

    def remove_key(self, key_id):
        """
        Remove a given key (and a matching private key) from disk and from local context.
        """
        raise NotImplementedError

    def is_private_key_available(self, key_id):
        """
        :param key_id: key id for the key to check
        :type key_id: str
        :return: if private key for the given key is available
        :rtype: bool
        """
        raise NotImplementedError


class DummySigContext(SigContext):
    """
    A SigContext that requires a dummy signature (of the form "dummy.{owner}"),
    for testing purposes.
    """

    def copy(self) -> 'DummySigContext':
        copied = DummySigContext()
        copied.keys = self.keys.copy()
        copied.key_ownership = self.key_ownership.copy()
        return copied

    def generate(self) -> Tuple[str, str]:
        num = len(self.keys) + 1
        owner = f'0x{num}{num}{num}'
        return f'{owner}', f'key.{owner}'

    def add_pubkey(self, pubkey: str, owner: str = None) -> str:
        if not pubkey.startswith('key.'):
            raise SigError('Expected key.* key, got {!r}'.format(pubkey))

        key_id = pubkey[len('key.'):]
        self.keys[key_id] = pubkey
        if owner:
            if key_id in self.key_ownership:
                if owner not in self.key_ownership[key_id]:
                    self.key_ownership[key_id].append(owner)
            else:
                self.key_ownership[key_id] = [owner]
        return key_id

    def get_primary_pubkey(self, owner: str) -> str:
        return self.keys[owner]

    def load_key(self, key_id: str) -> Tuple[str, str]:
        return key_id, f'key.{key_id}'

    def sign(self, owner: str, data: bytes, only_use_primary_key: bool = False) -> str:
        return f'dummy.{owner}'

    def verify(self, signature: str, data: bytes, pubkey: Optional[str] = None) -> str:
        if not signature.startswith('dummy.'):
            raise SigError(
                'Expected dummy.* signature, got {!r}'.format(signature))

        signer = signature[len('dummy.'):]
        if pubkey:
            if pubkey != 'key.' + signer:
                raise SigError('Incorrect signature: {!r}'.format(signer))
        elif not (signer in self.keys or self.use_local_keys):
            raise SigError('Unknown owner: {!r}'.format(signer))
        return signer

    def remove_key(self, key_id):
        if key_id in self.keys:
            del self.keys[key_id]
        if key_id in self.key_ownership:
            del self.key_ownership[key_id]

    def is_private_key_available(self, key_id):
        if key_id not in self.keys:
            return False
        return True

    @staticmethod
    def _fingerprint(pubkey: str) -> str:
        return pubkey.replace('key.', '')

class SignifySigContext(SigContext):
    """
    A Signify backend.

    The key_dir directory is for storing generated key pairs.
    """

    def __init__(self, key_dir: Path):
        super().__init__()
        self.key_dir = key_dir
        self.binary: str = self._find_binary()

    @staticmethod
    def _find_binary():
        for name in ['signify-openbsd', 'signify']:
            binary = shutil.which(name)
            if binary is not None:
                return binary
        raise WildlandError('signify binary not found, please install signify-openbsd')

    @staticmethod
    def _fingerprint(pubkey: str) -> str:
        """
        Convert Signify pubkey to a owner identifier (fingerprint). Raises binascii.Error
        if failed to parse key data.
        """
        # # strip unneeded syntactic sugar and empty lines
        pubkey_data = SignifySigContext._strip_key(pubkey)

        data = base64.b64decode(pubkey_data)
        prefix = data[:10][::-1]
        return '0x' + binascii.hexlify(prefix).decode()

    @staticmethod
    def _strip_key(key: str) -> str:
        """
        Strips empty lines and comments from a Signify-generated key
        """
        return [line for line in key.splitlines() if line
                and not line.startswith('untrusted comment')][0]

    def generate(self) -> Tuple[str, str]:
        """
        Generate a new key pair and store it in key_dir.
        The key is also loaded to the internal key database and can be used for
        verifying signatures.

        Returns a pair of (owner, pubkey).
        """

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
                key_data = self._strip_key(key)
                with file.open(mode='w') as f:
                    f.seek(0)
                    f.write(key_data)
                    f.truncate()

            pubkey = public_file.read_text()
            owner = self._fingerprint(pubkey)

            self.key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy(public_file, self.key_dir / f'{owner}.pub')
            shutil.copy(secret_file, self.key_dir / f'{owner}.sec')
            assert os.stat(self.key_dir / f'{owner}.sec').st_mode == stat.S_IFREG | 0o600

        self.keys[owner] = pubkey
        return owner, pubkey

    def load_key(self, key_id: str) -> Tuple[str, str]:
        """
        Loads the key from disk. Does NOT add the key to the internal key list; must
        be added manually if so desired.

        Looks for <name>.pub file in the specified key directory.
        """

        public_path = self.key_dir / f'{key_id}.pub'
        if not public_path.exists():
            raise SigError(f'File not found: {public_path}')

        pubkey = self._strip_key(public_path.read_text())
        owner = self._fingerprint(pubkey)
        return owner, pubkey

    def copy(self: 'SignifySigContext') -> 'SignifySigContext':
        sig = SignifySigContext(self.key_dir)
        sig.keys.update(self.keys)
        sig.key_ownership.update(self.key_ownership)
        return sig

    def add_pubkey(self, pubkey: str, owner: str = None) -> str:
        key_id = self._fingerprint(pubkey)

        # save the key in key_dir; this is not dangerous because we never load all keys
        key_file = self.key_dir / f'{key_id}.pub'
        if not key_file.exists():
            key_file.write_text(pubkey)

        self.keys[key_id] = self._strip_key(pubkey)
        if owner:
            if key_id in self.key_ownership:
                if owner not in self.key_ownership[key_id]:
                    self.key_ownership[key_id].append(owner)
            else:
                self.key_ownership[key_id] = [owner]
        return key_id

    def get_primary_pubkey(self, owner: str) -> str:
        """
        Get owner's primary/own pubkey.
        """

        found_pubkey = None

        if owner in self.keys:
            found_pubkey = self.keys[owner]
        elif self.use_local_keys:
            try:
                _, found_pubkey = self.load_key(owner)
            except SigError:
                pass

        if not found_pubkey:
            raise SigError(f'Public key not found: {owner}')

        return found_pubkey

    def sign(self, owner: str, data: bytes, only_use_primary_key: bool = False) -> str:
        """
        Sign data using a given owner's key. If not only_use_primary_key, will use the first
        available key, if multiple are available.
        Returns owner.
        """

        key_candidates = [owner]

        if not only_use_primary_key:
            key_candidates.extend([key_id for key_id in self.key_ownership
                                   if owner in self.key_ownership[key_id]])

        secret_file = None

        for key_candidate in key_candidates:
            secret_file_candidate = Path(self.key_dir / f'{key_candidate}.sec')
            if secret_file_candidate.exists():
                secret_file = secret_file_candidate
                break

        if not secret_file:
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

        signature_base64 = self._strip_key(signature_content)

        return signature_base64

    def verify(self, signature: str, data: bytes, pubkey: Optional[str] = None) -> str:
        """
        Verify signature for data, along with pubkey returning the recognized owner.
        """
        signature = self._strip_key(signature)
        signer = self._fingerprint(signature)

        if not pubkey:
            pubkey = self.get_primary_pubkey(signer)

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
            except subprocess.CalledProcessError as cpe:
                raise SigError(f'Could not verify signature for {signer}') from cpe
        return signer

    def remove_key(self, key_id):
        pubkey_file = self.key_dir / f'{key_id}.pub'
        secret_key_file = self.key_dir / f'{key_id}.sec'

        pubkey_file.unlink(missing_ok=True)
        secret_key_file.unlink(missing_ok=True)

        if key_id in self.keys:
            del self.keys[key_id]
        if key_id in self.key_ownership:
            del self.key_ownership[key_id]

    def is_private_key_available(self, key_id):
        if key_id not in self.keys:
            return False

        secret_key_file = self.key_dir / f'{key_id}.sec'
        return secret_key_file.exists()
