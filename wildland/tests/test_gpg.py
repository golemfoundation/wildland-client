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

    gpg_sig_2 = GpgSigContext(gpg_sig.gnupghome)

    with pytest.raises(SigError, match='Unknown signer'):
        gpg_sig_2.verify(signature, test_data)


def test_verify_self_signed(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    gpg_sig_2 = GpgSigContext(gpg_sig.gnupghome)
    assert gpg_sig_2.verify(signature, test_data, self_signed=True) == signer


def test_find(gpg_sig, signer, other_signer):
    # pylint: disable=unused-argument

    assert gpg_sig.find(signer) == signer
    assert gpg_sig.find(signer.lower()) == signer
    assert gpg_sig.find('Test 1') == signer

    with pytest.raises(SigError, match='No key found'):
        gpg_sig.find('Someone Else')

    with pytest.raises(SigError, match='Multiple keys found'):
        gpg_sig.find('Test')
