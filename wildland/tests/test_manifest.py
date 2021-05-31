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
from ..manifest.sig import SodiumSigContext


@pytest.fixture(scope='session')
def key_dir():
    with tempfile.TemporaryDirectory(prefix='wlsecret.') as d:
        yield Path(d)


@pytest.fixture
def sig(key_dir):
    return SodiumSigContext(key_dir)


@pytest.fixture
def owner(sig):
    own, pubkey = sig.generate()
    sig.add_pubkey(pubkey)
    return own


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


def test_parse_key_not_loaded(sig):
    # This should fail because a key that was not explicitly loaded into sig context should not
    # be usable
    owner, pubkey = sig.generate()
    sig_2 = sig.copy()

    sig.add_pubkey(pubkey)

    test_data = f'''
    object: test
    owner: "{owner}"
    key1: value1
    key2: "value2"
    '''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data

    with pytest.raises(ManifestError):
        Manifest.from_bytes(data, sig_2)


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

    with pytest.raises(ManifestError, match='Manifest owner does not have access to signing key'):
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
backends: 
    storage: []
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


def test_parse_duplicate_keys(sig, owner):
    test_data = f'''
owner: "{owner}"
pubkeys: []
key1: value1
key1: value2
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    with pytest.raises(ManifestError):
        Manifest.from_bytes(data, sig)


def test_parse_update_obsolete(sig, owner):
    test_data = f'''
signer: "{owner}"
backends: 
    storage: []
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['object'] == 'container'
    assert manifest.fields['owner'] == owner
    assert manifest.fields['version'] == Manifest.CURRENT_VERSION


def test_parse_version_1(sig, owner):
    test_data = f'''
signer: "{owner}"
backends: 
    storage: []
key1: value1
key2: "value2"
version: '1'
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    with pytest.raises(ManifestError):
        Manifest.from_bytes(data, sig)


def test_encrypt(sig, owner):
    test_data = {
        'owner': owner,
        'key': 'VALUE'
    }
    encrypted_data = Manifest.encrypt(test_data, sig)
    assert list(encrypted_data.keys()) == ['encrypted']
    assert list(encrypted_data['encrypted'].keys()) == ['encrypted-data', 'encrypted-keys']
    decrypted_data = Manifest.decrypt(encrypted_data, sig)
    assert decrypted_data['owner'] == owner
    assert decrypted_data['key'] == 'VALUE'


def test_encrypt_fail(sig, owner):
    test_data = {
        'owner': owner,
        'key': 'VALUE'
    }
    encrypted_data = Manifest.encrypt(test_data, sig)
    del sig.private_keys[owner]
    with pytest.raises(ManifestError):
        Manifest.decrypt(encrypted_data, sig)


def test_encrypt_access(sig, owner):
    additional_owner, pubkey = sig.generate()
    sig.add_pubkey(pubkey)

    test_data = {
        'owner': owner,
        'key': 'VALUE',
        'access': [{'user': additional_owner}]
    }
    encrypted_data = Manifest.encrypt(test_data, sig)

    del sig.private_keys[owner]
    (sig.key_dir / f'{owner}.sec').unlink()

    decrypted_data = Manifest.decrypt(encrypted_data, sig)
    assert decrypted_data['owner'] == owner
    assert decrypted_data['key'] == 'VALUE'


def test_encrypt_add_owner(sig, owner):
    _, additional_pubkey = sig.generate()
    sig.add_pubkey(additional_pubkey, owner)

    test_data = {
        'owner': owner,
        'key': 'VALUE',
    }
    encrypted_data = Manifest.encrypt(test_data, sig)

    assert len(encrypted_data['encrypted']['encrypted-keys']) == 2

    del sig.private_keys[owner]
    (sig.key_dir / f'{owner}.sec').unlink()

    decrypted_data = Manifest.decrypt(encrypted_data, sig)
    assert decrypted_data['owner'] == owner
    assert decrypted_data['key'] == 'VALUE'


def test_encrypt_no(sig, owner):
    test_data = {
        'owner': owner,
        'key': 'VALUE',
        'access': [{'user': '*'}]
    }
    encrypted_data = Manifest.encrypt(test_data, sig)
    assert encrypted_data == test_data


def test_encrypt_inline_storage(sig, owner):
    additional_owner, pubkey = sig.generate()
    sig.add_pubkey(pubkey)

    test_data = {
        'owner': owner,
        'key': 'VALUE',
        'access': [{'user': '*'}],
        'backends': {
            'storage': [
                {'key3': 'VALUE3'},
                {'key2': 'VALUE2',
                 'access': [{'user': additional_owner}]}
            ]
        }
    }
    encrypted_data = Manifest.encrypt(test_data, sig)
    assert 'owner' in encrypted_data
    assert encrypted_data['owner'] == owner
    assert 'backends' in encrypted_data
    assert 'storage' in encrypted_data['backends']
    assert len(encrypted_data['backends']['storage']) == 2
    assert 'encrypted' in encrypted_data['backends']['storage'][1]
    assert len(encrypted_data['backends']['storage'][1]['encrypted']['encrypted-keys']) == 2

    decrypted_data = Manifest.decrypt(encrypted_data, sig)
    assert test_data == decrypted_data


def test_encrypt_catalog(sig, owner):
    additional_owner, pubkey = sig.generate()
    sig.add_pubkey(pubkey)

    test_data = {
        'owner': owner,
        'object': 'user',
        'key': 'VALUE',
        'manifests-catalog': [
                {'key3': 'VALUE3'},
                {'key2': 'VALUE2',
                 'access': [{'user': additional_owner}]}
            ]
    }
    encrypted_data = Manifest.encrypt(test_data, sig)
    assert 'owner' in encrypted_data
    assert encrypted_data['owner'] == owner
    assert 'manifests-catalog' in encrypted_data
    assert len(encrypted_data['manifests-catalog']) == 2
    assert 'encrypted' in encrypted_data['manifests-catalog'][1]
    assert len(encrypted_data['manifests-catalog'][1]['encrypted']['encrypted-keys']) == 2

    decrypted_data = Manifest.decrypt(encrypted_data, sig)
    assert test_data == decrypted_data


def test_original_bytes(sig, owner):
    test_data = f'''
object: test
owner: "{owner}"
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, owner, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)

    (sig.key_dir / f'{owner}.sec').unlink()

    data = manifest.to_bytes()

    manifest_2 = Manifest.from_bytes(data, sig)

    assert manifest_2.fields['owner'] == owner
    assert manifest_2.fields['key1'] == 'value1'
    assert manifest_2.fields['key2'] == 'value2'
