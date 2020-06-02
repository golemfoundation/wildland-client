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

# pylint: disable=missing-docstring,redefined-outer-name

from pathlib import Path
import tempfile
import base64

import pytest

from ..manifest.sig import SignifySigContext, SigError


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


@pytest.fixture(scope='session')
def other_signer(sig):
    return sig.generate()[0]


def test_pubkey_to_signer(sig):
    pubkey = '''\
untrusted comment: hello world
RWS/mJgf4GTLPY2+qOnPzWSYhlfP6nwH1fFwUFMlW52/tKx52pnWwoA0
'''
    sig_data = pubkey.splitlines()[1]
    assert base64.b64decode(sig_data)[:10] == b'\x45\x64\xbf\x98\x98\x1f\xe0\x64\xcb\x3d'

    assert sig.fingerprint(pubkey) == '0x3dcb64e01f9898bf6445'


def test_verify(sig, signer):
    test_data = b'hello world'
    signature = sig.sign(signer, test_data)

    assert sig.verify(signature, test_data) == signer


def test_verify_wrong_data(sig, signer):
    test_data = b'hello world'
    signature = sig.sign(signer, test_data)

    with pytest.raises(SigError, match='Could not verify signature'):
        sig.verify(signature, test_data + b'more')



def test_verify_unknown_signer(sig, signer):
    test_data = b'hello world'
    signature = sig.sign(signer, test_data)

    sig_2 = SignifySigContext(sig.key_dir)
    with pytest.raises(SigError, match='Unrecognized signer'):
        sig_2.verify(signature, test_data)


def test_export_import_key(sig, signer):
    pubkey = sig.get_pubkey(signer)

    test_data = b'hello world'
    signature = sig.sign(signer, test_data)

    sig_2 = SignifySigContext(sig.key_dir)

    signer_2 = sig_2.add_pubkey(pubkey)
    assert signer_2 == signer
    assert sig_2.verify(signature, test_data) == signer


def test_copy_and_import(sig, signer, other_signer):
    pubkey = sig.get_pubkey(signer)
    pubkey2 = sig.get_pubkey(other_signer)

    g1 = SignifySigContext(sig.key_dir)
    assert g1.add_pubkey(pubkey) == signer
    assert signer in g1.signers

    g2 = g1.copy()
    assert g2.add_pubkey(pubkey2) == other_signer
    assert other_signer in g2.signers
    assert other_signer not in g1.signers


def test_find(sig, signer):
    found = sig.find(signer)
    pubkey = sig.get_pubkey(signer)
    assert found == (signer, pubkey)
