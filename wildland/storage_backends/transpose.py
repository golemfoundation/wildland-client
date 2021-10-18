# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                 Maja Kostacinska <maja@wildland.io>
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

"""
Transpose storage backend.
"""
import re
import ast
from typing import List, Union, Optional
from pathlib import PurePosixPath

import click

from .base import StorageBackend
from ..container import ContainerStub, Container
from ..manifest.schema import Schema
from ..client import Client
from ..exc import WildlandError

class Rule:
    """
    Helper rule class for applying the rules to the provided categories.
    """
    #pylint: disable=too-few-public-methods
    def __init__(self, rule: dict):
        self.content = rule

    def apply_rule(self, category: Optional[str], default: str):
        """
        Applies the chosen rule, either in accordance with the include
        or exclude scheme.
        """
        if default=='exclude':
            return self._exclude_apply_rule(category)

        return self._include_apply_rule(category)

    def _exclude_apply_rule(self, category: Optional[str]):
        if self.content.get('match-with', None)==str(category):
            if 'replace-with' in self.content:
                return True, self.content['replace-with']
            if 'exclude' in self.content:
                return True, None

        if 'match-category-regex' in self.content and category is not None:
            pattern = re.compile(self.content['match-category-regex'])
            if pattern.search(category) is not None:
                return True, re.sub(pattern = self.content['match-category-regex'],
                                              repl = self.content['replace-with'],
                                              string = category)

        return False, category

    def _include_apply_rule(self, category: Optional[str]):
        # IMPORTANT:
        # when prioritizing include, the categories with changes performed on them
        # are automatically assumed to be included. This is because in case of the
        # 'first-apply' conflict resolution, whenever a category is modified, it will
        # no longer be checked against other rules.
        if self.content.get('match-with', None)==str(category):
            if 'replace-with' in self.content:
                return True, self.content['replace-with']
            if 'include' in self.content:
                return True, category

        if 'match-category-regex' in self.content and category is not None:
            pattern = re.compile(self.content['match-category-regex'])
            if pattern.search(category) is not None:
                return True, re.sub(pattern = self.content['match-category-regex'],
                                              repl = self.content['replace-with'],
                                              string = category)

        return False, None

