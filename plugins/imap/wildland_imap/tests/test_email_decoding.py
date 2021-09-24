# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Piotr K. Isajew <pki@ex.com.pl>
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
Unit tests for email decoding
"""
from ..ImapClient import _decode_text


def test_decode_nasty_subject():
    """
    test if we can decode a nasty subject with a lot of quoted-printable
    entities in it.
    """

    expected = 'GOLEM nie jest człowiekiem, więc nie ma ani osobowości, ani charakteru'
    inputs = [(b'GOLEM nie jest ', None), (b'cz\xc5\x82owiekiem', 'utf-8'),
              (b', wi\xc4\x99c nie ma ani osobowo\xc5\x9bci', 'utf-8'),
              (b', ani charakteru', None)]

    decoded = _decode_text(inputs)

    assert decoded == expected
