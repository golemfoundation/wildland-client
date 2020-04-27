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

# pylint: disable=missing-docstring,redefined-outer-name

from pathlib import Path

import pytest

from ..resolve import WildlandPath, PathError


def test_path_from_str():
    wlpath = WildlandPath.from_str(':/foo/bar')
    assert wlpath.signer is None
    assert wlpath.parts == [Path('/foo/bar')]

    wlpath = WildlandPath.from_str('0xabcd:/foo/bar:/baz/quux')
    assert wlpath.signer == '0xabcd'
    assert wlpath.parts == [Path('/foo/bar'), Path('/baz/quux')]


def test_path_from_str_fail():
    with pytest.raises(PathError, match='has to start with signer'):
        WildlandPath.from_str('/foo/bar')

    with pytest.raises(PathError, match='Unrecognized signer field'):
        WildlandPath.from_str('foo:/foo/bar')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:foo/bar')

    with pytest.raises(PathError, match='Unrecognized absolute path'):
        WildlandPath.from_str('0xabcd:')


def test_path_to_str():
    wlpath = WildlandPath('0xabcd', [Path('/foo/bar')])
    assert str(wlpath) == '0xabcd:/foo/bar'

    wlpath = WildlandPath(None, [Path('/foo/bar'), Path('/baz/quux')])
    assert str(wlpath) == ':/foo/bar:/baz/quux'
