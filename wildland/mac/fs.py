# An implementation of Wildland designed primarily for
# usage on Apple platform. Rather than assuming specific
# filesystem interface, like FUSE, we abstract out the
# needed functionality to an abstract driver, injected
# by hosting application, which provides the supported
# interface.

'''
Wildland Filesystem implementation intendet to work as
part of embedded Python installation. This class is
primarily used within the specialized NFS server.
'''

import logging
import os
from pathlib import Path
from .apple_log import apple_log
from ..fs_base import WildlandFSBase

logger = logging.getLogger('fs')

class WildlandMacFS(WildlandFSBase):
    '''
    An independent implementation of Wildland. Rather
    than assuming speficic filesystem driver (i.e. FUSE)
    '''

    def __init__(self, socket_path):
        super().__init__()
        self.socket_path = Path(socket_path)

    def start(self):
        '''
        Called to start file system operation.
        '''
        apple_log.configure()
        self.uid, self.gid = os.getuid(), os.getgid()
        logger.info('Wildland is starting, control socket: %s',
                        self.socket_path)
        self.control_server.start(self.socket_path)
