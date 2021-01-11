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

# pylint: disable=missing-docstring, redefined-outer-name

import tempfile
from pathlib import Path

import pytest

from ..manifest.manifest import Manifest, Header, ManifestError
from ..manifest.sig import SignifySigContext


@pytest.fixture(scope='session')
def key_dir():
    with tempfile.TemporaryDirectory(prefix='wlsecret.') as d:
        yield Path(d)


@pytest.fixture(scope='session')
def sig(key_dir):
    return SignifySigContext(key_dir)


@pytest.fixture(scope='session')
def owner(sig):
    return sig.generate()[0]



def make_header(sig, owner, test_data):
    signature = sig.sign(owner, test_data)
    header = Header(signature.strip())
    return header.to_bytes()


def test_parse(sig, owner):
    test_data = f'''
object: test
owner: "{owner}"
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['owner'] == owner
    assert manifest.fields['key1'] == 'value1'
    assert manifest.fields['key2'] == 'value2'


def test_parse_deprecated(sig, owner):
    test_data = f'''
object: test
signer: "{owner}"
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['owner'] == owner
    assert manifest.fields['key1'] == 'value1'
    assert manifest.fields['key2'] == 'value2'


def test_parse_no_signature(sig, owner):
    test_data = f'''
---
object: test
owner: "{owner}"
key1: value1
'''.encode()
    manifest = Manifest.from_bytes(test_data, sig, trusted_owner=owner)
    assert manifest.fields['owner'] == owner
    assert manifest.fields['key1'] == 'value1'

    with pytest.raises(ManifestError, match='Signature expected'):
        Manifest.from_bytes(test_data, sig)

    with pytest.raises(ManifestError, match='Wrong owner for manifest without signature'):
        Manifest.from_bytes(test_data, sig, trusted_owner='0xcafe')


def test_parse_wrong_owner(sig, owner):
    test_data = '''
object: test
owner: other owner
key1: value1
key2: "value2"
'''.encode()
    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data

    with pytest.raises(ManifestError, match='Manifest owner does not have access to signer key'):
        Manifest.from_bytes(data, sig)

def test_parse_guess_manifest_type_bridge(sig, owner):
    test_data = f'''
owner: "{owner}"
user: user1
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['object'] == 'bridge'

def test_parse_guess_manifest_type_container(sig, owner):
    test_data = f'''
owner: "{owner}"
backends: []
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['object'] == 'container'

def test_parse_guess_manifest_type_storage(sig, owner):
    test_data = f'''
owner: "{owner}"
type: type1
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['object'] == 'storage'

def test_parse_guess_manifest_type_user(sig, owner):
    test_data = f'''
owner: "{owner}"
pubkeys: []
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['object'] == 'user'
