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
import threading

from typing import Dict, Callable

import fuse


logger = logging.getLogger('fuse')

fuse_thread_local = threading.local()


def start_coverage():
    '''
    If we are running with coverage, start coverage from FUSE-created thread.
    '''

    if not threading.current_thread().name.startswith('Dummy'):
        return
    if hasattr(fuse_thread_local, 'coverage_started'):
        return

    try:
        # pylint: disable=import-outside-toplevel
        from coverage.control import Coverage
    except ImportError:
        return

    cov = Coverage.current()
    if not cov:
        return

    logger.debug('starting coverage')
    cov._collector._start_tracer()

    fuse_thread_local.coverage_started = True


def debug_handler(func, bound=False):
    '''A decorator for wrapping FUSE API.

    Helpful for debugging.
    '''
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        start_coverage()

        try:
            args_to_display = args if bound else args[1:]

            logger.debug('%s(%s)', func.__name__, ', '.join(itertools.chain(
                (debug_repr(i) for i in args_to_display),
                (f'{k}={v!r}' for k, v in kwds.items()))))

            ret = func(*args, **kwds)
            ret_repr = debug_repr(ret)
            if isinstance(ret, int) and ret < 0:
                logger.warning('%s → %s', func.__name__, ret_repr)
            else:
                logger.debug('%s → %s', func.__name__, ret_repr)
            return ret
        except OSError as err:
            logger.warning('%s !→ %s %s', func.__name__,
                           errno.errorcode[err.errno],
                           err.strerror)
            raise
        except NotImplementedError:
            logger.warning('%s !→ ENOSYS (NotImplementedError)', func.__name__)
            return -errno.ENOSYS
        except Exception:
            logger.exception('error while handling %s', func.__name__)
            return -errno.EINVAL
    return wrapper


def debug_repr(obj):
    '''
    Return a representation for FUSE operation result, for logging.
    '''

    if isinstance(obj, bytes):
        if len(obj) > 128:
            return f'<{len(obj)} bytes>'
        return repr(obj)

    if isinstance(obj, int):
        try:
            return '-' + errno.errorcode[-obj]
        except KeyError:
            return str(obj)

    if isinstance(obj, list):
        return '[{}]'.format(
            ', '.join(debug_repr(element) for element in obj))

    if isinstance(obj, fuse.Direntry):
        return fuse_repr(obj)

    if isinstance(obj, fuse.Stat):
        return fuse_repr(obj)

    return repr(obj)


def fuse_repr(obj):
    '''
    Return a nice representation for a FUSE object.
    '''

    fmt: Dict[str, Callable]

    if isinstance(obj, fuse.Direntry):
        name = 'fuse.Direntry'
        fmt = {
            'name': repr,
            'offset': str,
            'type': str,
            'ino': str
        }
    elif isinstance(obj, fuse.Stat):
        name = 'fuse.Stat'
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
    else:
        assert False, obj
    attribs = []
    for key, formatter in fmt.items():
        value = getattr(obj, key)
        if value is not None and value != 0:
            attribs.append('{}={}'.format(key, formatter(value)))
    return '{}({})'.format(name, ', '.join(attribs))


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
