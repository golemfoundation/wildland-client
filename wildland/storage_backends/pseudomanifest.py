# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
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
import stat
from itertools import chain
from pathlib import PurePosixPath
from typing import Dict, Any, Optional, List, Callable

from .base import StorageBackend, File, Attr
from .buffered import FullBufferedFile
from ..manifest.manifest import Manifest
from ..manifest.schema import Schema


class PseudomanifestFile(FullBufferedFile):
    """
    File for storing single pseudomanifest file.

    Only accepts selected modifications of: paths, categories and title.
    Incorrect changes are rejected and related error message are printed directly into manifest file
    as a comment.
    """

    def __init__(
            self, base_dir: Optional[str],
            uuid_path: str,
            container_wl_path: str,
            data: bytearray,
            pseudomanifest_content: bytearray,
            error_message: bytearray,
            attr: Attr,
            release_callback: Callable[["PseudomanifestFile"], None]
    ):
        super().__init__(attr)
        self.base_dir = base_dir
        self.uuid_path = uuid_path
        self.container_wl_path = container_wl_path
        self.data = data
        self.pseudomanifest_content = pseudomanifest_content
        self.error_message = error_message
        self.release_callback = release_callback

    def release(self, flags: int):
        super().release(flags)
        self.release_callback(self)

    def read_full(self) -> bytes:
        return self.data

    def write_full(self, data: bytes) -> int:
        try:
            new = Manifest.from_unsigned_bytes(bytes(data))
            new.skip_verification()
            old = Manifest.from_unsigned_bytes(bytes(self.pseudomanifest_content))
            old.skip_verification()
        except Exception as e:
            self._update_error_message(data, str(e))
            raise IOError()  # pylint: disable=raise-missing-from

        args = self._prepare_modify_cmd_args(data, new, old)
        if args:
            try:
                _cli(self.base_dir, 'container', 'modify', self.container_wl_path, *args)
            except Exception as e:
                self._update_error_message(data, str(e))
                raise IOError()  # pylint: disable=raise-missing-from

        return len(data)

    def _prepare_modify_cmd_args(self, data: bytes, new: Manifest, old: Manifest) -> List[str]:
        """Compare new and old manifests and return args to modify old manifest"""
        args = []
        error_messages = ""

        try:
            args += self._add('path', new, old)
            args += self._del('path', new, old)

            args += self._add('category', new, old)
            args += self._del('category', new, old)
        except Exception as e:
            error_messages += '\n' + str(e)

        new_title = new.fields.get('title', None)
        old_title = old.fields.get('title', None)
        if new_title != old_title:
            if new_title is None:
                new_title = "null"
            args += ("--title", new_title)

        new_other_fields = {key: value for key, value in new.fields.items()
                            if key not in ('paths', 'categories', 'title')}
        old_other_fields = {key: value for key, value in old.fields.items()
                            if key not in ('paths', 'categories', 'title')}
        if new_other_fields != old_other_fields:
            error_messages += "\n Pseudomanifest error: Modifying fields except:" \
                              "\n 'paths', 'categories', 'title' are not supported."

        if error_messages:
            self._update_error_message(data, error_messages)
            raise IOError()

        return args

    def _add(self, field: str, new: Manifest, old: Manifest) -> List[str]:
        return self._modify('add', field, new, old)

    def _del(self, field: str, new: Manifest, old: Manifest) -> List[str]:
        return self._modify('del', field, new, old)

    def _modify(self, mod: str, field: str, new: Manifest, old: Manifest) -> List[str]:
        if field == 'path':
            fields = 'paths'
        elif field == 'category':
            fields = 'categories'
        else:
            raise ValueError()

        new_fields = new.fields[fields]
        old_fields = old.fields[fields]

        if mod == 'add':
            to_modify = {f for f in new_fields if f not in old_fields}
        elif mod == 'del':
            to_modify = {f for f in old_fields if f not in new_fields}
            try:
                to_modify.remove(self.uuid_path)
                raise ValueError("\n Pseudomanifest error: uuid path cannot be changed or removed.")
            except KeyError:
                pass
        else:
            raise ValueError()

        return list(chain.from_iterable((f'--{mod}-{field}', f) for f in to_modify))

    def _update_error_message(self, data: bytes, error_messages: str):
        """Append error messages to the unchanged pseudomanifest"""
        str_data = data.decode()
        lines = str_data.splitlines()
        without_comments = [line for line in lines if not line.startswith("#")]
        data_without_comments = "\n".join(without_comments)

        message = \
            '\n\n# Changes to the following manifest' \
            '\n# was rejected due to encountered errors:' \
            '\n#\n# ' + data_without_comments.replace('\n', '\n# ') + \
            '\n# ' + error_messages.replace('\n', '\n# ') + \
            '\n'

        self.error_message[:] = message.encode()
        self.data[:] = self.pseudomanifest_content + self.error_message
        self.attr.size = len(self.data)


class PseudomanifestStorageBackend(StorageBackend):
    """
    Storage backend containing pseudomanifest file listed in the storage manifest directly.
    """
    SCHEMA = Schema({
        "type": "object",
        "required": ["content"],
        "properties": {
            "content": {
                "type": "object",
                "description": "Pseudomanifest file content."
            }
        }
    })
    TYPE = 'pseudomanifest'

    def __init__(self, *, params: Dict[str, Any], **kwds):
        super().__init__(params=params, **kwds)

        self.read_only = False

        self.base_dir = params.get('base-dir', None)
        if self.base_dir == 'None':
            self.base_dir = None

        data = params['content']
        if isinstance(data, str):
            data = data.encode()
        header = b'# All YAML comments will be discarded when the manifest is saved\n'
        self.data = bytearray(header + data)

        manifest = Manifest.from_unsigned_bytes(bytes(self.data))
        manifest.skip_verification()

        self.uuid_path = manifest.fields['paths'][0]
        self.container_wl_path = f"wildland:{manifest.fields['owner']}:{self.uuid_path}:"
        self.pseudomanifest_content = self.data.copy()
        self.error_message = bytearray(b"")

        self.attr = Attr(
            size=len(self.data),
            timestamp=0,
            mode=stat.S_IFREG | 0o666
        )

        self.open_files: List[File] = []

    def open(self, path: PurePosixPath, flags: int) -> File:
        """
        open() for generated pseudomanifest storage
        """
        file = PseudomanifestFile(
            self.base_dir,
            self.uuid_path,
            self.container_wl_path,
            self.data,
            self.pseudomanifest_content,
            self.error_message,
            self.attr,
            release_callback=self.open_files.remove
        )
        self.open_files.append(file)
        return file

    def getattr(self, path: PurePosixPath) -> Attr:
        """
        getattr() for generated pseudomanifest storage
        """
        return self.attr

    def truncate(self, path: PurePosixPath, length: int) -> None:
        """
        Truncate the pseudomanifest file.
        """
        if not self.open_files:
            raise NotImplementedError()

        for file in self.open_files:
            file.ftruncate(length)


def _cli(base_dir, *args):
    # pylint: disable=import-outside-toplevel,cyclic-import
    from ..cli import cli_main
    cmdline = ['--base-dir', base_dir, *args] if base_dir else args

    # Convert Path to str
    cmdline = [str(arg) for arg in cmdline]

    try:
        cli_main.main.main(args=cmdline, prog_name='wl')
    except SystemExit as e:
        if e.code not in [None, 0]:
            if hasattr(e, '__context__'):
                assert isinstance(e.__context__, Exception)
                raise e.__context__
