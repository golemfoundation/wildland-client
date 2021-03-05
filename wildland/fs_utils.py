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
Helpers for handling abstract FS APIs
"""

import os

# stolen from python-fuse/example/xmp.py
_FLAGS_TO_MODE = {os.O_RDONLY: 'rb', os.O_WRONLY: 'wb', os.O_RDWR: 'wb+'}

def flags_to_mode(flags):
    """Convert binary flags for ``open(2)`` to *mode* in python's
    :func:`open`

    Args:
        flags (int): the flags
    Returns:
        str: the appropriate mode
    """
    mode = _FLAGS_TO_MODE[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]
    if flags | os.O_APPEND:
        mode = mode.replace('w', 'a', 1)
    return mode
