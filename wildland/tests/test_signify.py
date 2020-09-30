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
def owner(sig):
    return sig.generate()[0]


@pytest.fixture(scope='session')
def other_owner(sig):
    return sig.generate()[0]


@pytest.fixture(scope='session')
def old_owner(sig):
    old_owner = '0x6f94c183df4865c16445'
    old_pubkey = '''\
untrusted comment: signify public key
RWTBZUjfg8GUbxnKZ1GUKveJjpjujEvSkXDaaWOyEWcI9vpZmmw9fbDG
'''
    old_privkey = '''\
untrusted comment: signify secret key
RWRCSwAAAABfzbTCuL45s/xXoWya590NMRDfqctndx3BZUjfg8GUb4Lbu6LnZuNih1iTc5CjbE6cIBYu9fiHShvRN+JdtQIeGcpnUZQq94mOmO6MS9KRcNppY7IRZwj2+lmabD19sMY=
'''
    public_file = sig.key_dir / f'{old_owner}.pub'
    private_file = sig.key_dir / f'{old_owner}.sec'

    public_file.write_text(old_pubkey)
    private_file.write_text(old_privkey)

    sig.owners[old_owner] = old_pubkey
    return old_owner

def test_pubkey_to_owner(sig):
    pubkey = '''\
untrusted comment: hello world
RWS/mJgf4GTLPY2+qOnPzWSYhlfP6nwH1fFwUFMlW52/tKx52pnWwoA0
'''
    sig_data = pubkey.splitlines()[1]
    assert base64.b64decode(sig_data)[:10] == b'\x45\x64\xbf\x98\x98\x1f\xe0\x64\xcb\x3d'

    assert sig.fingerprint(pubkey) == '0x3dcb64e01f9898bf6445'


def test_verify(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    assert sig.verify(signature, test_data) == owner


def test_verify_wrong_data(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    with pytest.raises(SigError, match='Could not verify signature'):
        sig.verify(signature, test_data + b'more')



def test_verify_unknown_owner(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    sig_2 = SignifySigContext(sig.key_dir)
    with pytest.raises(SigError, match='Public key not found'):
        sig_2.verify(signature, test_data)


def test_export_import_key(sig, owner):
    pubkey = sig.get_pubkey(owner)

    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    sig_2 = SignifySigContext(sig.key_dir)

    owner_2 = sig_2.add_pubkey(pubkey)
    assert owner_2 == owner
    assert sig_2.verify(signature, test_data) == owner


def test_copy_and_import(sig, owner, other_owner):
    pubkey = sig.get_pubkey(owner)
    pubkey2 = sig.get_pubkey(other_owner)

    g1 = SignifySigContext(sig.key_dir)
    assert g1.add_pubkey(pubkey) == owner
    assert owner in g1.owners

    g2 = g1.copy()
    assert g2.add_pubkey(pubkey2) == other_owner
    assert other_owner in g2.owners
    assert other_owner not in g1.owners


def test_find(sig, owner):
    found = sig.find(owner)
    pubkey = sig.get_pubkey(owner)
    assert found == (owner, pubkey)


def test_new_key_to_owner(sig):
    pubkey = '''RWS/mJgf4GTLPY2+qOnPzWSYhlfP6nwH1fFwUFMlW52/tKx52pnWwoA0'''

    assert base64.b64decode(pubkey)[:10] == b'\x45\x64\xbf\x98\x98\x1f\xe0\x64\xcb\x3d'

    assert sig.fingerprint(pubkey) == '0x3dcb64e01f9898bf6445'


def test_old_verify(sig, old_owner):
    test_data = b'hello world'
    signature = sig.sign(old_owner, test_data)

    assert sig.verify(signature, test_data) == old_owner


def test_old_find(sig, old_owner):
    found = sig.find(old_owner)
    pubkey = sig.get_pubkey(old_owner)
    assert found == (old_owner, pubkey)


def test_copy_and_import_old(sig, owner, old_owner):
    pubkey = sig.get_pubkey(owner)
    pubkey2 = sig.get_pubkey(old_owner)

    g1 = SignifySigContext(sig.key_dir)
    assert g1.add_pubkey(pubkey) == owner
    assert owner in g1.owners

    g2 = g1.copy()
    assert g2.add_pubkey(pubkey2) == old_owner
    assert old_owner in g2.owners
    assert old_owner not in g1.owners
