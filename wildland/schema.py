# TODO pylint: disable=missing-docstring

import json
from pathlib import Path

import jsonschema

from .exc import WildlandError


PROJECT_PATH = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_PATH / 'schemas'
COMMON_FILES = ['types.json']


def load_common_files():
    for name in COMMON_FILES:
        with open(SCHEMA_PATH / name) as f:
            yield name, json.load(f)



class SchemaError(WildlandError):
    def __init__(self, errors):
        super().__init__()
        self.errors = errors

    def __str__(self):
        messages = []
        for error in self.errors:
            prefix = ''
            if error.absolute_path:
                prefix = '.'.join(error.absolute_path) + ': '
            messages.append('{}{}'.format(prefix, error.message))
        return '\n'.join(messages)


class Schema:
    def __init__(self, name: str):
        path = SCHEMA_PATH / f'{name}.schema.json'
        with open(path) as f:
            self.schema = json.load(f)
        jsonschema.Draft4Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft4Validator(self.schema)
        self.validator.resolver.store.update(load_common_files())

    def validate(self, data):
        errors = list(self.validator.iter_errors(data))
        if errors:
            raise SchemaError(errors)
