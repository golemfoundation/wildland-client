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
Module for handling signatures. Provides two backends: libsodium/pynacl (SodiumSigContext), and a
"dummy" one.
"""

from typing import Optional, TypeVar, Dict, Tuple, List, Iterable
from pathlib import Path
import os
import base64
import stat
import logging
from hashlib import sha256

import nacl.utils
from nacl.secret import SecretBox
from nacl.signing import SigningKey, VerifyKey
from nacl.public import PrivateKey, SealedBox, PublicKey
from nacl.encoding import RawEncoder
from nacl.exceptions import BadSignatureError, CryptoError

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
    def __init__(self, key_dir: Path):
        """
        Sets up the SigContext. By default, assumes keys are files stored in a key_dir.
        """
        self.key_dir = key_dir
        self.keys: Dict[str, str] = {}
        self.private_keys: Dict[str, str] = {}
        self.key_ownership: Dict[str, List[str]] = {}
        self.use_local_keys = False

    @staticmethod
    def fingerprint(pubkey: str) -> str:
        """
        Turns a public key into owner/key id.
        :return: key_id
        """
        return '0x' + sha256(base64.b64decode(pubkey)).hexdigest()

    def recognize_local_keys(self):
        """
        Recognize local keys (i.e. ones found using find()) while loading.
        """

        self.use_local_keys = True

    def copy(self):
        """
        Create and return a copy of the current context.
        """
        sig = self.__class__(self.key_dir)
        sig.keys.update(self.keys)
        sig.private_keys.update(self.private_keys)
        sig.key_ownership.update(self.key_ownership)
        return sig

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

        key_id = self.fingerprint(pubkey)

        # save the key in key_dir; this is not dangerous because we never load all keys
        key_file = self.key_dir / f'{key_id}.pub'
        if not key_file.exists():
            key_file.write_text(pubkey)

        self.keys[key_id] = pubkey
        if owner:
            if key_id in self.key_ownership:
                if owner not in self.key_ownership[key_id]:
                    self.key_ownership[key_id].append(owner)
            else:
                self.key_ownership[key_id] = [owner]

        private_key_file = self.key_dir / f'{key_id}.sec'
        if private_key_file.exists():
            private_key = private_key_file.read_text()
            self.private_keys[key_id] = private_key

        return key_id

    def get_all_pubkeys(self, owner: str):
        """
        Get all pubkeys owned by a given owner.
        """
        return [self.keys[key_id] for key_id in self.key_ownership
                if owner in self.key_ownership[key_id]] + [self.get_primary_pubkey(owner)]

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

    def load_key(self, key_id: str) -> Tuple[str, str]:
        """
        Find a canonical form for the key.
        If the key is to be used in verification and signing, it must be added to
        SigContext with add_pubkey.
        By default, looks for <name>.pub file in the specified key directory.
        Returns a pair of (owner, pubkey).
        """
        public_path = self.key_dir / f'{key_id}.pub'
        if not public_path.exists():
            raise SigError(f'File not found: {public_path}')

        pubkey = public_path.read_text()
        owner = self.fingerprint(pubkey)
        if owner != key_id:
            logger.warning('Suspicious key fingerprint encountered; expected %s, got %s',
                           key_id, owner)
        return owner, pubkey

    def sign(self, owner: str, data: bytes, only_use_primary_key: bool = False) -> str:
        """
        Sign data using a given owner's key. If not only_use_primary_key, will use the first
        available key, if multiple are available.
        Returns signature.
        """
        raise NotImplementedError()

    def verify(self, signature: str, data: bytes, pubkey: Optional[str] = None) -> str:
        """
        Verify signature for data, returning the recognized owner.
        If self_signed, pass pubkey to verify the message integrity.
        """
        raise NotImplementedError()

    def is_valid_pubkey(self, key: str) -> bool:
        """
        Verify that given string is a valid public key
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
        pubkey_file = self.key_dir / f'{key_id}.pub'
        secret_key_file = self.key_dir / f'{key_id}.sec'

        pubkey_file.unlink(missing_ok=True)
        secret_key_file.unlink(missing_ok=True)

        if key_id in self.keys:
            del self.keys[key_id]
        if key_id in self.key_ownership:
            del self.key_ownership[key_id]

    def is_private_key_available(self, key_id: str) -> bool:
        """
        :param key_id: key id for the key to check
        :return: if private key for the given key is available
        """
        if key_id not in self.keys:
            return False

        if key_id in self.private_keys:
            return True

        return False

    def encrypt(self, data: bytes, keys: Iterable[str]) -> Tuple[str, List[str]]:
        """
        Encrypt data to be readable by keys. Returns a tuple: encrypted message,
        list of encrypted keys.
        """
        raise NotImplementedError()

    def decrypt(self, data: str, encrypted_keys: List[str]) -> bytes:
        """
        Attempt to decrypt data using all available keys.
        """
        raise NotImplementedError()


