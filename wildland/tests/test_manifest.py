# pylint: disable=missing-docstring

import pytest

from ..manifest import Manifest, Header, ManifestError


def make_header(gpg_sig, signer, test_data):
    signature = gpg_sig.sign(signer, test_data, passphrase='secret')
    header = Header(signature.strip())
    return header.to_bytes()


def test_parse(gpg_sig, signer):
    test_data = f'''
signer: "{signer}"
key1: value1
key2: "value2"
'''.encode()

    data = make_header(gpg_sig, signer, test_data) + b'\n---\n' + test_data
    manifest = Manifest.from_bytes(data, gpg_sig)
    assert manifest.fields['signer'] == signer
    assert manifest.fields['key1'] == 'value1'
    assert manifest.fields['key2'] == 'value2'


def test_parse_wrong_signer(gpg_sig, signer):
    test_data = f'''
signer: other signer
key1: value1
key2: "value2"
'''.encode()
    data = make_header(gpg_sig, signer, test_data) + b'\n---\n' + test_data

    with pytest.raises(ManifestError, match='Signer field mismatch'):
        Manifest.from_bytes(data, gpg_sig)
