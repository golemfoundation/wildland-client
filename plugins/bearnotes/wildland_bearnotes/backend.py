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
S3 storage backend
'''

from pathlib import PurePosixPath
from typing import Iterable, Tuple, Optional
import logging
import errno
from dataclasses import dataclass

import sqlite3
import click

from wildland.storage_backends.cached import ReadOnlyCachedStorageBackend, Info
from wildland.manifest.schema import Schema

# TODO why can't we serve size 0?
MAX_SIZE = 4096

logger = logging.getLogger('storage-bear')


@dataclass
class BearNote:
    '''
    Individual Bear note.
    '''

    ident: str
    title: str
    text: str


class BearDBStorageBackend(ReadOnlyCachedStorageBackend):
    '''
    Main BearDB storage that serves individual manifests.

    Must be created with the 'trusted' option in order to work.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs_path",
                "description": "Path to the Bear SQLite database",
            },
        }
    })
    TYPE = 'bear-db'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.db = sqlite3.connect(self.params['path'])
        self.db.row_factory = sqlite3.Row

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--path'], metavar='PATH',
                         help='Path to the SQLite database',
                         required=True)
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'path': data['path'],
        }

    def get_note_idents(self) -> Iterable[str]:
        cursor = self.db.cursor()
        cursor.execute('SELECT ZUNIQUEIDENTIFIER FROM ZSFNOTE')
        for row in cursor.fetchall():
            yield row['ZUNIQUEIDENTIFIER']

    def get_note(self, ident: str) -> Optional[BearNote]:
        cursor = self.db.cursor()
        cursor.execute('''
            SELECT ZTITLE, ZTEXT FROM ZSFNOTE
            WHERE ZUNIQUEIDENTIFIER = ?
        ''', [ident])
        row = cursor.fetchone()
        if not row:
            return None
        return BearNote(ident=ident, title=row['ZTITLE'], text=row['ZTEXT'])

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        yield PurePosixPath('.'), Info(is_dir=True)

        for ident in self.get_note_idents():
            dir_path = PurePosixPath(ident)
            yield dir_path, Info(is_dir=True)
            yield dir_path / 'container.yaml', Info(is_dir=False, size=MAX_SIZE)
            yield dir_path / 'note.md', Info(is_dir=False, size=MAX_SIZE)
            yield dir_path / f'{ident}.md', Info(is_dir=False, size=MAX_SIZE)
            yield dir_path / 'README.txt', Info(is_dir=False, size=MAX_SIZE)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        if len(path.parts) != 2:
            raise FileNotFoundError(errno.ENOENT, str(path))
        ident, name = path.parts

        if name in ('note.md', f'{ident}.md'):
            note = self.get_note(ident)
            if not note:
                raise FileNotFoundError(errno.ENOENT, str(path))

            content = 'title: ' + note.title + '\n---\n' + note.text + '\n'
            return content.encode('utf-8')

        if name == 'container.yaml':
            return b'' # TODO

        if name == 'README.txt':
            return (
                'This is an auto-generated directory representing a (storage '
                'for a) single Bear note. The note itself is exposed via the '
                'Wildland FS tree, depending on what tags it defines for '
                'itself. Thus a note containing `#projects/wildland/bear2fs` '
                'tag will be found under `~/Wildland/projects/bear2fs/` '
                'directory.\n'
            ).encode()

        raise FileNotFoundError(errno.ENOENT, str(path))
