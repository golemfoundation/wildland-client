# pylint: disable=missing-docstring


import pytest

from ..schema import Schema, SchemaError


TEST_UUID = '85ab42ce-c087-4c80-8bf1-197b44235287'


def container():
    return {
        'signer': 'user',
        'uuid': TEST_UUID,
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
    c['uuid'] = 'not uuid'
    with pytest.raises(SchemaError, match=r"uuid: .* does not match"):
        schema.validate(c)

    c = container()
    c['paths'].clear()
    with pytest.raises(SchemaError, match=r"paths: \[\] is too short"):
        schema.validate(c)
