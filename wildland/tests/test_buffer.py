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

# pylint: disable=missing-docstring,redefined-outer-name,unused-argument

'''
Tests for Buffer class
'''

from ..storage_backends.buffered import Buffer

def test_get_needed_range():
    buf = Buffer(size=11, page_size=2, max_pages=10)
    buf.pages = {
        0: bytearray(2),
        1: bytearray(2),
        4: bytearray(2),
    }

    # all pages present
    assert buf.get_needed_range(3, 1) is None

    # need pages 2..3
    assert buf.get_needed_range(6, 1) == (4, 4)
    assert buf.get_needed_range(7, 1) == (4, 4)

    # need pages 2..4, but 4 is loaded
    assert buf.get_needed_range(8, 1) == (4, 4)
    assert buf.get_needed_range(9, 1) == (4, 4)

    # need pages 2..5
    # (even though page 4 is loaded)
    assert buf.get_needed_range(8, 3) == (8, 4)
    assert buf.get_needed_range(8, 3) == (8, 4)
    assert buf.get_needed_range(999, 3) == (8, 4)


def test_read():
    buf = Buffer(size=10, page_size=4, max_pages=10)
    buf.pages = {
        0: bytearray(b'abcd'),
        1: bytearray(b'efgh'),
        2: bytearray(b'ij\0\0'),
    }
    assert buf.read(5, 3) == b'defgh'
    assert buf.read(10, 3) == b'defghij'
    assert buf.read(None, 0) == b'abcdefghij'
    assert buf.read(None, 2) == b'cdefghij'


def test_set_read_trim():
    buf = Buffer(size=10, page_size=4, max_pages=2)
    buf.set_read(b'abcd', 4, 0)
    buf.set_read(b'efgh', 4, 4)
    buf.set_read(b'ij\0\0', 4, 8)

    assert len(buf.pages) == 3

    assert buf.read(5, 3) == b'defgh'
    assert len(buf.pages) == 2
    assert 2 not in buf.pages
