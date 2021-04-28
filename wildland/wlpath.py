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

"""
Wildland path class
"""


from pathlib import PurePosixPath
from typing import List, Optional
import re


from .exc import WildlandError

WILDLAND_URL_PREFIX = 'wildland:'


class PathError(WildlandError):
    """
    Error in parsing or resolving a Wildland path.
    """


class WildlandPath:
    """
    A path in Wildland namespace.

    The path has the following form:

        [wildland:][owner][@hint]:(part:)+:[file_path]

    - owner (optional): owner determining the first container's namespace, if omitted @default
      will be used
    - hint (optional, requires owner): hint to the location of first container's namespace;
      takes the form of protocol[address], for example https{demo.wildland.io/demo.user.yaml}
    - parts: intermediate parts, identifying bridges or containers on the path
    - file_path (optional): path to file in the last container
    """

    ABSPATH_RE = re.compile(r'^/.*$')
    FINGERPRINT_RE = re.compile(r'^0x[0-9a-f]+$')
    ALIAS_RE = re.compile(r'^@[a-z-]+$')
    HINT_RE = re.compile(r'^0x[0-9a-f]+(@https{.*})')
    # if adding more protocols to hint, refactor to a separate WildlandHint class
    WLPATH_RE = re.compile(r'^(wildland:)?(0x[0-9a-f]+(@https{.*})?|@[a-z-]+)?:')

    def __init__(
        self,
        owner: Optional[str],
        hint: Optional[str],
        parts: List[PurePosixPath],
        file_path: Optional[PurePosixPath]
    ):
        assert len(parts) > 0
        self.owner = owner
        self.hint = hint
        self.parts = parts
        self.file_path = file_path

    @classmethod
    def match(cls, s: str) -> bool:
        """
        Check if a string should be recognized as a Wildland path.

        To be used when distinguishing Wildland paths from other identifiers
        (local paths, URLs).

        Note that this doesn't guarantee that the WildlandPath.from_str() will
        succeed in parsing the path.
        """

        return cls.WLPATH_RE.match(s) is not None

    @classmethod
    def from_str(cls, s: str) -> 'WildlandPath':
        """
        Construct a WildlandPath from a string.

        Accepts paths both with and without 'wildland:' protocol prefix.
        """
        if s.startswith(WILDLAND_URL_PREFIX):
            s = s[len(WILDLAND_URL_PREFIX):]

        if ':' not in s:
            raise PathError('The path has to start with owner and ":"')

        split = s.split(':')
        if split[0] == '':
            owner = None
            hint = None
        elif cls.FINGERPRINT_RE.match(split[0]) or cls.ALIAS_RE.match(split[0]):
            owner = split[0]
            hint = None
        elif cls.HINT_RE.match(split[0]):
            owner, hint = split[0].split('@', 1)
            hint = 'https://' + hint[6:-1]  # change the https{ ... } syntax to resolvable URL
        else:
            if '@https' in split[0] and '0x' not in split[0]:
                raise PathError('Hint field requires explicit owner: {!r}'.format(split[0]))
            raise PathError('Unrecognized owner field: {!r}'.format(split[0]))

        parts = []
        for part in split[1:-1]:
            if part != '*' and not cls.ABSPATH_RE.match(part):
                raise PathError('Unrecognized absolute path: {!r}'.format(part))
            parts.append(PurePosixPath(part))

        if split[-1] == '':
            file_path = None
        else:
            if not cls.ABSPATH_RE.match(split[-1]):
                raise PathError('Unrecognized absolute path: {!r}'.format(split[-1]))
            file_path = PurePosixPath(split[-1])

        if not parts:
            raise PathError(f'Path has no containers: {s!r}. Did you forget a ":" at the end?')

        return cls(owner, hint, parts, file_path)

    def __str__(self):
        s = ''
        if self.owner is not None:
            s += self.owner
        if self.hint is not None:
            s += '@' + 'https{' + self.hint[8:] + '}'
        s += ':' + ':'.join(str(p) for p in self.parts) + ':'
        if self.file_path is not None:
            s += str(self.file_path)
        return s
