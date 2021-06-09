# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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
General Wildland utility functions.
"""

import yaml


class DisallowDuplicateKeyLoader(yaml.SafeLoader):
    """
    Alternate Yaml loader that raises error on duplicate keys.
    """
    def construct_mapping(self, node, deep=False):
        mapping = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise yaml.YAMLError(f'Duplicate key {key} encountered')
            mapping.append(key)
        return super().construct_mapping(node, deep)


def load_yaml(stream):
    """
    Load a yaml data stream, raising yaml.YAMLError on duplicate keys
    (unlike pyYAML default behaviour).
    """
    return yaml.load(stream, Loader=DisallowDuplicateKeyLoader)


def load_yaml_all(stream):
    """
    Load a yaml data stream, which can consist of multiple yaml documents,
    raising yaml.YAMLError on duplicate keys (unlike pyYAML default behaviour).
    """
    return yaml.load_all(stream, Loader=DisallowDuplicateKeyLoader)
