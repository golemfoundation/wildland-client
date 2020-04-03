#
# (c) 2020 Wojtek Porczyk <woju@invisiblethingslab.com>
#

import errno
import functools
import itertools
import logging
import os
import sys

def debug_handler(func, bound=False):
    '''A decorator for wrapping FUSE API.

    Helpful for debugging.
    '''
    @functools.wraps(func)
    def wrapper(*args, **kwds):
        try:
            args_to_display = args if bound else args[1:]

            logging.debug('%s(%s)', func.__name__, ', '.join(itertools.chain(
                (repr(i) for i in args_to_display),
                (f'{k}={v!r}' for k, v in kwds.items()))))

            ret = func(*args, **kwds)
            if isinstance(ret, int):
                try:
                    ret_repr = '-' + errno.errorcode[-ret]
                except KeyError:
                    ret_repr = str(ret)
            else:
                ret_repr = repr(ret)
            logging.debug('%s → %s', func.__name__, ret_repr)
            return ret
        except OSError as err:
            logging.debug('%s !→ %s', func.__name__, err)
            raise
        except Exception:
            logging.exception('error while handling %s', func.__name__)
            raise
    return wrapper

# stolen from python-fuse/example/xmp.py
_FLAGS_TO_MODE = {os.O_RDONLY: 'rb', os.O_WRONLY: 'wb', os.O_RDWR: 'wb+'}

def flags_to_mode(flags):
    mode = _FLAGS_TO_MODE[flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)]
    if flags | os.O_APPEND:
        mode = mode.replace('w', 'a', 1)
    return mode

class Tracer:
    def __init__(self, current_frame):
        self.current_frame = current_frame
        self.run = True

    @classmethod
    def breakpointhook(cls):
        # pylint: disable=protected-access
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