class TransposeStorageBackend(StorageBackend):
    """
    Transpose storage backend enabling the user to easily
    change the initial (automatically created) categories
    given to the subcontainers.

    When creating the object instance:
    1. First, the storage parameters for the inner container will be resolved
    (see Client.select_storage()),
    2. Then, the inner storage backend will be instantiated and passed as
    params['storage'] (see StorageBackend.from_params()).
    """

    SCHEMA = Schema({
        "type": "object",
        "required": ["reference-container", "rules", "conflict"],
        "properties": {
            "reference-container": {
                "$ref": "/schemas/types.json#reference-container",
                "description": ("Container to be used, either as URL or as an inlined manifest"),
            },
            "rules": {
                "description": ("Rules to be followed while modifying the subcontainer categories. "
                                "Each to be passed as a dictionary enclosed in single quotes. "
                                "e.g.: '{\"match-with\": \"/1\", \"replace-with\": \"/2\"}'" )
            },
            "conflict": {
                "type": "string",
                "description": ("Description of how to act when a conflict is encountered. "
                                "Should match one of the following values: first-apply, last-apply,"
                                " all-apply."),
                "oneOf":[
                    {"pattern": "first-apply"},
                    {"pattern": "last-apply"},
                    {"pattern": "all-apply"},
                ]
            }
        }
    })
    TYPE = 'transpose'

    def __init__(self, **kwds):
        super().__init__(**kwds)
        self.reference = self.params['storage']
        self.conflict = self.params.get('conflict')
        self.url = self.params['reference-container']

        self.rules = []
        rules = self.params.get('rules', [])
        for rule in rules:
            self.rules.append(Rule(rule))

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'],
                         help='URL for inner container manifest', required=True, metavar='URL'),
            click.Option(['--conflict'],
                         help='''Explanation of what to do in case the given rules
                                 are conflicting (first-apply/last-apply/all-apply)''',
                         required=True, default='first-apply'),
            click.Option(['--rules'],
                         help="""The rules to follow when modifying the initial categories.
                                 Each to be passed as a dictionary enclosed in single quotes,
                                 e.g.: '{"match-with": "/1", "replace-with": "/2"}'
                                 Can be repeated.""",
                         required=True, multiple=True),
        ]

    @classmethod
    def cli_create(cls, data):
        rules = []
        try:
            for rule in list(data['rules']):
                rules.append(ast.literal_eval(rule))
        except SyntaxError as error:
            raise WildlandError('Could not parse rules: '+repr(error)
            +'\nExamples of syntatically correct rules can be found'
            ' in the Wildland documentation.') from error
        opts = {
            'reference-container': data['reference_container_url'],
            'conflict': data['conflict'],
            'rules': rules,
        }
        return opts

    def mount(self) -> None:
        self.reference.request_mount()

    def unmount(self) -> None:
        self.reference.request_unmount()

    def clear_cache(self) -> None:
        self.reference.clear_cache()

    @property
    def can_have_children(self) -> bool:
        return self.reference.can_have_children

    def get_children(self, client: Client = None, query_path: PurePosixPath = PurePosixPath('*'),):
        subcontainer_list = self.reference.get_children(client)

        for element in subcontainer_list:
            path = element[0]
            container = element[1]

            if isinstance(container, ContainerStub):
                new_categories = self.modify_categories(container.fields['categories'])

                yield PurePosixPath(path), \
                ContainerStub({
                'paths': container.fields['paths'],
                'title': container.fields['title'],
                'categories': new_categories,
                'backends': {'storage': [{
                    'type': 'delegate',
                    'reference-container':'wildland:@default:@parent-container:',
                    'subdirectory': container.fields['backends']['storage'][0]['subdirectory']
                    }]}
                })
            else:
                assert client is not None
                target_bytes = container.get_target_file()
                link_container = client.load_object_from_bytes(None,
                                                               target_bytes)

                if isinstance(link_container, Container) and  \
                        PurePosixPath(self.reference.params['container-path']) \
                        not in link_container.paths:
                    paths = []
                    categories: List[Union[str, None]] = []
                    for path in link_container.paths:
                        paths.append(str(path))
                    for category in link_container.categories:
                        categories.append(str(category))

                    new_categories = self.modify_categories(categories)
                    link_manifest = link_container.to_manifest_fields(False)

                    yield PurePosixPath(path), \
                    ContainerStub({
                        'paths': link_manifest.get('paths'),
                        'title': link_manifest.get('title'),
                        'categories': new_categories,
                        'backends': link_manifest.get('backends')
                    })

    def modify_categories(self, categories_list: List[Union[str, None]]) -> List[str]:
        """
        Given an initial list of categories extracted from the subcontainers
        of the reference-container, this method helps perform relevant
        modifications on them and returns a list of new categories to be
        assigned to the new subcontainers.
        """
        new_categories = []
        default = 'exclude'
        break_on_match = False

        # determines whether the categories should by excluded or included by default
        for rule in self.rules:
            if 'include' in rule.content and self.conflict=='first-apply':
                default = 'include'
                break

            if 'include' in rule.content:
                default = 'include'
            elif 'exclude' in rule.content:
                default = 'exclude'

        # determines whether or not to break on match and whether the rule list should
        # be iterated backwards
        if self.conflict=='first-apply':
            break_on_match = True
        elif self.conflict=='last-apply':
            break_on_match = True
            self.rules.reverse()

        for category in categories_list:
            for rule in self.rules:
                matched, new_category = rule.apply_rule(category, default)

                if matched and break_on_match:
                    if new_category is not None:
                        new_categories.append(new_category)
                    category = None
                    break

                category = new_category

            if category is not None:
                new_categories.append(category)

        return new_categories

    def open(self, path: PurePosixPath, flags: int):
        return self.reference.open(path, flags)

    def getattr(self, path: PurePosixPath):
        return self.reference.getattr(path)

    def readdir(self, path: PurePosixPath):
        return self.reference.readdir(path)
