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

# pylint: disable=missing-docstring

import pytest

from ..manifest.manifest import split_header, Header, HeaderParser, ManifestError


def test_split_header():
    assert split_header(b'header\n---\ndata') == (b'header', b'data')
    assert split_header(b'\n---\n') == (b'', b'')
    with pytest.raises(ManifestError):
        split_header(b'--\nno newline')
    with pytest.raises(ManifestError):
        split_header(b'no header')
    with pytest.raises(ManifestError):
        split_header(b'foo\n-- \nbar')


def test_parse_header():
    data = b'''\
signature: |
  line 1
  line 2
'''
    header = Header.from_bytes(data)
    assert header.signature == 'line 1\nline 2'
    assert header.pubkey is None

def test_parse_header_with_pubkey():
    data = b'''\
signature: |
  line 1
  line 2
pubkey: |
  line 3
  line 4
'''
    header = Header.from_bytes(data)
    assert header.signature == 'line 1\nline 2'
    assert header.pubkey == 'line 3\nline 4'


def test_header_to_bytes():
    header = Header('line 1\nline 2', None)
    data = header.to_bytes()
    assert data == b'''\
signature: |
  line 1
  line 2'''


def test_header_with_pubkey_to_bytes():
    header = Header('line 1\nline 2', 'line 3\nline 4')
    data = header.to_bytes()
    assert data == b'''\
signature: |
  line 1
  line 2
pubkey: |
  line 3
  line 4'''


def test_parser():
    parser = HeaderParser(b'''\
foo: "foo"
bar: |
  bar

  lines
baz: "baz"
''')
    assert parser.expect_field('foo') == 'foo'
    assert parser.expect_field('bar') == 'bar\n\nlines'
    assert parser.expect_field('baz') == 'baz'


def test_parser_error():
    with pytest.raises(ManifestError, match='Unexpected line'):
        HeaderParser(b'foo: unquoted').expect_field('foo')
    with pytest.raises(ManifestError, match='Unexpected line'):
        HeaderParser(b'foo: "illegal\"characters"').expect_field('foo')
    with pytest.raises(ManifestError, match='Unexpected field'):
        HeaderParser(b'bar: "wrong field"').expect_field('foo')
    with pytest.raises(ManifestError, match='Unexpected input'):
        HeaderParser(b'bar: "extra field"').expect_eof()
    with pytest.raises(ManifestError, match='Block literal cannot be empty'):
        HeaderParser(b'foo: |\nbar: "empty block"').expect_field('foo')