class DummySigContext(SigContext):
    """
    A SigContext that requires a dummy signature (of the form "dummy.{owner}"),
    for testing purposes.
    """

    @staticmethod
    def fingerprint(pubkey: str) -> str:
        if not pubkey.startswith('key.'):
            raise SigError('Expected key.* key, got {!r}'.format(pubkey))
        return pubkey[len('key.'):]

    def generate(self) -> Tuple[str, str]:
        num = len(self.keys) + 1
        owner = f'0x{num}{num}{num}'
        return f'{owner}', f'key.{owner}'

    def add_pubkey(self, pubkey: str, owner: str = None) -> str:
        if not pubkey.startswith('key.'):
            raise SigError('Expected key.* key, got {!r}'.format(pubkey))

        key_id = self.fingerprint(pubkey)
        self.keys[key_id] = pubkey
        if owner:
            if key_id in self.key_ownership:
                if owner not in self.key_ownership[key_id]:
                    self.key_ownership[key_id].append(owner)
            else:
                self.key_ownership[key_id] = [owner]
        self.private_keys[key_id] = pubkey
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
        return key_id in self.private_keys

    def is_valid_pubkey(self, key: str) -> bool:
        return key.startswith('key.')

    def encrypt(self, data: bytes, keys: Iterable[str]) -> Tuple[str, List[str]]:
        """
        Encrypt data to be readable by keys. Returns a tuple: encrypted message,
        list of encrypted keys.
        """
        return 'enc.' + data.decode(), ['enc.' + key for key in keys]

    def decrypt(self, data: str, encrypted_keys: List[str]) -> bytes:
        """
        Attempt to decrypt data using all available keys.
        """
        if not data.startswith('enc.') or \
                [key for key in encrypted_keys if not key.startswith('enc.')]:
            raise SigError('Cannot decrypt data')
        if not [key for key in encrypted_keys if key[4:] in self.keys.values()
                or self.use_local_keys]:
            raise SigError('Cannot decrypt data')

        return data[4:].encode()


