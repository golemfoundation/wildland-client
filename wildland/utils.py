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
from typing import Union

import click
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


def format_options_required_first(command: Union[click.Command, click.Group], ctx, formatter):
    """
    Get all options from command and write it to formatter. First it writes required options, then
    non-required
    """
    required_options = []
    non_required_options = []
    for param in command.get_params(ctx):
        record = param.get_help_record(ctx)
        if record is not None:
            if param.required:
                required_options.append(record)
            else:
                non_required_options.append(record)

    with formatter.section('Options'):
        if required_options:
            formatter.write_dl(required_options)
        if non_required_options:
            formatter.write_dl(non_required_options)


def format_command_options(self, ctx: click.Context,
                           formatter: click.HelpFormatter) -> None:
    """
    Handles help message formatting (first displays required options).
    """

    format_options_required_first(self, ctx, formatter)


def format_multi_command_options(self, ctx: click.Context,
                                 formatter: click.HelpFormatter) -> None:
    """
    Handles help message formatting (first displays required options).
    """

    format_options_required_first(self, ctx, formatter)
    self.format_commands(ctx, formatter)
