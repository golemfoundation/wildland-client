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
Classes for handling signed Wildland manifests
"""

from typing import Tuple, Optional, Dict
import re
import logging
from pathlib import Path

import yaml

from .schema import Schema
from .sig import SigContext, SigError
from ..utils import load_yaml
from ..exc import WildlandError


logger = logging.getLogger('manifest')

HEADER_SEPARATOR = b'\n---\n'
HEADER_SEPARATOR_EMPTY = b'---\n'


class ManifestError(WildlandError):
    """
    Exception class for problems during manifest loading or construction.
    """


class Manifest:
    """
    Represents a loaded manifest.

    The data (fields) should not be modified, because it needs to match the
    return signature.
    """
    CURRENT_VERSION = '1'  # update also in schemas/types.json

    def __init__(self, header: Optional['Header'], fields: dict,
                 original_data: Optional[bytes], local_path: Optional[Path] = None):

        # If header is set, that means we have verified the signature,
        # or explicitly accepted an unsigned manifest.
        self.header = header

        self.local_path = local_path

        # Accessible as 'fields' only if there is a header.
        self._fields = fields

        self.owner = fields.get('owner', None)

        # Original data that has been signed.
        self._original_data = original_data

    @property
    def original_data(self):
        """
        Return manifest's bytes data.
        """
        if not self._original_data:
            self._original_data = yaml.dump(self._fields, encoding='utf-8', sort_keys=False)
        return self._original_data

    def copy_to_unsigned(self) -> 'Manifest':
        """
        Make an unsigned deep copy of this manifest. Useful for skipping signing, validation
        and similar potentially destructive changes.
        """
        manifest = self.__class__.from_unsigned_bytes(
            yaml.dump(self._fields, encoding='utf-8', sort_keys=False))
        return manifest

    @property
    def fields(self):
        """
        A wrapper for manifest fields that makes sure the manifest is signed.
        """

        if not self.header:
            raise ManifestError('Trying to read an unsigned manifest')
        return self._fields

    @classmethod
    def encrypt(cls, fields: dict, sig: SigContext, owner: Optional[str] = None) -> dict:
        """
        Encrypt provided dict with the SigContext.
        Encrypts to 'owner' keys, unless 'access' field specifies otherwise.
        Inline storages may have their own access fields.
        Returns encrypted dict.
        """
        if not owner:
            owner = fields.get('owner', None)
            if not owner:
                raise ManifestError('Owner not found')

        for key, value in fields.items():
            fields[key] = cls._encrypt_submanifests(value, sig, owner)

        if fields.get('object', None) in ['user', 'bridge']:
            return fields

        return cls._encrypt_dict(fields, sig, owner)

    @classmethod
    def _encrypt_dict(cls, fields: dict, sig: SigContext, owner: str) -> dict:
        keys_to_encrypt = sig.get_all_pubkeys(owner)
        if 'access' in fields.keys():
            for data_dict in fields['access']:
                user = data_dict['user']
                if user == '*':
                    return fields
                if user == owner:
                    continue
                pubkeys = sig.get_all_pubkeys(user)
                if not pubkeys:
                    raise ManifestError(f'Cannot encrypt to {user}.')
                keys_to_encrypt.extend(pubkeys)

        keys_to_encrypt = set(keys_to_encrypt)
        data_to_encrypt = yaml.dump(fields, sort_keys=False).encode()
        try:
            encrypted_data, encrypted_keys = sig.encrypt(data_to_encrypt, keys_to_encrypt)
        except SigError as se:
            raise ManifestError('Cannot encrypt manifest.') from se
        return {'encrypted': {'encrypted-data': encrypted_data, 'encrypted-keys': encrypted_keys}}

    @classmethod
    def _encrypt_submanifests(cls, object_, sig, owner):
        """
        Encrypt all encountered submanifests.
        """
        if isinstance(object_, dict):
            for key, value in object_.items():
                object_[key] = cls._encrypt_submanifests(value, sig, owner)
            if 'access' in object_:
                return cls._encrypt_dict(object_, sig, owner)
            return object_

        if isinstance(object_, list):
            for idx, obj_ in enumerate(object_):
                object_[idx] = cls._encrypt_submanifests(obj_, sig, owner)

        return object_

    @classmethod
    def decrypt(cls, fields: dict, sig: SigContext) -> dict:
        """
        Decrypt provided dict within provided SigContext.
        Assumes encrypted (sub) dict contains an 'encrypted' fields that contains a dict
        with two fields: 'encrypted-data' and 'encrypted-keys'.
        Returns decrypted dict.
        """

        decrypted_fields = cls._decrypt_dict(fields, sig)
        for key, value in decrypted_fields.items():
            decrypted_fields[key] = cls._decrypt_submanifests(value, sig)
        return decrypted_fields

    @classmethod
    def _decrypt_dict(cls, fields: dict, sig: SigContext) -> dict:
        """
        Decrypt a dict.
        """
        if list(fields.keys()) == ['encrypted']:
            encrypted_dict = fields['encrypted']

            if not isinstance(encrypted_dict, dict) or \
                    sorted(encrypted_dict.keys()) != ['encrypted-data', 'encrypted-keys']:
                raise ManifestError('Encrypted field malformed.')
            try:
                decrypted_raw = sig.decrypt(encrypted_dict['encrypted-data'],
                                            encrypted_dict['encrypted-keys'])
            except SigError as se:
                raise ManifestError('Cannot decrypt manifest.') from se

            fields = yaml.safe_load(decrypted_raw)

        return fields

    @classmethod
    def _decrypt_submanifests(cls, object_, sig):
        """
        Decrypt and replace as needed all submanifests inside the given dict.
        """
        if isinstance(object_, dict):
            try:
                object_ = cls._decrypt_dict(object_, sig)
            except ManifestError:
                return object_
            for key, value in object_.items():
                try:
                    object_[key] = cls._decrypt_submanifests(value, sig)
                except ManifestError:
                    continue

        if isinstance(object_, list):
            for idx, obj_ in enumerate(object_):
                try:
                    object_[idx] = cls._decrypt_submanifests(obj_, sig)
                except ManifestError:
                    continue

        return object_

    @classmethod
    def update_manifest_version(cls, fields: dict) -> dict:
        """
        Update manifest version, if an old version is encountered.
        Currently able to update from un-versioned to version 1.
        """
        if not isinstance(fields, dict):
            raise TypeError(f'expected dict, got {type(fields)} instance')

        if "version" not in fields:
            # Un-versioned manifest
            fields = cls.update_to_version_1(fields, True)

        # Obsolete names from v1
        fields = cls.update_obsolete(fields)

        return fields

    @classmethod
    def update_obsolete(cls, fields: dict):
        """
        Update fields obsolete in V1.
        """
        if fields.get('type', None) == 'http-index':
            fields['type'] = 'http'

        if fields.get('subcontainers', None):
            if 'manifest-pattern' in fields:
                raise ManifestError('Obsolete subcontainers field cannot be '
                                    'merged into an existing manifest-patter.')
            fields['manifest-pattern'] = {
                'type': 'list',
                'paths': fields['subcontainers']
            }
            del fields['subcontainers']

        if 'infrastructures' in fields:
            fields['manifests-catalog'] = fields['infrastructures']
            del fields['infrastructures']

        if 'backends' in fields and 'storage' in fields['backends']:
            for storage in fields['backends']['storage']:
                if isinstance(storage, dict):
                    cls.update_obsolete(storage)
        if 'manifests-catalog' in fields:
            for container in fields['manifests-catalog']:
                if isinstance(container, dict):
                    cls.update_obsolete(container)

        return fields

    @classmethod
    def update_to_version_1(cls, fields: dict, add_version: bool = True) -> dict:
        """
        Update any obsolete fields, bringing manifest up to v1. Currently handles:
          - signer --> owner
          - inner-container --> reference-container
          - in local storages, path --> location
        """
        if 'owner' not in fields:
            if 'signer' in fields:
                fields['owner'] = fields['signer']
                del fields['signer']

        if 'inner-container' in fields:
            fields['reference-container'] = fields['inner-container']
            del fields['inner-container']

        if 'object' not in fields:
            if 'user' in fields:
                fields['object'] = 'bridge'
            elif 'backends' in fields:
                fields['object'] = 'container'
            elif 'type' in fields:
                fields['object'] = 'storage'
            elif 'pubkeys' in fields:
                fields['object'] = 'user'
            else:
                raise ManifestError(
                    "no 'object' field and could not guess manifest type")

        # Nested manifests too
        if 'backends' in fields and 'storage' in fields['backends']:
            for storage in fields['backends']['storage']:
                if isinstance(storage, dict) and list(storage.keys()) != ['encrypted']:
                    cls.update_to_version_1(storage, add_version=False)
        if 'infrastructures' in fields:
            for container in fields['infrastructures']:
                if isinstance(container, dict) and container.get('object', None) == 'container':
                    if container.get('version', None):
                        raise ManifestError('Manifest version mismatch: expected no manifest'
                                            'version in infrastructure container.')
                    cls.update_to_version_1(container, add_version=True)
        if fields.get('type', None) in ['local', 'local-cached', 'local-dir-cached'] and \
                'path' in fields:
            fields['location'] = fields['path']
            del fields['path']

        if add_version:
            fields['version'] = '1'

        return fields

    @classmethod
    def from_fields(cls, fields: dict, sig: SigContext = None,
                    local_path: Optional[Path] = None) -> 'Manifest':
        """
        Create a manifest based on a dict of fields.

        Has to be signed separately, but is assumed to be verified for the purpose of accessing
        data.
        """
        if sig:
            fields = cls.decrypt(fields, sig)
        fields = cls.update_manifest_version(fields)
        return cls(Header(None), fields, None, local_path=local_path)

    @classmethod
    def from_unsigned_bytes(cls, data: bytes, sig: SigContext = None,
                            local_path: Optional[Path] = None) -> 'Manifest':
        """
        Create a new Manifest based on existing YAML-serialized
        content. The content can include an existing header, it will be ignored.

        Has to be signed separately.
        """

        if HEADER_SEPARATOR in data or data.startswith(HEADER_SEPARATOR_EMPTY):
            _, data = split_header(data)

        rest_str = data.decode('utf-8')
        try:
            fields = load_yaml(rest_str)
        except yaml.YAMLError as e:
            raise ManifestError('Manifest parse error: {}'.format(e)) from e
        if sig:
            fields = cls.decrypt(fields, sig)
        fields = cls.update_manifest_version(fields)
        return cls(None, fields, data, local_path=local_path)

    def encrypt_and_sign(self, sig_context: SigContext, only_use_primary_key: bool = False,
                         encrypt=True):
        """
        Sign a manifest. If signed, will replace signature.
        If attach_pubkey is true, attach the public key to the signature.
        Can force not encrypting, if needed.
        """

        if self.header is not None:
            self.header = None

        fields = self._fields
        data = self.original_data

        if encrypt:
            fields = Manifest.encrypt(fields, sig_context)
            data = yaml.dump(fields, encoding='utf-8', sort_keys=False)

        owner = self._fields['owner']
        signature = sig_context.sign(owner, data,
                                     only_use_primary_key=only_use_primary_key)

        self._original_data = data
        self._fields = fields
        self.header = Header(signature)

    def skip_verification(self):
        """
        Explicitly mark the manifest as unsigned, and allow using it.
        """

        self.header = Header(None)

    @classmethod
    def from_file(cls, path, sig_context: SigContext,
                  schema: Optional[Schema] = None,
                  trusted_owner: Optional[str] = None) -> 'Manifest':
        """
        Load a manifest from YAML file, verifying it.

        Args:
            path: path to YAML file
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            trusted_owner: accept signature-less manifest from this owner
        """

        with open(path, 'rb') as f:
            data = f.read()
        return cls.from_bytes(
            data, sig_context, schema, trusted_owner, local_path=path)

    @classmethod
    def from_bytes(cls, data: bytes, sig_context: SigContext,
                   schema: Optional[Schema] = None,
                   trusted_owner: Optional[str] = None,
                   allow_only_primary_key: bool = False,
                   decrypt: bool = True,
                   local_path: Optional[Path] = None) -> 'Manifest':
        """
        Load a manifest from YAML content, verifying it.

        Args:
            data: existing manifest content
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            trusted_owner: accept signature-less manifest from this owner
            allow_only_primary_key: can this manifest be signed by any auxiliary keys
                associated with the given user?
            decrypt: should we attempt to decrypt the manifest
        """

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        try:
            header_signer = header.verify_rest(rest_data, sig_context, trusted_owner)
        except SigError as e:
            raise ManifestError(
                'Signature verification failed: {}'.format(e)) from e
        fields = cls._parse_yaml(rest_data, sig_context, decrypt=decrypt)

        if header.signature is None:
            if fields.get('owner') != trusted_owner:
                raise ManifestError(
                    'Wrong owner for manifest without signature: '
                    'trusted owner {!r}, manifest {!r}'.format(
                        trusted_owner, fields.get('owner')))
        else:
            possible_owners = [header_signer]
            if not allow_only_primary_key:
                possible_owners.extend(sig_context.get_possible_owners(header_signer))
            if fields.get('owner') not in possible_owners:
                raise ManifestError(
                    'Manifest owner does not have access to signing key: header {!r}, '
                    'manifest {!r}'.format(header_signer, fields.get('owner')))
        manifest = cls(header, fields, rest_data, local_path=local_path)
        if schema:
            manifest.apply_schema(schema)

        return manifest

    def to_bytes(self):
        """
        Serialize the manifest, including the signature.
        """

        if self.header is None:
            raise ManifestError('Manifest not signed')

        return self.header.to_bytes() + HEADER_SEPARATOR + self.original_data

    def apply_schema(self, schema: Schema):
        """
        Validate the manifest using a provided schema.
        """

        schema.validate(self._fields)

    @classmethod
    def verify_and_load_pubkeys(cls,
                                data: bytes,
                                sig_context: SigContext) -> None:
        """
        Load pubkeys directly from manifest's message (body) into signature context
        without relying on locally stored users/keys. This might be used in a
        self-signed manifests context.
        """

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        fields = cls._parse_yaml(rest_data, sig_context)
        # to be able to import keys from both bridge ('pubkey' field) and user ('pubkeys' field)
        # we have to handle both fields
        pubkeys = fields.get('pubkeys', [])
        if not pubkeys:
            pubkeys = [fields.get('pubkey')]

        if len(pubkeys) < 1:
            raise ManifestError('Manifest doest not contain any pubkeys')

        primary_pubkey = pubkeys[0]

        # Now we can verify integrity of the self-signed manifest
        owner = header.verify_rest(rest_data, sig_context, trusted_owner=None,
                                   pubkey=primary_pubkey)

        # Add the retrieved pubkey(s) to the sig context
        sig_context.keys[owner] = primary_pubkey

        for pubkey in pubkeys:
            sig_context.add_pubkey(pubkey, owner)

    @classmethod
    def _parse_yaml(cls, data: bytes, sig: SigContext, decrypt: bool = True):
        try:
            fields = load_yaml(data.decode('utf-8'))
            if decrypt:
                fields = cls.decrypt(fields, sig)
            fields = cls.update_manifest_version(fields)
            return fields
        except (ValueError, yaml.YAMLError) as e:
            raise ManifestError('Manifest parse error: {}'.format(e)) from e


class Header:
    """
    Manifest header (owner and signature).
    """

    def __init__(self, signature: Optional[str]):
        self.signature = None

        if signature is not None:
            self.signature = signature.rstrip('\n')

    def verify_rest(self, rest_data: bytes, sig_context: SigContext,
                    trusted_owner: Optional[str], pubkey: Optional[str] = None) -> str:
        """
        Verify the signature against manifest content (without parsing it).
        Return signer.

        pass the optional pubkey *only* in case of self-signed manifests
        """

        # Handle lack of signature, if allowed
        if self.signature is None:
            if trusted_owner is None:
                raise SigError('Signature expected')
            return trusted_owner

        return sig_context.verify(self.signature, rest_data, pubkey)

    @classmethod
    def from_bytes(cls, data: bytes):
        """
        Parse the header.
        """

        parser = HeaderParser(data)
        fields = parser.parse('signature', 'pubkey')
        if 'pubkey' in fields:
            logger.warning('deprecated pubkey field found in header, ignoring')
        return cls(fields.get('signature'))

    def to_bytes(self):
        """
        Serialize the header.
        """

        lines = []
        if self.signature is not None:
            lines.append('signature: |')
            for sig_line in self.signature.splitlines():
                lines.append('  ' + sig_line)

        data = '\n'.join(lines).encode()
        self.verify_bytes(data)
        return data

    def verify_bytes(self, data: bytes):
        """
        Internal consistency check: verify that the serialized manifest parses
        the same.
        """

        try:
            header = self.from_bytes(data)
        except ManifestError as me:
            raise Exception('Header serialization error') from me
        if header.signature != self.signature:
            print(repr(header.signature), repr(self.signature))
            raise Exception('Header serialization error')


def split_header(data: bytes) -> Tuple[bytes, bytes]:
    """
    Split manifest data into header and the rest of content.
    """

    if data.startswith(HEADER_SEPARATOR_EMPTY):
        return b'', data[len(HEADER_SEPARATOR_EMPTY):]

    header_data, sep, rest_data = data.partition(HEADER_SEPARATOR)
    if not sep:
        raise ManifestError('Separator not found in manifest')
    return header_data, rest_data


class HeaderParser:
    """
    An extremely simple YAML parser, used for manifest header.
    Handles two types of fields:

        field_normal: "normal_value"
        field_block: |
          block value

    Example usage:

        parser = HeaderParser(data)
        fields = parser.parse('signature', 'owner')
    """

    SIMPLE_FIELD_RE = re.compile(r'([a-z]+): "([a-zA-Z0-9_ .-]+)"$')
    BLOCK_FIELD_RE = re.compile(r'([a-z]+): \|$')
    BLOCK_LINE_RE = re.compile('^ {0,2}$|^  (.*)')

    def __init__(self, data: bytes):
        try:
            text = data.decode('ascii', 'strict')
        except UnicodeDecodeError as ude:
            raise ManifestError('Header should be ASCII') from ude
        self.lines = text.splitlines()
        self.pos = 0

    def parse(self, *fields: str) -> Dict[str, str]:
        """
        Parse the header. Recognize only provided fields.
        """

        result: Dict[str, str] = {}
        while not self.is_eof():
            name, value = self.parse_field()
            if name not in fields:
                raise ManifestError(
                    f'Unexpected field: {name!r}')
            if name in  result:
                raise ManifestError(
                    f'Duplicate field: {name!r}')
            result[name] = value
        return result

    def parse_field(self) -> Tuple[str, str]:
        """
        Parse a single field. Returns (name, value).
        """

        assert not self.is_eof()
        line = self.lines[self.pos]
        self.pos += 1

        m = self.SIMPLE_FIELD_RE.match(line)
        if m:
            return m.group(1), m.group(2)

        m = self.BLOCK_FIELD_RE.match(line)
        if m:
            return m.group(1), self.parse_block()

        raise ManifestError('Unexpected line: {!r}'.format(line))

    def is_eof(self):
        """
        Check if there is nothing else in the parser.
        """
        return self.pos == len(self.lines)

    def parse_block(self):
        """
        Parse a block continuation (after ``field_name: |``)
        """

        parsed_lines = []
        while self.pos < len(self.lines):
            line = self.lines[self.pos]
            m = self.BLOCK_LINE_RE.match(line)
            if not m:
                break
            self.pos += 1
            parsed_lines.append(m.group(1) or '')

        while parsed_lines and parsed_lines[-1] == '':
            parsed_lines.pop()

        if not parsed_lines:
            raise ManifestError('Block literal cannot be empty')
        return '\n'.join(parsed_lines)
