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

import yaml

from .schema import Schema
from .sig import SigContext, SigError
from ..exc import WildlandError


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

    # Values for self_signed parameter
    DISALLOW = 0
    ALLOW = 1
    REQUIRE = 2

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
    def from_fields(cls, fields: dict) -> 'Manifest':
        '''
        Create a manifest based on a dict of fields.

        Has to be signed separately.
        '''

        if not isinstance(fields, dict) or 'signer' not in fields:
            raise ManifestError('signer field not found')
        data = yaml.dump(fields, encoding='utf-8')
        return Manifest(None, fields, data)

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
        if not isinstance(fields, dict) or 'signer' not in fields:
            raise ManifestError('signer field not found')
        return cls(None, fields, data)

    def sign(self, sig_context: SigContext, attach_pubkey: bool = False):
        '''
        Sign a previously unsigned manifest.
        If attach_pubkey is true, attach the public key to the signature.
        '''

        if self.header is not None:
            raise ManifestError('Manifest already signed')

        signer = self._fields['signer']
        signature = sig_context.sign(signer, self.original_data)
        pubkey = None
        if attach_pubkey:
            pubkey = sig_context.get_pubkey(signer)
        self.header = Header(signature, pubkey)

    def skip_signing(self):
        '''
        Explicitly mark the manifest as unsigned, and allow using it.
        '''

        self.header = Header(None, None)

    @classmethod
    def from_file(cls, path, sig_context: SigContext,
                  schema: Optional[Schema] = None,
                  self_signed: int = DISALLOW,
                  trusted_signer: Optional[str] = None) -> 'Manifest':
        '''
        Load a manifest from YAML file, verifying it.

        Args:
            path: path to YAML file
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            self_signed: ignore that a signer is unknown to the SigContext
                (useful for bootstrapping)
            trusted_signer: accept signature-less manifest from this signer
        '''

        with open(path, 'rb') as f:
            data = f.read()
        return cls.from_bytes(
            data, sig_context, schema, self_signed, trusted_signer)

    @classmethod
    def from_bytes(cls, data: bytes, sig_context: SigContext,
                   schema: Optional[Schema] = None,
                   self_signed: int = DISALLOW,
                   trusted_signer: Optional[str] = None) -> 'Manifest':
        '''
        Load a manifest from YAML content, verifying it.

        Args:
            data: existing manifest content
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            self_signed: ignore that a signer is unknown to the SigContext
                (useful for bootstrapping)
            trusted_signer: accept signature-less manifest from this signer
        '''

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        try:
            header_signer = header.verify_rest(
                rest_data, sig_context, self_signed, trusted_signer)
        except SigError as e:
            raise ManifestError(
                'Signature verification failed: {}'.format(e))

        try:
            rest_str = rest_data.decode('utf-8')
            fields = yaml.safe_load(rest_str)
        except ValueError as e:
            raise ManifestError('Manifest parse error: {}'.format(e))

        if fields.get('signer') != header_signer:
            if header.signature is None:
                raise ManifestError(
                    'Wrong signer for manifest without signature: '
                    'trusted signer {!r}, manifest {!r}'.format(
                        header_signer, fields.get('signer')))

            raise ManifestError(
                'Signer field mismatch: header {!r}, manifest {!r}'.format(
                    header_signer, fields.get('signer')))

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


class Header:
    '''
    Manifest header (signer and signature).
    '''

    def __init__(self, signature: Optional[str], pubkey: Optional[str]):
        self.signature = None
        self.pubkey = None

        if signature is not None:
            self.signature = signature.rstrip('\n')
        if pubkey is not None:
            self.pubkey = pubkey.rstrip('\n')

    def verify_rest(self, rest_data: bytes, sig_context: SigContext,
                    self_signed: int, trusted_signer: Optional[str]) -> str:
        '''
        Verify the signature against manifest content (without parsing it).
        Return signer.
        '''

        # Verify pubkey presence/absence
        if self_signed == Manifest.REQUIRE and self.pubkey is None:
            raise SigError('Expecting the header to contain pubkey')

        if self_signed == Manifest.DISALLOW and self.pubkey is not None:
            raise SigError('Not expecting the header to contain pubkey')

        # Verify against public key, if provided
        if self.pubkey is not None:
            if self.signature is None:
                raise SigError('Signature is always required when providing pubkey')

            sig_temp = sig_context.copy()
            pubkey_signer = sig_temp.add_pubkey(self.pubkey)
            signer = sig_temp.verify(self.signature, rest_data)
            if signer != pubkey_signer:
                raise SigError(
                    'Signer does not match pubkey (signature {!r}, pubkey {!r})'.format(
                        signer, pubkey_signer))
            return signer

        # Handle lack of signature, if allowed
        if self.signature is None:
            if trusted_signer is None:
                raise SigError('Signature expected')
            return trusted_signer

        return sig_context.verify(self.signature, rest_data)

    @classmethod
    def from_bytes(cls, data: bytes):
        '''
        Parse the header.
        '''

        parser = HeaderParser(data)
        fields = parser.parse('signature', 'pubkey')
        return cls(fields.get('signature'), fields.get('pubkey'))

    def to_bytes(self):
        '''
        Serialize the header.
        '''

        lines = []
        if self.signature is not None:
            lines.append('signature: |')
            for sig_line in self.signature.splitlines():
                lines.append('  ' + sig_line)

        if self.pubkey is not None:
            lines.append('pubkey: |')
            for sig_line in self.pubkey.splitlines():
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
        except ManifestError:
            raise Exception('Header serialization error')
        if header.signature != self.signature:
            print(repr(header.signature), repr(self.signature))
            raise Exception('Header serialization error')
        if header.pubkey != self.pubkey:
            print(repr(header.pubkey), repr(self.pubkey))
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
        fields = parser.parse('signature', 'signer')
    '''

    SIMPLE_FIELD_RE = re.compile(r'([a-z]+): "([a-zA-Z0-9_ .-]+)"$')
    BLOCK_FIELD_RE = re.compile(r'([a-z]+): \|$')
    BLOCK_LINE_RE = re.compile('^ {0,2}$|^  (.*)')

    def __init__(self, data: bytes):
        try:
            text = data.decode('ascii', 'strict')
        except UnicodeDecodeError:
            raise ManifestError('Header should be ASCII')
        self.lines = text.splitlines()
        self.pos = 0

    def parse(self, *fields: str) -> Dict[str, str]:
        '''
        Parse the header. Recognize only provided fields.
        '''

        result = {}
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
