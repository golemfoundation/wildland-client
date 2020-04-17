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

# TODO pylint: disable=missing-docstring

import json
from pathlib import Path

import jsonschema

from ..exc import WildlandError


PROJECT_PATH = Path(__file__).resolve().parents[2]
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
                prefix = '.'.join(map(str, error.absolute_path)) + ': '
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
