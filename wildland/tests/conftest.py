

import tempfile
import shutil

import pytest

from ..sig import GpgSigContext

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
