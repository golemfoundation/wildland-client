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
Utilities
'''

import stat

import fuse


def simple_file_stat(size: int, timestamp: int) -> fuse.Stat:
    '''
    Create a fuse.Stat object for a regular file.
    '''

    return fuse.Stat(
        st_mode=stat.S_IFREG | 0o644,
        st_nlink=1,
        st_size=size,
        st_atime=timestamp,
        st_mtime=timestamp,
        st_ctime=timestamp,
        st_uid=None,
        st_gid=None,
    )


def simple_dir_stat(size: int = 0, timestamp: int = 0) -> fuse.Stat:
    '''
    Create a fuse.Stat object for a directory.
    '''

    return fuse.Stat(
        st_mode=stat.S_IFDIR | 0o755,
        st_nlink=1,
        st_size=size,
        st_atime=timestamp,
        st_mtime=timestamp,
        st_ctime=timestamp,
        st_uid=None,
        st_gid=None,
    )
