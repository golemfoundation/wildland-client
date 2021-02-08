# A Sphinx extension to generate a compact description based on JSON Schema.
# Supports a small subset, but can be expanded if necessary.

from pathlib import Path
import json
from docutils import nodes
from docutils.parsers.rst import Directive


class SchemaDirective(Directive):
    has_content = True

    def run(self):
        content = ''.join(self.content)
        file_name, *keys = content.split()
        file_path = self._path(file_name)
        assert file_path.exists(), f'not found: {file_path}'

        schema = json.loads(file_path.read_bytes())
        for key in keys:
            schema = schema[key]

        prop_list = self._prop_list(schema)
        if prop_list:
            return [prop_list]
        return []

    def _prop_list(self, definition, prefix=''):
        required = definition.get('required', [])
        properties = definition.get('properties', {})

        prop_list = nodes.bullet_list()
        for key, sub_definition in properties.items():
            is_required = key in required
            for item in self._describe(key, sub_definition, prefix=prefix,
                                       is_required=is_required):
                prop_list += item
        if prop_list.children:
            return prop_list
        return None

    def _describe(self, key, definition, prefix='', is_required=False):
        item = nodes.list_item()

        item += nodes.literal(text=prefix + key)
        qualifiers = []

        if is_required:
            qualifiers.append('required')

        if '$ref' in definition:
            ref_desc = self._resolve_ref(definition['$ref'])
            if ref_desc:
                qualifiers.append(ref_desc)

        if 'type' in definition:
            type_desc = definition['type']
            if isinstance(type_desc, list):
                type_desc = ' or '.join(type_desc)
            qualifiers.append(type_desc)

        if qualifiers:
            item += nodes.inline(text=' ({})'.format(
                ', '.join(qualifiers)))

        if 'description' in definition:
            desc = definition['description']
            item += nodes.inline(text=f': {desc}')

        # Nested properties
        if definition.get('properties'):
            sub_prefix = f'{prefix}{key}.'
            item += self._prop_list(definition, sub_prefix)

        # Nested properties for array items
        if definition.get('items') and definition['items'].get('properties'):
            sub_prefix = f'{prefix}{key}[].'
            item += self._prop_list(definition['items'], sub_prefix)

        yield item

    @staticmethod
    def _path(file_name):
        return Path(__file__).parent / '../wildland/schemas' / file_name.replace('/schemas/', '')

    def _resolve_ref(self, ref):
        file_name, _, path = ref.partition('#')
        if not file_name:
            return None

        file_path = self._path(file_name)
        if not file_path.exists:
            return None

        schema = json.loads(file_path.read_bytes())
        for part in path.split('/'):
            if part not in schema:
                return None
            schema = schema[part]

        return schema.get('description')


def setup(app):
    app.add_directive("schema", SchemaDirective)

    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
