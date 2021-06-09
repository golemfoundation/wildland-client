# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=missing-docstring,redefined-outer-name

from pathlib import Path
import tempfile

import pytest

from ..manifest.sig import SigError, SodiumSigContext


@pytest.fixture(scope='session')
def key_dir():
    with tempfile.TemporaryDirectory(prefix='wlsecret.') as d:
        yield Path(d)


@pytest.fixture(params=[SodiumSigContext])
def sig(key_dir, request):
    return request.param(key_dir)


@pytest.fixture
def owner(sig):
    owner, pubkey = sig.generate()
    sig.add_pubkey(pubkey)
    return owner


@pytest.fixture
def other_owner(sig):
    owner, pubkey = sig.generate()
    sig.add_pubkey(pubkey)
    return owner


def test_generate_keys(sig):
    owner, pubkey = sig.generate()

    assert sig.fingerprint(pubkey) == owner
    assert (sig.key_dir / f'{owner}.pub').exists()
    assert (sig.key_dir / f'{owner}.sec').exists()

    loaded_owner, loaded_pubkey = sig.load_key(owner)
    assert (loaded_owner, loaded_pubkey) == (owner, pubkey)

    sig.add_pubkey(loaded_pubkey, owner)

    assert sig.get_primary_pubkey(owner) == pubkey
    assert sig.is_private_key_available(owner)

    sig.remove_key(owner)

    with pytest.raises(SigError):
        sig.load_key(owner)

    assert not (sig.key_dir / f'{owner}.pub').exists()
    assert not (sig.key_dir / f'{owner}.sec').exists()


