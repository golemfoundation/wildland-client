# TODO pylint: disable=missing-docstring

from typing import Tuple, Optional
import re

import yaml

from .schema import Schema
from .sig import SigContext, SigError
from .exc import WildlandError


HEADER_SEPARATOR = b'\n---\n'


class ManifestError(WildlandError):
    pass


class Manifest:
    '''
    Represents a loaded manifest.

    The data (fields) should not be modified, because it needs to match the
    return '\n.join(parsed_lines)signature.
    '''

    def __init__(self, header: 'Header', fields, original_data: bytes):
        self.header = header
        self.fields = fields
        self.original_data = original_data

    @classmethod
    def from_fields(cls, fields, sig_context: SigContext) -> 'Manifest':
        signer = fields['signer']
        data = yaml.dump(fields, encoding='utf-8')
        signature = sig_context.sign(data, signer)
        header = Header(signer, signature)
        return cls(header, fields, data)

    @classmethod
    def from_bytes(cls, data: bytes, sig_context: SigContext,
                   schema: Optional[Schema] = None) -> 'Manifest':
        '''
        Create a manifest from YAML, performing necessary validation.

        Throws ManifestError on failure.
        '''

        header_data, rest_data = split_header(data)
        header = Header.from_bytes(header_data)

        try:
            header.verify_rest(rest_data, sig_context)
        except SigError as e:
            raise ManifestError(
                'Signature verification failed: {}'.format(e))

        try:
            rest_str = rest_data.decode('utf-8')
            fields = yaml.safe_load(rest_str)
        except ValueError as e:
            raise ManifestError('Manifest parse error: {}'.format(e))

        if fields.get('signer') != header.signer:
            raise ManifestError('Signer field mismatch')

        manifest = cls(header, fields, rest_data)
        if schema:
            manifest.apply_schema(schema)

        return manifest

    def to_bytes(self):
        return self.header.to_bytes() + HEADER_SEPARATOR + self.original_data

    def apply_schema(self, schema: Schema):
        schema.validate(self.fields)


class Header:
    def __init__(self, signer: str, signature: str):
        self.signer = signer
        self.signature = signature

    def verify_rest(self, rest_data: bytes, sig_context: SigContext):
        sig_context.verify(self.signer, self.signature, rest_data)

    @classmethod
    def from_bytes(cls, data: bytes):
        parser = HeaderParser(data)
        signer = parser.expect_field('signer')
        signature = parser.expect_field('signature')
        parser.expect_eof()
        return cls(signer, signature)

    def to_bytes(self):
        lines = []
        lines.append(f'signer: "{self.signer}"')
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
        if header.signer != self.signer or header.signature != self.signature:
            raise Exception('Header serialization error')


def split_header(data: bytes) -> Tuple[bytes, bytes]:
    header_data, sep, rest_data = data.partition(HEADER_SEPARATOR)
    if not sep:
        raise ManifestError('Separator not found in manifest')
    return header_data, rest_data


class HeaderParser:
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

    def expect_field(self, name):
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
        if self.pos < len(self.lines):
            raise ManifestError(
                'Unexpected input: {!r}'.format(self.lines[self.pos]))

    def parse_block(self):
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
