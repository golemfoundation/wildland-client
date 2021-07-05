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

# pylint: disable=missing-docstring


import pytest

from ..manifest.schema import Schema, SchemaError


def container():
    return {
        'version': '1',
        'object': 'container',
        'owner': '0x3333',
        'paths': [
            '/home/photos',
        ],
        'backends': {
            'storage': [
                'file:///tmp/storage1.yaml',
            ]
        }
    }


def container_backends():
    return {
        'version': '1',
        'object': 'container',
        'owner': '0x3333',
        'paths': [
            '/home/photos',
        ],
        'backends': {
            'storage': [
                {'type': 'local',
                 'location': '/path',
                 'object': 'storage'
                 }
            ]
        }
    }


def container_access():
    return {
        'version': '1',
        'object': 'container',
        'owner': '0x3333',
        'paths': [
            '/home/photos',
        ],
        'backends': {
            'storage': [
                'file:///tmp/storage1.yaml',
            ]
        },
        "access": [
            {"user": '0x4444'}
        ]
    }


def user():
    return {
        'version': '1',
        'object': 'user',
        'owner': '0x3333',
        'paths': [
            '/Alice',
        ],
        'pubkeys': ['key.0x333'],
    }


def test_validate():
    schema = Schema('container')
    schema.validate(container())

    schema.validate(container_access())
    schema.validate(container_backends())

    c = container_access()
    c['access'][0]['user'] = '*'
    schema.validate(c)


def test_validate_errors():
    schema = Schema('container')

    c = container()
    del c['object']
    with pytest.raises(SchemaError, match=r"'object' is a required property"):
        schema.validate(c)

    c = container()
    del c['owner']
    with pytest.raises(SchemaError, match=r"'owner' is a required property"):
        schema.validate(c)

    c = container()
    c['paths'].clear()
    with pytest.raises(SchemaError, match=r"paths: \[\] is too short"):
        schema.validate(c)

    c = container()
    del c['version']
    with pytest.raises(SchemaError, match=r"'version' is a required property"):
        schema.validate(c)

    c = container()
    c['version'] = '2'
    with pytest.raises(SchemaError, match=r"'1' was expected"):
        schema.validate(c)

    c = container_access()
    c['access'].append({'user': '*'})
    with pytest.raises(SchemaError, match=r"not valid"):
        schema.validate(c)


def test_validate_user():
    schema = Schema('user')
    schema.validate(user())

    u = user()
    u['manifests-catalog'] = [container()]
    schema.validate(u)

    u['manifests-catalog'][0]['version'] = '2'
    with pytest.raises(SchemaError, match=r"not valid"):
        schema.validate(u)