class SodiumSigContext(SigContext):
    """
    A libsodium backend.
    """

    FINGERPRINT_LEN = 66
    PUBKEY_LEN = 32
    PRIVATE_KEY_LEN = 32
    KEY_PREFIX = b'Ed'

    def _key_to_files(self, sign_public_bytes: bytes, encr_public_bytes: bytes,
                      sign_private_bytes: bytes = None, encr_private_bytes: bytes = None) \
            -> Tuple[str, str]:
        """
        Takes key bytes and stores it in key_dir. Returns a tuple key_id, public_key
        """
        public_bytes = base64.b64encode(self.KEY_PREFIX + sign_public_bytes + encr_public_bytes)
        if sign_private_bytes and encr_private_bytes:
            private_bytes: Optional[bytes] = base64.b64encode(
                self.KEY_PREFIX + sign_public_bytes + encr_public_bytes +
                sign_private_bytes + encr_private_bytes)
        else:
            private_bytes = None

        key_id = self.fingerprint(public_bytes.decode())

        public_file = self.key_dir / f'{key_id}.pub'

        self.key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        if not public_file.exists():
            public_file.write_bytes(public_bytes)
        else:
            raise FileExistsError(f'File {public_file} already exists.')

        if private_bytes:
            private_file = self.key_dir / f'{key_id}.sec'

            if private_file.exists():
                raise FileExistsError(f'File {private_file} already exists.')

            private_file.touch(mode=stat.S_IFREG | 0o600)
            private_file.write_bytes(private_bytes)
            assert os.stat(private_file).st_mode == stat.S_IFREG | 0o600

        return key_id, public_bytes.decode()

    def _key_to_subkey(self, key: str, public: bool = True, signing: bool = True) -> bytes:
        """
        Turn a concatenated base64 key string into a key bytes. Handles private/public keys
        and signing/encryption keys.
        :param key: key string in base64
        :param public: return public key (if False, return private key)
        :param signing: return signing key (if False, return encryption key)
        :return: key bytes
        """
        key_bytes = base64.b64decode(key)
        if not key_bytes[:len(self.KEY_PREFIX)] == self.KEY_PREFIX:
            raise SigError('Incorrect key format')
        key_bytes = key_bytes[len(self.KEY_PREFIX):]

        if public:
            if not len(key_bytes) == 2 * self.PUBKEY_LEN:
                raise SigError('Incorrect key format')

            if signing:
                return key_bytes[:self.PUBKEY_LEN]
            return key_bytes[self.PUBKEY_LEN:]

        key_bytes = key_bytes[(2 * self.PUBKEY_LEN):]

        if not len(key_bytes) == 2 * self.PRIVATE_KEY_LEN:
            raise SigError('Incorrect key format')

        if signing:
            return key_bytes[:self.PRIVATE_KEY_LEN]
        return key_bytes[self.PRIVATE_KEY_LEN:]

    def _get_key(self, key_id: str, public: bool = True, signing: bool = True) -> bytes:
        """
        Takes a key_id and tries to load it, first from cache, then from disk:
        returns public or private signing or encrypting key
        """
        if public:
            key = self.keys.get(key_id, None)
        else:
            key = self.private_keys.get(key_id, None)

        if not key and self.use_local_keys:
            file = self.key_dir / f'{key_id}.pub' if public else self.key_dir / f'{key_id}.sec'
            key = file.read_text()

        if not key:
            raise FileNotFoundError

        return self._key_to_subkey(key, public=public, signing=signing)

    def generate(self) -> Tuple[str, str]:
        """
        Generate a new key set: signing key pair and encrypting key pair, and store it in key_dir.
        The keys are also loaded to the internal key database and can be used for
        verifying signatures and encryption/decryption.

        Returns a pair of (owner, concatenated signing pubkey and encrypting pubkey).
        """

        signing_key = SigningKey.generate()
        signing_private = signing_key.encode(encoder=RawEncoder)
        signing_public = signing_key.verify_key.encode(encoder=RawEncoder)

        encryption_key = PrivateKey.generate()
        encryption_private = encryption_key.encode(encoder=RawEncoder)
        encryption_public = encryption_key.public_key.encode(encoder=RawEncoder)

        return self._key_to_files(signing_public, encryption_public,
                                  signing_private, encryption_private)

    def _get_private_key(self, owner: str, signing: bool,
                         only_use_primary_key: bool = False) -> Tuple[str, bytes]:
        """
        Get first available secret key of a given user, returns a tuple of key id, private key.
        :param signing: should we retrieve the signing key
        :param owner: for which user
        :return: key id, signing or encrypting private key
        """
        if owner in self.keys:
            key_candidates = [owner]
        else:
            key_candidates = []

        if not only_use_primary_key:
            key_candidates.extend([key_id for key_id in self.key_ownership
                                   if owner in self.key_ownership[key_id]])

        for key_candidate in key_candidates:
            try:
                return key_candidate, self._get_key(key_candidate, public=False, signing=signing)
            except FileNotFoundError:
                continue

        raise SigError(f'Secret key not found: {owner}')

    def sign(self, owner: str, data: bytes, only_use_primary_key: bool = False) -> str:
        """
        Sign data using a given owner's key. If not only_use_primary_key, will use the first
        available key, if multiple are available.
        Returns signature.
        """
        assert len(owner) == self.FINGERPRINT_LEN

        key_id, secret_key = self._get_private_key(
            owner, signing=True, only_use_primary_key=only_use_primary_key)

        secret_key_loaded = SigningKey(secret_key, encoder=RawEncoder)

        signature = secret_key_loaded.sign(data, encoder=RawEncoder)

        return key_id + ':' + base64.b64encode(signature.signature).decode()

    def verify(self, signature: str, data: bytes, pubkey: Optional[str] = None) -> str:
        """
        Verify signature for data, along with pubkey returning the recognized owner.
        """
        if len(signature) == 100:
            raise SigError(
                'Old key format detected. Please create new encryption and signing keys '
                'using the new format.')

        try:
            signer, signature = signature.split(':', 1)
        except ValueError as ve:
            raise SigError('Incorrect signature format.') from ve

        signature_bytes = base64.b64decode(signature)

        if not pubkey:
            pubkey = self.get_primary_pubkey(signer)

        pubkey_bytes = self._key_to_subkey(pubkey, public=True, signing=True)

        verify_key = VerifyKey(pubkey_bytes, encoder=RawEncoder)

        try:
            verify_key.verify(data, signature_bytes, encoder=RawEncoder)
            return self.fingerprint(pubkey)
        except BadSignatureError as bse:
            raise SigError(f'Could not verify signature for {signer}') from bse

    def is_valid_pubkey(self, key: str) -> bool:
        try:
            key_bytes = self._key_to_subkey(key, public=True, signing=False)
            PublicKey(key_bytes, encoder=RawEncoder)

            return True
        except Exception:
            return False

    def encrypt(self, data: bytes, keys: Iterable[str]) -> Tuple[str, List[str]]:
        private_key = nacl.utils.random(SecretBox.KEY_SIZE)
        secret_box = SecretBox(private_key)

        encrypted_message = base64.b64encode(secret_box.encrypt(data)).decode()

        encrypted_keys = []

        for key in keys:
            key_bytes = self._key_to_subkey(key, public=True, signing=False)
            box = SealedBox(PublicKey(key_bytes, encoder=RawEncoder))
            encrypted_keys.append(base64.b64encode(box.encrypt(private_key)).decode())

        return encrypted_message, encrypted_keys

    def decrypt(self, data: str, encrypted_keys: List[str]) -> bytes:
        decryption_key = None

        for key in self.private_keys.values():
            private_key = self._key_to_subkey(key, public=False, signing=False)

            box = SealedBox(PrivateKey(private_key, encoder=RawEncoder))

            for encrypted_key in encrypted_keys:
                try:
                    decryption_key = box.decrypt(base64.b64decode(encrypted_key))
                    break
                except CryptoError:
                    pass
            if decryption_key:
                break

        if not decryption_key:
            raise SigError('Failed to find decryption key')

        box = SecretBox(decryption_key)
        try:
            return box.decrypt(base64.b64decode(data))
        except CryptoError as ce:
            raise SigError('Failed to decrypt data')from ce
