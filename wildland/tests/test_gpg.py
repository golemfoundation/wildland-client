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

import pytest

from ..manifest.sig import SigError, GpgSigContext


def test_verify(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    assert gpg_sig.verify(signature, test_data) == signer


def test_verify_wrong_data(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    with pytest.raises(SigError, match='Could not verify signature'):
        gpg_sig.verify(signature, test_data + b'more')


def test_verify_unknown_signer(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    with GpgSigContext(gpg_sig.gnupghome) as gpg_sig_2:
        with pytest.raises(SigError, match='Could not verify signature'):
            gpg_sig_2.verify(signature, test_data)


def test_export_import_key(gpg_sig, signer):
    pubkey = gpg_sig.get_pubkey(signer)

    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    with GpgSigContext(gpg_sig.gnupghome) as gpg_sig_2:
        signer_2 = gpg_sig_2.add_pubkey(pubkey)
        assert signer_2 == signer
        assert gpg_sig_2.verify(signature, test_data) == signer


def test_find(gpg_sig, signer, other_signer):
    # pylint: disable=unused-argument

    assert gpg_sig.find(signer)[0] == signer
    assert gpg_sig.find(signer.lower())[0] == signer
    assert gpg_sig.find('Test 1')[0] == signer

    with pytest.raises(SigError, match='No key found'):
        gpg_sig.find('Someone Else')

    with pytest.raises(SigError, match='Multiple keys found'):
        gpg_sig.find('Test')


def test_copy_and_import(gpg_sig, signer, other_signer):
    pubkey = gpg_sig.get_pubkey(signer)
    pubkey2 = gpg_sig.get_pubkey(other_signer)

    with GpgSigContext(gpg_sig.gnupghome) as g1:
        assert g1.add_pubkey(pubkey) == signer
        assert signer in g1.signers

        with g1.copy() as g2:
            assert g2.add_pubkey(pubkey2) == other_signer
            assert other_signer in g2.signers
            assert other_signer not in g1.signers
