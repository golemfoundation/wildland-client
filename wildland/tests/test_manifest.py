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
def signer(sig):
    return sig.generate()[0]



def make_header(sig, signer, test_data, attach_pubkey=False):
    signature = sig.sign(signer, test_data)
    pubkey = None
    if attach_pubkey:
        pubkey = sig.get_pubkey(signer)
    header = Header(signature.strip(), pubkey)
    return header.to_bytes()

def test_parse(sig, signer):
    test_data = f'''
signer: "{signer}"
key1: value1
key2: "value2"
'''.encode()

    data = make_header(sig, signer, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, sig)
    assert manifest.fields['signer'] == signer
    assert manifest.fields['key1'] == 'value1'
    assert manifest.fields['key2'] == 'value2'


def test_parse_wrong_signer(sig, signer):
    test_data = '''
signer: other signer
key1: value1
key2: "value2"
'''.encode()
    data = make_header(sig, signer, test_data) + b'\n---\n' + test_data

    with pytest.raises(ManifestError, match='Signer field mismatch'):
        Manifest.from_bytes(data, sig)


def test_parse_self_signed(sig, signer):
    test_data = f'''
signer: "{signer}"
key1: value1
key2: "value2"
'''.encode()

    data = (make_header(sig, signer, test_data, attach_pubkey=True) +
            b'\n---\n' + test_data)
    manifest = Manifest.from_bytes(data, sig, self_signed=Manifest.REQUIRE)
    assert manifest.fields['signer'] == signer
    assert manifest.fields['key1'] == 'value1'
    assert manifest.fields['key2'] == 'value2'

    print(data.decode())
