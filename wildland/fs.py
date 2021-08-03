# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Wildland Filesystem
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass

import fuse

from .fs_base import WildlandFSBase, Timespec
from .fuse_utils import debug_handler
from .log import init_logging
from .control_server import ControlHandler
from .log import get_logger

fuse.fuse_python_api = 0, 2
logger = get_logger('fuse')


@dataclass
class Watch:
    """
    A watch added by a connected user.
    """

    id: int
    storage_id: int
    pattern: str
    handler: ControlHandler

    def __str__(self):
        return f"{self.storage_id}:{self.pattern}"


class WildlandFS(WildlandFSBase, fuse.Fuse):
    """A FUSE implementation of Wildland"""
    # pylint: disable=no-self-use,too-many-public-methods

    def __init__(self, *args, **kwds):
        # this is before cmdline parsing
        super().__init__(*args, **kwds)
        # Note that we need this intermediate class because
        # parser apparently uses some reflection approach
        # which enters infinite recursion in multiple inheritance
        # scenario.
        self.parser.add_option(mountopt='log', metavar='PATH',
                               help='path to log file, use - for stderr')

        self.parser.add_option(mountopt='socket', metavar='SOCKET',
                               help='path to control socket file')

        self.parser.add_option(mountopt='breakpoint', action='store_true',
                               help='enable .control/breakpoint')

        self.parser.add_option(mountopt='single_thread', action='store_true',
                               help='run single-threaded')

        self.parser.add_option(mountopt='default_user', help='override default_user')

        self.install_debug_handler()

        # Disable file caching, so that we don't have to report the right file
        # size in getattr(), for example for auto-generated files.
        # See 'man 8 mount.fuse' for details.
        self.fuse_args.add('direct_io')

        # allow nonempty mount_dir (due to some operating systems insisting on putting random files
        # in every directory); this is not destructive and, worst case scenario, leads to confusion
        self.fuse_args.add('nonempty')

        with open("/etc/fuse.conf", "r") as fd:
            parsed_config = [c for c in fd.read().splitlines()
                             if c and not c.startswith('#')]

        re_can_mount = re.compile("[ \t]*user_allow_other")
        if list(filter(re_can_mount.match, parsed_config)):
            self.fuse_args.add('allow_other')

    def getattr(self, path):
        return self._mapattr(super().getattr(path))

    def fgetattr(self, path, *args):
        return self._mapattr(super().fgetattr(path, *args))

    def readdir(self, path, _offset):
        return [fuse.Direntry(name) for name in super().readdir(path, _offset)]

    def utimens(self, path: str, atime: fuse.Timespec, mtime: fuse.Timespec):
        return super().utimens(path, self._maptimespec(atime),
                                   self._maptimespec(mtime))

    def main(self, args=None):
        # this is after cmdline parsing
        self.uid, self.gid = os.getuid(), os.getgid()

        self.init_logging(self.cmdline[0])

        self.multithreaded = not self.cmdline[0].single_thread
        self.default_user = self.cmdline[0].default_user

        if not self.cmdline[0].breakpoint:
            self.control_breakpoint = None

        super().main(args)

    def init_logging(self, args):
        """
        Configure logging module.
        """

        log_path = args.log or '/tmp/wlfuse.log'
        if log_path == '-':
            init_logging(console=True)
        else:
            init_logging(console=False, file_path=log_path)


    def install_debug_handler(self):
        """Decorate all python-fuse entry points"""
        for name in fuse.Fuse._attrs:
            if hasattr(self, name):
                method = getattr(self, name)
                setattr(self, name, debug_handler(method, bound=True))

    @staticmethod
    def _mapattr(stat: os.stat_result) -> fuse.Stat:
        return fuse.Stat(
            st_mode=stat.st_mode,
            st_nlink=stat.st_nlink,
            st_uid=stat.st_uid,
            st_gid=stat.st_gid,
            st_size=stat.st_size,
            st_atime=stat.st_atime,
            st_mtime=stat.st_mtime,
            st_ctime=stat.st_ctime,
        )

    @staticmethod
    def _maptimespec(ts: fuse.Timespec) -> Timespec:
        return Timespec(
            name=ts.name,
            tv_sec=ts.tv_sec,
            tv_nsec=ts.tv_nsec
        )

    #
    # FUSE API
    #
    # pylint: disable=missing-docstring

    def fsinit(self):
        logger.info('mounting wildland')
        socket_path = Path(self.cmdline[0].socket or '/tmp/wlfuse.sock')
        self.control_server.start(socket_path)

    def fsdestroy(self):
        logger.info('unmounting wildland')
        self.control_server.stop()
        with self.mount_lock:
            for storage_id in list(self.storages):
                self._unmount_storage(storage_id)

def main():
    # pylint: disable=missing-docstring
    server = WildlandFS()
    server.parse(errex=1)
    server.main()


if __name__ == '__main__':
    main()
