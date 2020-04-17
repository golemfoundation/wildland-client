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

from typing import Tuple, Optional
import re

import yaml

from .schema import Schema
from .sig import SigContext, SigError
from ..exc import WildlandError


HEADER_SEPARATOR = b'\n---\n'


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

        # If header is set, that means we have verified the signature.
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

        if HEADER_SEPARATOR in data:
            _, data = split_header(data)

        rest_str = data.decode('utf-8')
        fields = yaml.safe_load(rest_str)
        if not isinstance(fields, dict) or 'signer' not in fields:
            raise ManifestError('signer field not found')
        return cls(None, fields, data)

    def sign(self, sig_context: SigContext):
        '''
        Sign a previously unsigned manifest.
        '''
        if self.header is not None:
            raise ManifestError('Manifest already signed')

        signer = self._fields['signer']
        signature = sig_context.sign(signer, self.original_data)
        self.header = Header(signature)

    @classmethod
    def from_file(cls, path, sig_context: SigContext,
                   schema: Optional[Schema] = None,
                   self_signed=False) -> 'Manifest':
        '''
        Load a manifest from YAML file, verifying it.

        Args:
            path: path to YAML file
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            self_signed: ignore that a signer is unknown to the SigContext
                (useful for bootstrapping)
        '''

        with open(path, 'rb') as f:
            data = f.read()
        return cls.from_bytes(data, sig_context, schema, self_signed)

    @classmethod
    def from_bytes(cls, data: bytes, sig_context: SigContext,
                   schema: Optional[Schema] = None,
                   self_signed=False) -> 'Manifest':
        '''
        Load a manifest from YAML content, verifying it.

        Args:
            data: existing manifest content
            sig_context: a SigContext to use for signature verification
            schema: a Schema to validate the fields with
            self_signed: ignore that a signer is unknown to the SigContext
                (useful for bootstrapping)
        '''

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        try:
            header_signer = header.verify_rest(rest_data, sig_context, self_signed)
        except SigError as e:
            raise ManifestError(
                'Signature verification failed: {}'.format(e))

        try:
            rest_str = rest_data.decode('utf-8')
            fields = yaml.safe_load(rest_str)
        except ValueError as e:
            raise ManifestError('Manifest parse error: {}'.format(e))

        if fields.get('signer') != header_signer:
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

    def __init__(self, signature: str):
        self.signature = signature.rstrip('\n')

    def verify_rest(self, rest_data: bytes, sig_context: SigContext,
                    self_signed) -> str:
        '''
        Verify the signature against manifest content (without parsing it).
        Return signer, if known.
        '''

        return sig_context.verify(self.signature, rest_data, self_signed)

    @classmethod
    def from_bytes(cls, data: bytes):
        '''
        Parse the header.
        '''

        parser = HeaderParser(data)
        signature = parser.expect_field('signature')
        parser.expect_eof()
        return cls(signature)

    def to_bytes(self):
        '''
        Serialize the header.
        '''

        lines = []
        lines.append(f'signature: |')
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
        except ManifestError:
            raise Exception('Header serialization error')
        if header.signature != self.signature:
            print(repr(header.signature), repr(self.signature))
            raise Exception('Header serialization error')


def split_header(data: bytes) -> Tuple[bytes, bytes]:
    '''
    Split manifest data into header and the rest of content.
    '''

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
        signer = parser.expect_field('signer')
        signature = parser.expect_field('signature')
        parser.expect_eof()
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

    def expect_field(self, name: str) -> str:
        '''
        Parse a single field with a given name
        '''

        if self.pos == len(self.lines):
            raise ManifestError('Unexpected end of header')
        line = self.lines[self.pos]
        self.pos += 1

        m = self.SIMPLE_FIELD_RE.match(line)
        if m:
            if m.group(1) != name:
                raise ManifestError(
                    'Unexpected field: {!r}'.format(m.group(1)))
            return m.group(2)

        m = self.BLOCK_FIELD_RE.match(line)
        if m:
            if m.group(1) != name:
                raise ManifestError(
                    'Unexpected field: {!r}'.format(m.group(1)))
            return self.parse_block()

        raise ManifestError('Unexpected line: {!r}'.format(line))

    def expect_eof(self):
        '''
        Make sure there is nothing else in the parser.
        '''

        if self.pos < len(self.lines):
            raise ManifestError(
                'Unexpected input: {!r}'.format(self.lines[self.pos]))

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
