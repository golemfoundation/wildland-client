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


def test_write_new_file():
    buf = Buffer(size=0, page_size=4)

    buf.write(b'ab', 0)
    assert buf.pages == {0: bytearray(b'ab\0\0')}
    assert buf.size == 2

    buf.write(b'cdef', 2)
    assert buf.pages == {
        0: bytearray(b'abcd'),
        1: bytearray(b'ef\0\0'),
    }
    assert buf.size == 6

    buf.write(b'g', 1)
    assert buf.pages == {
        0: bytearray(b'agcd'),
        1: bytearray(b'ef\0\0'),
    }
    assert buf.size == 6


def test_set_read():
    buf = Buffer(size=10, page_size=4)
    buf.set_read(b'abcdef', 8, 4)
    assert buf.pages == {
        1: bytearray(b'abcd'),
        2: bytearray(b'ef\0\0'),
    }


def test_get_needed_ranges():
    buf = Buffer(size=11, page_size=2)
    buf.pages = {
        0: bytearray(2),
        1: bytearray(2),
        4: bytearray(2),
    }
    assert buf.get_needed_ranges(16, 3) == [
        (2, 4),
        (2, 6),
        (2, 10),
    ]


def test_read():
    buf = Buffer(size=10, page_size=4)
    buf.pages = {
        0: bytearray(b'abcd'),
        1: bytearray(b'efgh'),
        2: bytearray(b'ij\0\0'),
    }
    assert buf.read(5, 3) == b'defgh'
    assert buf.read(10, 3) == b'defghij'


def test_truncate():
    buf = Buffer(size=10, page_size=4)
    buf.pages = {
        0: bytearray(b'abcd'),
        1: bytearray(b'efgh'),
        2: bytearray(b'ij\0\0'),
    }
    buf.truncate(9)
    assert buf.size == 9
    assert 2 in buf.pages
    buf.truncate(8)
    assert buf.size == 8
    assert 2 not in buf.pages


def test_get_dirty_data():
    buf = Buffer(size=10, page_size=4)
    buf.pages = {
        0: bytearray(b'abcd'),
        1: bytearray(b'efgh'),
        2: bytearray(b'ij\0\0'),
    }
    buf.write(b'AB', 0)
    buf.write(b'JKLMN', 9)
    assert buf.size == 14
    assert buf.dirty == {0, 2, 3}

    assert buf.get_dirty_data() == [
        (b'ABcd', 0),
        (b'iJKL', 8),
        (b'MN', 12)
    ]
