# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
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

"""Pseudomanifest storage, handles .manifest.wildland.yaml files"""

import os
import stat
from itertools import chain
from pathlib import PurePosixPath
from typing import Optional, Dict, Any

from .base import StorageBackend, File, Attr
from ..manifest.manifest import Manifest
from ..manifest.schema import Schema


def _cli(*args):
    # pylint: disable=import-outside-toplevel,cyclic-import
    from ..cli import cli_main
    cmdline = ['--base-dir', os.environ['WL_BASE_DIR'], *args]
    # Convert Path to str
    cmdline = [str(arg) for arg in cmdline]
    try:
        cli_main.main.main(args=cmdline, prog_name='wl')
    except SystemExit as e:
        if e.code not in [None, 0]:
            if hasattr(e, '__context__'):
                assert isinstance(e.__context__, Exception)
                raise e.__context__


class PseudomanifestFile(File):
    """
    File for storing single pseudomanifest file.

    Only accepts selected modifications of: paths, categories and title.
    Incorrect changes are rejected and related error message are printed directly into manifest file
    as a comment.
    """

    def __init__(self, container_name: str, data: bytes, attr: Attr):
        self.container_name = container_name
        self.data = data
        self.cache: Optional[bytearray] = bytearray()
        self.cache[:] = data
        self.attr = attr
        self.attr.size = len(data)

    def read(self, length: Optional[int] = None, offset: int = 0) -> bytes:
        if length is None:
            length = self.attr.size - offset

        return bytes(self.cache)[offset:offset+length]

    def flush(self) -> None:
        try:
            new = Manifest.from_unsigned_bytes(self.cache)
            new.skip_verification()
            old = Manifest.from_unsigned_bytes(self.data)
            old.skip_verification()
        except Exception as e:
            message = \
                '\n\n# All following changes to the manifest' \
                '\n# was rejected due to encountered errors:' \
                '\n#\n# ' + self.cache.decode().replace('\n', '\n# ') + \
                '\n# ' + str(e).replace('\n', '\n# ')
            self.data[len(self.data) - 1:] = message.encode()
            raise IOError() from e
        else:
            error_messages = ""

            error_messages += self._add('path', new, old)
            error_messages += self._del('path', new, old)

            error_messages += self._add('category', new, old)
            error_messages += self._del('category', new, old)

            new_title = new.fields.get('title')
            old_title = old.fields.get('title')
            if new_title != old_title:
                if new_title is None:
                    new_title = "'null'"
                try:
                    _cli('container', 'modify',
                         'set-title', self.container_name, '--title', new_title)
                    old.fields['title'] = new.fields['title']
                except Exception as e:
                    error_messages += '\n' + str(e)

            new_other_fields = {key: value for key, value in new.fields.items()
                                if key not in ('paths', 'categories', 'title')}
            old_other_fields = {key: value for key, value in old.fields.items()
                                if key not in ('paths', 'categories', 'title')}
            if new_other_fields != old_other_fields:
                error_messages += "Pseudomanifest error: Modifying fields except:" \
                                  "\n 'paths', 'categories', 'title' are forbidden."

            self.data[:] = old.copy_to_unsigned().original_data
            if error_messages:
                message = \
                    '\n\n# Some changes to the following manifest' \
                    '\n# was rejected due to encountered errors:' \
                    '\n#\n# ' + self.cache.decode().replace('\n', '\n# ') + \
                    '\n# ' + error_messages.replace('\n', '\n# ')
                self.data[len(self.data) - 1:] = message.encode()
                raise IOError()

    def release(self, flags):
        pass

    def fgetattr(self):
        return self.attr

    def write(self, data: bytes, offset: int) -> int:
        self.cache[offset:offset + len(data)] = data
        self.attr.size = len(self.cache)

        return len(data)

    def _add(self, field: str, new: Manifest, old: Manifest) -> str:
        return self._modify('add', field, new, old)

    def _del(self, field: str, new: Manifest, old: Manifest) -> str:
        return self._modify('del', field, new, old)

    def _modify(self, mod: str, field: str, new: Manifest, old: Manifest) -> str:
        if field == 'path':
            fields = 'paths'
        elif field == 'category':
            fields = 'categories'
        else:
            raise ValueError()

        new_fields = new.fields[fields]
        old_fields = old.fields[fields]

        if mod == 'add':
            to_modify = [f for f in new_fields if f not in old_fields]
        elif mod == 'del':
            to_modify = [f for f in old_fields if f not in new_fields]
        else:
            raise ValueError()

        args = list(chain.from_iterable((f'--{field}', f) for f in to_modify))
        if args:
            try:
                _cli('container', 'modify', f'{mod}-{field}', self.container_name, *args)

                if mod == 'add':
                    old_fields.extend(to_modify)
                elif mod == 'del':
                    for f in to_modify:
                        old_fields.remove(f)
                else:
                    raise ValueError()

            except Exception as e:
                return '\n' + str(e)

        return ""

    def ftruncate(self, length: int) -> None:
        self.cache = self.cache[:length]
        self.attr.size = 0


class PseudomanifestStorageBackend(StorageBackend):
    """
    Storage backend containing pseudomanifest file listed in the storage manifest directly.
    """
    SCHEMA = Schema({
        "type": "object",
        "required": ["content", "container-name"],
        "properties": {
            "content": {
                "type": "object",
                "description": "Pseudomanifest file content."
            },
            "container-name": {
                "type": "string",
                "description": "Container name."
            }
        }
    })
    TYPE = 'pseudomanifest'

    def __init__(self, *, params: Optional[Dict[str, Any]] = None, **kwds):
        super().__init__(params=params, **kwds)
        self.read_only = False

        # Name is required to modify the container.
        self.container_name = params['container-name']
        if self.container_name == '':
            self.read_only = True

        data = params['content']
        if isinstance(data, str):
            data = data.encode()
        self.data = bytearray(data)

        self.attr = Attr(
            size=len(self.data),
            timestamp=0,
            mode=stat.S_IFREG | 0o666
        )

    def open(self, path: PurePosixPath, flags: int) -> File:
        """
        open() for generated pseudomanifest storage
        """
        return PseudomanifestFile(self.container_name, self.data, self.attr)

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        getattr() for generated pseudomanifest storage
        """
        return self.attr
