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


class YAMLParserError(yaml.YAMLError):
    """
    Base exception for YamlParser
    """


class DisallowDuplicateKeyLoader(yaml.SafeLoader):
    """
    Alternate Yaml loader that raises error on duplicate keys.
    """

    def construct_mapping(self, node, deep=False):
        mapping = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise YAMLParserError(f'Duplicate key {key} encountered')
            mapping.append(key)
        return super().construct_mapping(node, deep)


class FrozenAnchorsDict(dict):
    """
    Dict object preventing setitem.

    This is YAML oriented with anchors usage message when trying
    to set an item. This is to be used as a replacement of anchors
    attribute for a yaml.Loader instance.
    """

    def __setitem__(self, key, value):
        """
        Override dict setitem method in order to prevent any add of anchors
        """
        raise YAMLParserError(f"Anchor '{key}' encountered")


class DisallowAnchorAndDuplicateKeyLoader(DisallowDuplicateKeyLoader):
    """
    Alternate Yaml loader that raises error on duplicate keys and usage of anchors
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.anchors = FrozenAnchorsDict()


class YamlParser:
    """
    Yaml Parser on top of pyyaml
    """

    # We currently have only static methods. This could change in the future.

    @staticmethod
    def safe_load(data):
        """
        Parse the first YAML document in a stream
        and produce the corresponding Python object.

        Resolve only basic YAML tags. This is known
        to be safe for untrusted input.
        """
        return yaml.safe_load(data)

    @staticmethod
    def safe_load_all(data):
        """
        Parse all YAML documents in a stream
        and produce corresponding Python objects.

        Resolve only basic YAML tags. This is known
        to be safe for untrusted input.
        """
        return yaml.safe_load_all(data)

    @staticmethod
    def load(stream):
        """
        Load a yaml data stream, raising YAMLParserError on duplicate keys and anchors
        (unlike pyYAML default behaviour).
        """
        return yaml.load(stream, Loader=DisallowAnchorAndDuplicateKeyLoader)

    @staticmethod
    def load_all(stream):
        """
        Load a yaml data stream, which can consist of multiple yaml documents,
        raising YAMLParserError on duplicate keys and anchors (unlike pyYAML default behaviour).
        """
        return yaml.load_all(stream, Loader=DisallowAnchorAndDuplicateKeyLoader)

    @staticmethod
    def dump(data, stream=None, **kwargs):
        """
        Serialize a Python object into a YAML stream.
        If stream is None, return the produced string instead.
        """
        return yaml.dump(data, stream, **kwargs)

    @staticmethod
    def safe_dump(data, stream=None, **kwargs):
        """
        Serialize a Python object into a YAML stream.
        Produce only basic YAML tags.
        If stream is None, return the produced string instead.
        """
        return yaml.safe_dump(data, stream=stream, **kwargs)


yaml_parser = YamlParser()
