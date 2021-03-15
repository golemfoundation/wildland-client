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
from typing import Union, Dict
import pkg_resources

import jsonschema

from ..exc import WildlandError


COMMON_FILES = [
    'types.json',
    'storage.schema.json',
    'container.schema.json',
]


def load_common_files():
    for name in COMMON_FILES:
        with pkg_resources.resource_stream('wildland', 'schemas/' + name) as f:
            yield name, json.load(f)
            f.seek(0)
            yield '/schemas/' + name, json.load(f)



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
            messages.append('Expected {}'.format(readable_schema(error.schema)))
        return '\n'.join(messages)


def readable_schema(schema: dict) -> str:
    description = schema.get('description', '')
    if description:
        description = f" ({description})"
    if 'type' in schema:
        return schema['type'] + description
    if '$ref' in schema:
        pattern = schema['$ref']
        if pattern.endswith("#abs-path"):
            return 'an absolute path: must start with /'
        if pattern.endswith("#http-url"):
            return 'a http or https address: must start with http:// or https://'
        if pattern.endswith("#rel-path"):
            return 'a relative path: must begin with "./" or "../")'
        if pattern.endswith("#url") or pattern.endswith("#url-or-relpath"):
            if pattern.endswith("#url-or-relpath"):
                prefix = 'a relative path: must begin with "./" or "../") or '
            else:
                prefix = ''
            return prefix + 'any url: either HTTP(S), starting with http:// or https://; or ' \
                            'local file url, starting with file://; or Wildland URL, starting ' \
                            'with "wildland:" and containing at least three parts separated ' \
                            'by ":" (sample Wildland URLs: wildland::/data/books: or ' \
                            'wildland:@default:/data/books:/file.txt '
        if pattern.endswith("container.schema.json"):
            return 'complete container schema'
        if pattern.endswith("#version"):
            return 'manifest version'
        if pattern.endswith("#fingerprint"):
            return "key fingerprint (starting with 0x; if editing manifest manually, " \
                   "remember to quote the fingerprint)"
        if pattern.endswith("#encrypted"):
            return "encrypted data"
        if pattern.endswith("/storage-inline"):
            return "inline storage manifest, requiring at least 'type' field (and others, " \
                   "depending on type)"
        if pattern.endswith("#access"):
            return "access data: either 'user: \"*\"' for no encryption, or a list of users to " \
                   "be allowed access in the following format: 'user: \"0x...\"' "
        return schema.get('description', pattern)
    if 'oneOf' in schema:
        return ", or ".join([readable_schema(s) for s in schema['oneOf']])
    return description


class Schema:
    def __init__(self, arg: Union[str, dict]):
        if isinstance(arg, str):
            path = f'schemas/{arg}.schema.json'
            with pkg_resources.resource_stream('wildland', path) as f:
                self.schema = json.load(f)
        else:
            self.schema = arg
        jsonschema.Draft6Validator.check_schema(self.schema)
        self.validator = jsonschema.Draft6Validator(self.schema)
        self.validator.resolver.store.update(load_common_files())

    @classmethod
    def load_dict(cls, name: str, root_key: str) -> Dict[str, 'Schema']:
        """
        Load a dictionary of schemas from a file.
        """

        path = f'schemas/{name}'
        with pkg_resources.resource_stream('wildland', path) as f:
            data = json.load(f)
        return {
            key: cls(value)
            for key, value in data[root_key].items()
        }

    def validate(self, data):
        errors = list(self.validator.iter_errors(data))
        if errors:
            raise SchemaError(errors)
