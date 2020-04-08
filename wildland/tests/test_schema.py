# pylint: disable=missing-docstring


import pytest

from ..schema import Schema, SchemaError


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
