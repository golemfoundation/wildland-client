# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Dispatch for built-in and added storage types.
"""

from typing import Dict, Type
import logging
import entrypoints

from .base import StorageBackend


def load_backends() -> Dict[str, Type[StorageBackend]]:
    """
    Load StorageBackend classes.
    """

    result = {}
    for ep in entrypoints.get_group_all('wildland.storage_backends'):
        logging.debug('storage: %s', ep)
        cls: Type[StorageBackend] = ep.load()
        result[cls.TYPE] = cls

    if not result:
        raise ImportError(
            'No storage backends found. Please install the Python packages:\n'
            '  pip install -e . plugins/*\n'
        )

    return result


def get_storage_backends() -> Dict[str, Type[StorageBackend]]:
    """
    Return a list of supported StorageBackend classes.
    """

    return _backends


_backends = load_backends()
