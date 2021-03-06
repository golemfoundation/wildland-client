# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Marek Marczykowski-Górecki <marmarek@invisiblethingslab.com>,
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

# pylint: disable=missing-docstring,redefined-outer-name
import re


class PartialDict:
    """
    Compare only some dict keys.

    This allows a partial dict matching (with the main purpose of checking mocked calls parameters).
    Usage:
        p = PartialDict({'a': 'val1', 'b': 'val2'})
        actual == p  # will look only for actual['a'] and actual['b']

    """
    def __init__(self, values):
        self.dict = values

    def __repr__(self):
        return repr(self.dict)

    def __eq__(self, other):
        for key in self.dict:
            if key not in other:
                return False
            if self.dict[key] != other[key]:
                return False
        return True


class str_re:
    """
    Compare str to a regular expression.

    Usage:
        >>> s = str_re(r'abc.*x')
        >>> 'abcdefx' == s
        True
        >>> 'xxx' == s
        False
    """

    def __init__(self, pattern):
        self._re = re.compile(pattern)

    def __eq__(self, other):
        return bool(self._re.match(str(other)))

    def __repr__(self):
        return f'str_re({self._re.pattern})'
