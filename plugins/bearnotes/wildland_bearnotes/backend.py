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
from typing import Iterable, Tuple, Optional, List
import logging
from dataclasses import dataclass
import errno

import sqlite3
import click

from wildland.storage import Storage
from wildland.container import Container
from wildland.storage_backends.cached import ReadOnlyCachedStorageBackend, Info
from wildland.manifest.manifest import Manifest
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
    tags: List[str]


class BearDB:
    '''
    An class for accessing the Bear SQLite database.
    '''

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row

    def get_note_idents(self) -> Iterable[str]:
        '''
        Retrieve list of note IDs.
        '''

        cursor = self.db.cursor()
        cursor.execute('SELECT ZUNIQUEIDENTIFIER FROM ZSFNOTE')
        for row in cursor.fetchall():
            yield row['ZUNIQUEIDENTIFIER']

    def get_note(self, ident: str) -> Optional[BearNote]:
        '''
        Retrieve a single note.
        '''

        cursor = self.db.cursor()
        cursor.execute('''
            SELECT Z_PK, ZTITLE, ZTEXT FROM ZSFNOTE
            WHERE ZUNIQUEIDENTIFIER = ?
        ''', [ident])
        row = cursor.fetchone()
        if not row:
            return None

        tags = self.get_tags(row['Z_PK'])
        return BearNote(ident=ident, title=row['ZTITLE'], text=row['ZTEXT'],
                        tags=tags)

    def get_tags(self, pk: int) -> List[str]:
        '''
        Retrieve a list of tags for a note.
        '''

        cursor = self.db.cursor()
        cursor.execute('''
            SELECT ZTITLE FROM ZSFNOTETAG
            JOIN Z_7TAGS ON Z_7TAGS.Z_7NOTES = ?
            AND Z_7TAGS.Z_14TAGS = ZSFNOTETAG.Z_PK
        ''', [pk])

        return [tag_row['ZTITLE'] for tag_row in cursor.fetchall()]


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

        self.bear_db = BearDB(self.params['path'])

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

    def make_storage_manifest(self, note: BearNote) -> Manifest:
        '''
        Create a storage manifest for a single note.
        '''

        storage = Storage(
            signer=self.params['signer'],
            storage_type='bear-note',
            container_path=f'/.uuid/{note.ident}',
            trusted=False,
            params={
                'path': self.params['path'],
                'note': note.ident,
            })
        storage.validate()
        manifest = storage.to_unsigned_manifest()
        manifest.skip_signing()
        return manifest

    def make_container_manifest(self, note: BearNote) -> Manifest:
        '''
        Create a container manifest for a single note. The container paths will
        be derived from note tags.
        '''

        storage_manifest = self.make_storage_manifest(note)
        paths = [f'/.uuid/{note.ident}']
        for tag in note.tags:
            paths.append(f'/{tag}')
        container = Container(
            signer=self.params['signer'],
            paths=paths,
            backends=[storage_manifest.fields],
        )
        manifest = container.to_unsigned_manifest()
        manifest.skip_signing()
        return manifest

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        yield PurePosixPath('.'), Info(is_dir=True)

        for ident in self.bear_db.get_note_idents():
            note = self.bear_db.get_note(ident)
            if not note:
                continue
            # TODO: we need the right manifest size here; because otherwise the
            # file gets padded with 0's otherwise
            manifest_size = len(self.make_container_manifest(note).to_bytes())
            yield PurePosixPath(f'{ident}.yaml'), Info(is_dir=False, size=manifest_size)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        # we should be called by CachedStorage only with paths from backend_info_all()
        assert len(path.parts) == 1
        assert path.suffix == '.yaml'

        ident = path.stem
        note = self.bear_db.get_note(ident)
        if not note:
            raise FileNotFoundError(errno.ENOENT, str(path))
        return self.make_container_manifest(note).to_bytes()


class BearNoteStorageBackend(ReadOnlyCachedStorageBackend):
    '''
    A backend responsible for serving an individual Bear note.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs_path",
                "description": "Path to the Bear SQLite database",
            },
            "note": {
                "type": "string",
                "description": "Bear note identifier, typically UUID",
            },
        }
    })
    TYPE = 'bear-note'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.bear_db = BearDB(self.params['path'])
        self.ident = self.params['note']
        self.note: Optional[BearNote] = None

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--path'], metavar='PATH',
                         help='Path to the SQLite database',
                         required=True),
            click.Option(['--note'], metavar='IDENT',
                         help='Bear note identifier',
                         required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'path': data['path'],
            'note': data['note'],
        }

    def get_md(self) -> bytes:
        '''
        Get the contents of note Markdown file.
        '''

        if not self.note:
            return b''

        content = 'title: ' + self.note.title + '\n---\n' + self.note.text + '\n'
        return content.encode('utf-8')

    @staticmethod
    def get_readme() -> bytes:
        '''
        Get the contents of note README.txt file.
        '''

        return (
            'This is an auto-generated directory representing a (storage '
             'for a) single Bear note. The note itself is exposed via the '
            'Wildland FS tree, depending on what tags it defines for '
            'itself. Thus a note containing `#projects/wildland/bear2fs` '
            'tag will be found under `~/Wildland/projects/bear2fs/` '
            'directory.\n'
        ).encode()

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        self.note = self.bear_db.get_note(self.ident)
        if not self.note:
            return

        yield PurePosixPath('.'), Info(is_dir=True)

        md_size = len(self.get_md())
        readme_size = len(self.get_readme())
        yield PurePosixPath('note.md'), Info(is_dir=False, size=md_size)
        yield PurePosixPath(f'{self.ident}.md'), Info(is_dir=False, size=md_size)
        yield PurePosixPath('README.txt'), Info(is_dir=False, size=readme_size)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        assert len(path.parts) == 1

        if path.name == 'note.md' or path.name == f'{self.ident}.md':
            return self.get_md()

        if path.name == 'README.txt':
            return self.get_readme()

        raise FileNotFoundError(errno.ENOENT, str(path))
