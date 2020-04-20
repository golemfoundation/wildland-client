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

# pylint: disable=missing-docstring


import pytest

from ..manifest.schema import Schema, SchemaError


def container():
    return {
        'signer': '0x3333',
        'paths': [
            '/home/photos',
        ],
        'backends': {
            'storage': [
                'storage1.yaml',
            ]
        }
    }


def test_validate():
    schema = Schema('container')
    schema.validate(container())


def test_validate_errors():
    schema = Schema('container')
    c = container()
    del c['signer']
    with pytest.raises(SchemaError, match=r"'signer' is a required property"):
        schema.validate(c)

    c = container()
    c['paths'].clear()
    with pytest.raises(SchemaError, match=r"paths: \[\] is too short"):
        schema.validate(c)