def test_verify(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    assert sig.verify(signature, test_data) == owner


def test_verify_key_not_loaded(sig):
    test_data = b'hello world'
    owner, _ = sig.generate()

    with pytest.raises(SigError):
        sig.sign(owner, test_data)

    # when local keys can be used, we can access the key (just for sign, not for encryption)
    sig.use_local_keys = True
    signature = sig.sign(owner, test_data)

    assert sig.verify(signature, test_data) == owner


def test_verify_wrong_data(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    with pytest.raises(SigError, match='Could not verify signature'):
        sig.verify(signature, test_data + b'more')


def test_verify_wrong_owner(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)
    signature = '0xaaa' + signature[4:]

    with pytest.raises(SigError, match='Public key not found'):
        sig.verify(signature, test_data)


def test_verify_unknown_owner(sig, owner):
    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    sig_2 = SodiumSigContext(sig.key_dir)
    with pytest.raises(SigError, match='Public key not found'):
        sig_2.verify(signature, test_data)


def test_pubkey_to_owner(sig):
    pubkey = \
        'RWSFTQBA3OKaC4EZCP8n7fz0PeeUuDOOwjxys/n7xOWkJG19mKu6bIGS/bWyV1eLB1zWhIuJtCCd4JnseOaEp/Q0'

    assert sig.fingerprint(pubkey) == \
           '0x57802d611b2f0226338a367513877a25980d730efd52b6d5127f90afe55c030d'


def test_export_import_key(sig, owner):
    pubkey = sig.get_primary_pubkey(owner)

    test_data = b'hello world'
    signature = sig.sign(owner, test_data)

    sig_2 = SodiumSigContext(sig.key_dir)

    owner_2 = sig_2.add_pubkey(pubkey)
    assert owner_2 == owner
    assert sig_2.verify(signature, test_data) == owner


def test_copy_and_import(sig, owner, other_owner):
    pubkey = sig.get_primary_pubkey(owner)
    pubkey2 = sig.get_primary_pubkey(other_owner)

    g1 = SodiumSigContext(sig.key_dir)
    assert g1.add_pubkey(pubkey) == owner
    assert owner in g1.keys

    g2 = g1.copy()
    assert g2.add_pubkey(pubkey2) == other_owner
    assert other_owner in g2.keys
    assert other_owner not in g1.keys


def test_load_key(sig, owner):
    found_owner, found_key = sig.load_key(owner)
    sig.add_pubkey(found_key)
    pubkey = sig.get_primary_pubkey(owner)
    assert (found_owner, found_key) == (owner, pubkey)


def test_multiple_pubkeys(sig, owner):
    additional_owner, additional_pubkey = sig.generate()
    _additional_owner2, additional_pubkey2 = sig.generate()

    sig.add_pubkey(additional_pubkey, owner)
    sig.add_pubkey(additional_pubkey2, owner)

    test_data = b'hello world'
    signature = sig.sign(additional_owner, test_data)

    possible_owners = sig.get_possible_owners(sig.verify(signature, test_data))

    assert {owner, additional_owner} == set(possible_owners)


def test_signing_multiple_keys(sig):
    primary_owner, primary_pubkey = sig.generate()
    additional_owner, additional_pubkey = sig.generate()

    sig.add_pubkey(primary_pubkey)
    sig.add_pubkey(additional_pubkey, primary_owner)

    del sig.private_keys[primary_owner]

    test_data = b'hello world'

    signature = sig.sign(primary_owner, test_data, only_use_primary_key=False)
    signer = sig.verify(signature, test_data)

    assert signer == additional_owner
    assert primary_owner in sig.get_possible_owners(signer)

    with pytest.raises(SigError, match='Secret key not found'):
        sig.sign(primary_owner, test_data, only_use_primary_key=True)


def test_check_if_key_available(sig):
    primary_owner, pubkey = sig.generate()
    additional_owner, additional_pubkey = sig.generate()

    private_file = sig.key_dir / f'{primary_owner}.sec'
    private_file.unlink()

    # keys not loaded
    assert not sig.is_private_key_available(primary_owner)
    assert not sig.is_private_key_available(additional_owner)

    # keys loaded
    sig.add_pubkey(pubkey)
    sig.add_pubkey(additional_pubkey)

    assert not sig.is_private_key_available(primary_owner)
    assert sig.is_private_key_available(additional_owner)


def test_encrypt(sig, owner):
    pubkey = sig.get_primary_pubkey(owner)

    test_data = b'hello world'

    enc_data, enc_keys = sig.encrypt(test_data, [pubkey])

    assert sig.decrypt(enc_data, enc_keys) == test_data


def test_encrypt_not_found(sig, owner):
    pubkey = sig.get_primary_pubkey(owner)

    test_data = b'hello world'

    enc_data, enc_keys = sig.encrypt(test_data, [pubkey])

    del sig.private_keys[owner]

    with pytest.raises(SigError):
        sig.decrypt(enc_data, enc_keys)


def test_encrypt_mangled(sig, owner):
    pubkey = sig.get_primary_pubkey(owner)

    test_data = b'hello world'

    _, enc_keys = sig.encrypt(test_data, [pubkey])
    enc_data_2, _ = sig.encrypt(test_data, [pubkey])

    with pytest.raises(SigError):
        sig.decrypt(enc_data_2, enc_keys)


def test_encrypt_multiple_owners(sig):
    owner, pubkey = sig.generate()
    _, additional_pubkey = sig.generate()

    sig.add_pubkey(pubkey)
    sig.add_pubkey(additional_pubkey)

    test_data = b'hello world'

    enc_data, enc_keys = sig.encrypt(test_data, [pubkey, additional_pubkey])

    assert len(enc_keys) == 2

    (sig.key_dir / f'{owner}.sec').unlink()

    assert sig.decrypt(enc_data, enc_keys) == test_data
    assert sig.decrypt(enc_data, [enc_keys[1], enc_keys[0]]) == test_data

def test_sig_key_validity(sig):
    _, pubkey = sig.generate()

    assert sig.is_valid_pubkey(pubkey)

    # Remove a few bytes
    bogus = pubkey[0:len(pubkey)-3]

    assert not sig.is_valid_pubkey(bogus)
