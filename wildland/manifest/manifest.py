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
Classes for handling signed Wildland manifests
'''

from typing import Tuple, Optional, Dict
import re
import logging

import yaml

from .schema import Schema
from .sig import SigContext, SigError
from ..exc import WildlandError


logger = logging.getLogger('manifest')

HEADER_SEPARATOR = b'\n---\n'
HEADER_SEPARATOR_EMPTY = b'---\n'


class ManifestError(WildlandError):
    '''
    Exception class for problems during manifest loading or construction.
    '''


class Manifest:
    '''
    Represents a loaded manifest.

    The data (fields) should not be modified, because it needs to match the
    return signature.
    '''

    def __init__(self, header: Optional['Header'], fields,
                 original_data: bytes):

        # If header is set, that means we have verified the signature,
        # or explicitly accepted an unsigned manifest.
        self.header = header

        # Accessible as 'fields' only if there is a header.
        self._fields = fields

        # Original data that has been signed.
        self.original_data = original_data

    @property
    def fields(self):
        '''
        A wrapper for manifest fields that makes sure the manifest is signed.
        '''

        if not self.header:
            raise ManifestError('Trying to read an unsigned manifest')
        return self._fields

    @classmethod
    def update_obsolete(cls, fields: dict) -> dict:
        """
        Update any obsolete fields. Currently handles:
          - signer --> owner
          - inner-container --> reference-container
          - in local storages, path --> location
        """
        if not isinstance(fields, dict):
            raise TypeError(f'expected dict, got {type(fields)} instance')

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
                if isinstance(storage, dict):
                    cls.update_obsolete(storage)
        if 'infrastructures' in fields:
            for container in fields['infrastructures']:
                if isinstance(container, dict):
                    cls.update_obsolete(container)
        if fields.get('type', None) in ['local', 'local-cached', 'local-dir-cached'] and \
                'path' in fields:
            fields['location'] = fields['path']
            del fields['path']

        return fields

    @classmethod
    def from_fields(cls, fields: dict) -> 'Manifest':
        '''
        Create a manifest based on a dict of fields.

        Has to be signed separately.
        '''

        fields = cls.update_obsolete(fields)
        data = yaml.dump(fields, encoding='utf-8', sort_keys=False)
        return cls(None, fields, data)

    @classmethod
    def from_unsigned_bytes(cls, data: bytes) -> 'Manifest':
        '''
        Create a new Manifest based on existing YAML-serialized
        content. The content can include an existing header, it will be ignored.

        Has to be signed separately.
        '''

        if HEADER_SEPARATOR in data or data.startswith(HEADER_SEPARATOR_EMPTY):
            _, data = split_header(data)

        rest_str = data.decode('utf-8')
        fields = yaml.safe_load(rest_str)
        fields = cls.update_obsolete(fields)
        return cls(None, fields, data)

    def sign(self, sig_context: SigContext, only_use_primary_key: bool = False):
        '''
        Sign a previously unsigned manifest.
        If attach_pubkey is true, attach the public key to the signature.
        '''

        if self.header is not None:
            raise ManifestError('Manifest already signed')

        owner = self._fields['owner']
        signature = sig_context.sign(owner, self.original_data,
                                     only_use_primary_key=only_use_primary_key)
        self.header = Header(signature)

    def skip_signing(self):
        '''
        Explicitly mark the manifest as unsigned, and allow using it.
        '''

        self.header = Header(None)

    @classmethod
    def from_file(cls, path, sig_context: SigContext,
                  schema: Optional[Schema] = None,
                  trusted_owner: Optional[str] = None) -> 'Manifest':
        '''
        Load a manifest from YAML file, verifying it.

        Args:
            path: path to YAML file
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            trusted_owner: accept signature-less manifest from this owner
        '''

        with open(path, 'rb') as f:
            data = f.read()
        return cls.from_bytes(
            data, sig_context, schema, trusted_owner)

    @classmethod
    def from_bytes(cls, data: bytes, sig_context: SigContext,
                   schema: Optional[Schema] = None,
                   trusted_owner: Optional[str] = None,
                   allow_only_primary_key: bool = False) -> 'Manifest':
        '''
        Load a manifest from YAML content, verifying it.

        Args:
            data: existing manifest content
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            trusted_owner: accept signature-less manifest from this owner
            allow_only_primary_key: can this manifest be signed by any auxiliary keys
                associated with the given user?
        '''

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        try:
            header_signer = header.verify_rest(rest_data, sig_context, trusted_owner)
        except SigError as e:
            raise ManifestError(
                'Signature verification failed: {}'.format(e)) from e

        fields = cls._parse_yaml(rest_data)

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

        manifest = cls(header, fields, rest_data)
        if schema:
            manifest.apply_schema(schema)

        return manifest

    def to_bytes(self):
        '''
        Serialize the manifest, including the signature.
        '''

        if self.header is None:
            raise ManifestError('Manifest not signed')

        return self.header.to_bytes() + HEADER_SEPARATOR + self.original_data

    def apply_schema(self, schema: Schema):
        '''
        Validate the manifest using a provided schema.
        '''

        schema.validate(self._fields)

    @classmethod
    def load_pubkeys(cls,
                     data: bytes,
                     sig_context: SigContext) -> None:
        """
        Load pubkeys directly from manifest's message (body) into signature context
        without relying on locally stored users/keys. This might be used in a
        self-signed manifests context.
        """

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        fields = cls._parse_yaml(rest_data)
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
    def _parse_yaml(cls, data: bytes):
        try:
            fields = yaml.safe_load(data.decode('utf-8'))
            return cls.update_obsolete(fields)
        except ValueError as e:
            raise ManifestError('Manifest parse error: {}'.format(e)) from e


class Header:
    '''
    Manifest header (owner and signature).
    '''

    def __init__(self, signature: Optional[str]):
        self.signature = None

        if signature is not None:
            self.signature = signature.rstrip('\n')

    def verify_rest(self, rest_data: bytes, sig_context: SigContext,
                    trusted_owner: Optional[str], pubkey: Optional[str] = None) -> str:
        '''
        Verify the signature against manifest content (without parsing it).
        Return signer.

        pass the optional pubkey *only* in case of self-signed manifests
        '''

        # Handle lack of signature, if allowed
        if self.signature is None:
            if trusted_owner is None:
                raise SigError('Signature expected')
            return trusted_owner

        return sig_context.verify(self.signature, rest_data, pubkey)

    @classmethod
    def from_bytes(cls, data: bytes):
        '''
        Parse the header.
        '''

        parser = HeaderParser(data)
        fields = parser.parse('signature', 'pubkey')
        if 'pubkey' in fields:
            logger.warning('deprecated pubkey field found in header, ignoring')
        return cls(fields.get('signature'))

    def to_bytes(self):
        '''
        Serialize the header.
        '''

        lines = []
        if self.signature is not None:
            lines.append('signature: |')
            for sig_line in self.signature.splitlines():
                lines.append('  ' + sig_line)

        data = '\n'.join(lines).encode()
        self.verify_bytes(data)
        return data

    def verify_bytes(self, data: bytes):
        '''
        Internal consistency check: verify that the serialized manifest parses
        the same.
        '''

        try:
            header = self.from_bytes(data)
        except ManifestError as me:
            raise Exception('Header serialization error') from me
        if header.signature != self.signature:
            print(repr(header.signature), repr(self.signature))
            raise Exception('Header serialization error')


def split_header(data: bytes) -> Tuple[bytes, bytes]:
    '''
    Split manifest data into header and the rest of content.
    '''

    if data.startswith(HEADER_SEPARATOR_EMPTY):
        return b'', data[len(HEADER_SEPARATOR_EMPTY):]

    header_data, sep, rest_data = data.partition(HEADER_SEPARATOR)
    if not sep:
        raise ManifestError('Separator not found in manifest')
    return header_data, rest_data


class HeaderParser:
    '''
    An extremely simple YAML parser, used for manifest header.
    Handles two types of fields:

        field_normal: "normal_value"
        field_block: |
          block value

    Example usage:

        parser = HeaderParser(data)
        fields = parser.parse('signature', 'owner')
    '''

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
        '''
        Parse the header. Recognize only provided fields.
        '''

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
        '''
        Parse a single field. Returns (name, value).
        '''

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
        '''
        Check if there is nothing else in the parser.
        '''
        return self.pos == len(self.lines)

    def parse_block(self):
        '''
        Parse a block continuation (after ``field_name: |``)
        '''

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
