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
Synthetic storage, which services :path:`/.control` directory
'''

from functools import partial
import errno

from .base import StorageBackend
from .generated import GeneratedStorageMixin, CachedDirEntry, FuncFileEntry


class ControlStorageBackend(GeneratedStorageMixin, StorageBackend):
    '''Control pseudo-storage'''

    def __init__(self, fs):
        super().__init__()
        self.fs = fs
        self.root = CachedDirEntry('.', partial(self._get_obj_entries, fs))

    @classmethod
    def cli_options(cls):
        raise NotImplementedError()

    @classmethod
    def cli_create(cls, data):
        raise NotImplementedError()

    def get_root(self):
        return self.root

    def refresh(self):
        self.root.refresh()

    def _get_obj_entries(self, obj):
        for name, node in self.node_list(obj):
            if getattr(node, '_control_directory', True) or not hasattr(node, '_control_directory'):
                yield CachedDirEntry(name, partial(self._get_obj_entries, node))
            elif node._control_read:
                yield FuncFileEntry(name, on_read=node)
            else:
                assert node._control_write
                yield FuncFileEntry(name, on_write=node)

    @staticmethod
    def node_list(obj):
        '''
        List a node which is a directory

        The result is undefined if the node is not an actual control node
        '''
        try:
            obj._control_directory

        except AttributeError:
            for attr in dir(obj):
                try:
                    attr = getattr(obj, attr)
                    name = getattr(attr, '_control_name')
                except AttributeError:
                    continue
                yield name, attr
            return

        if not obj._control_directory:
            raise OSError(errno.ENOTDIR, '')

        yield from obj()

    def truncate(self, path, length):
        pass
