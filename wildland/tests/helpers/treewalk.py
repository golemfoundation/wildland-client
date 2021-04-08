# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Patryk Bęza <patryk@wildland.io>
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

"""
Misc testing helper functions for traversing directory tree
"""

from pathlib import Path
from typing import Iterable, List


def walk_all(path: Path) -> List[str]:
    """
    Return a list of all directories and files from the given path. Items in each directory are
    sorted alphabetically.
    """
    return list(_walk_all(path, path))

def _walk_all(root, path) -> Iterable[str]:
    for sub_path in sorted(path.iterdir()):
        if sub_path.is_dir():
            yield str(sub_path.relative_to(root)) + '/'
            yield from _walk_all(root, sub_path)
        else:
            yield str(sub_path.relative_to(root))
