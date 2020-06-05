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
from typing import Union
import pkg_resources

import jsonschema

from ..exc import WildlandError


COMMON_FILES = ['types.json', 'storage.schema.json']


def load_common_files():
    for name in COMMON_FILES:
        with pkg_resources.resource_stream('wildland', 'schemas/' + name) as f:
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
    def __init__(self, arg: Union[str, dict]):
        if isinstance(arg, str):
            path = f'schemas/{arg}.schema.json'
            with pkg_resources.resource_stream('wildland', path) as f:
                self.schema = json.load(f)
        else:
            self.schema = arg
        jsonschema.Draft4Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft4Validator(self.schema)
        self.validator.resolver.store.update(load_common_files())

    def validate(self, data):
        errors = list(self.validator.iter_errors(data))
        if errors:
            raise SchemaError(errors)
