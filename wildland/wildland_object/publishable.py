# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#   Michał Kluczek <michal@wildland.io>
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
Abstract class used by Wildland Objects can be published (ie. Users, Containers, Bridges, etc).
"""
import abc
from typing import List
from pathlib import PurePosixPath


class Publishable(metaclass=abc.ABCMeta):
    """
    An interface for Wildland Objects that can be published
    """
    @abc.abstractmethod
    def get_unique_publish_id(self) -> str:
        """
        Return unique id for publishable object. In most cases it's going to be an uuid of
        the manifest while User object, for example, may return user's signature.
        """

    @abc.abstractmethod
    def get_primary_publish_path(self) -> PurePosixPath:
        """
        Return primary path where the manifest is going to be published, by convention it's
        a path that starts with /.uuid/
        """

    @abc.abstractmethod
    def get_publish_paths(self) -> List[PurePosixPath]:
        """
        Return all paths where the manifest is going to be published (that shall always return
        primary publish path, among others)
        """
