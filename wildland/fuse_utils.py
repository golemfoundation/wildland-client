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

'''
Assorted helpers for handling FUSE API
'''

import errno
import functools
import itertools
import logging
import os
import sys

import fuse


logger = logging.getLogger('fuse')

def debug_handler(func, bound=False):
    '''A decorator for wrapping FUSE API.

    Helpful for debugging.
    '''
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        try:
            args_to_display = args if bound else args[1:]

            logger.debug('%s(%s)', func.__name__, ', '.join(itertools.chain(
                (repr(i) for i in args_to_display),
                (f'{k}={v!r}' for k, v in kwds.items()))))

            ret = func(*args, **kwds)
            ret_repr = debug_repr(ret)
            logger.debug('%s → %s', func.__name__, ret_repr)
            return ret
        except OSError as err:
            logger.debug('%s !→ %s', func.__name__, err)
            raise
        except Exception:
            logger.exception('error while handling %s', func.__name__)
            raise
    return wrapper


def debug_repr(obj):
    '''
    Return a representation for FUSE operation result, for logging.
    '''

    if isinstance(obj, int):
        try:
            return '-' + errno.errorcode[-obj]
        except KeyError:
            return str(obj)

    if isinstance(obj, fuse.Stat):
        fmt = {
            'st_mode': oct,
            'st_ino': str,
            'st_dev': str,
            'st_nlink': str,
            'st_uid': str,
            'st_gid': str,
            'st_size': str,
            'st_atime': str,
            'st_mtime': str,
            'st_ctime': str,
        }
        attribs = []
        for key, formatter in fmt.items():
            value = getattr(obj, key)
            if value is not None and value != 0:
                attribs.append('{}={}'.format(key, formatter(value)))
        return 'fuse.Stat({})'.format(', '.join(attribs))

    return repr(obj)


# stolen from python-fuse/example/xmp.py
_FLAGS_TO_MODE = {os.O_RDONLY: 'rb', os.O_WRONLY: 'wb', os.O_RDWR: 'wb+'}

def flags_to_mode(flags):
    '''Convert binary flags for ``open(2)`` to *mode* in python's
    :func:`open`

    Args:
        flags (int): the flags
    Returns:
        str: the appropriate mode
    '''
    mode = _FLAGS_TO_MODE[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]
    if flags | os.O_APPEND:
        mode = mode.replace('w', 'a', 1)
    return mode

class Tracer:
    # pylint: disable=missing-docstring
    def __init__(self, current_frame):
        self.current_frame = current_frame
        self.run = True

    @classmethod
    def breakpointhook(cls):
        sys.settrace(cls(sys._getframe(1)))

    def __call__(self, frame, event, arg):
        if event == 'call' and frame.f_code.co_filename.startswith('/usr/lib/python3.7/logging'):
            return None
        logging.debug('tracer: %s %s %d %r %r',
            frame.f_code.co_filename, frame.f_code.co_name, frame.f_lineno,
            event, arg)
#       if frame is self.current_frame and event == 'return':
#           self.run = False
        return self if self.run else None
