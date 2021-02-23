# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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

import pytest

from ..manifest.manifest import Manifest, ManifestError
from ..manifest.sig import DummySigContext


@pytest.fixture(scope='session')
def sig():
    return DummySigContext()


@pytest.fixture(scope='session')
def owner(sig):
    owner, pubkey = sig.generate()
    sig.add_pubkey(pubkey)
    return owner


def test_manifest_own_signer(sig, owner):
    test_data = f'''\
signature: |
  dummy.{owner}
---
owner: "{owner}"
paths:
- /test
pubkeys:
- key.0x999
'''.encode()

    manifest = Manifest.from_bytes(test_data, sig, allow_only_primary_key=True)
    assert manifest.fields['owner'] == owner
    assert sig.verify(manifest.header.signature, None) == owner

    manifest = Manifest.from_bytes(test_data, sig, allow_only_primary_key=False)
    assert manifest.fields['owner'] == owner
    assert sig.verify(manifest.header.signature, None) == owner


def test_manifest_other_signer(sig, owner):
    test_data = f'''\
signature: |
  dummy.0x999
---
owner: "{owner}"
paths:
- /test
pubkeys:
- key.0x999
'''.encode()

    with pytest.raises(ManifestError, match='Unknown'):
        Manifest.from_bytes(test_data, sig, allow_only_primary_key=True)

    with pytest.raises(ManifestError, match='Unknown'):
        Manifest.from_bytes(test_data, sig, allow_only_primary_key=False)

    # adding the pubkey should make a difference only when allow_only_primary_key is False
    sig.add_pubkey('key.0x999', owner)

    with pytest.raises(ManifestError, match='Manifest owner does not have access to signing key'):
        Manifest.from_bytes(test_data, sig, allow_only_primary_key=True)

    manifest = Manifest.from_bytes(test_data, sig, allow_only_primary_key=False)
    assert manifest.fields['owner'] == owner
    assert sig.verify(manifest.header.signature, None) == '0x999'
