import tempfile
import shutil

import pytest

from ..sig import GpgSigContext, SigError

# pylint: disable=redefined-outer-name


# The following fixtures are session-scoped for performance reasons (generating
# keys takes time).

@pytest.fixture(scope='session')
def gpg_sig():
    home_dir = tempfile.mkdtemp(prefix='wlgpg.')
    try:
        yield GpgSigContext(home_dir)
    finally:
        shutil.rmtree(home_dir)

@pytest.fixture(scope='session')
def signer(gpg_sig):
    keyid = gpg_sig.gen_test_key(passphrase='secret')
    gpg_sig.add_signer('signer', keyid)
    return 'signer'


@pytest.fixture(scope='session')
def other_signer(gpg_sig):
    keyid = gpg_sig.gen_test_key(passphrase='secret')
    gpg_sig.add_signer('other_signer', keyid)
    return 'other_signer'


def test_verify(gpg_sig, signer):
    test_data = b'hello world'
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')

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
