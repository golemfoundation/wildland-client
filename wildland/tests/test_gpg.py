# pylint: disable=missing-docstring,redefined-outer-name

import pytest

from ..sig import SigError


def test_verify(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    print(signature)

    gpg_sig.verify(signer, signature, test_data)


def test_verify_wrong_data(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    with pytest.raises(SigError, match='Could not verify signature'):
        gpg_sig.verify(signer, signature, test_data + b'more')


def test_verify_wrong_signer(gpg_sig, signer, other_signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

    with pytest.raises(SigError, match='Wrong key for signature'):
        gpg_sig.verify(other_signer, signature, test_data)


def test_verify_unknown_signer(gpg_sig):
    with pytest.raises(SigError, match='Unknown signer'):
        gpg_sig.verify('unknown-signer', 'any-signature', 'test data')
