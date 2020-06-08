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
Bear storage backend
'''

from pathlib import PurePosixPath
from typing import Iterable, Tuple, Optional, List, Set
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

    def get_paths(self) -> List[PurePosixPath]:
        '''
        Get the list of paths this not should be mounted under, based on tags.

        This includes only leaf tags, i.e. for tags 'tests', 'tests/cat',
        'tests/cat/subcat', only the last one will be used.
        '''

        result: Set[PurePosixPath] = set()
        for tag in sorted(self.tags, key=len):
            path = PurePosixPath('/') / PurePosixPath(tag)
            for parent in path.parents:
                if parent in result:
                    result.remove(parent)
            result.add(path)
        return sorted(result)

    def get_md(self) -> bytes:
        '''
        Get the contents of note Markdown file.
        '''
        content = 'title: ' + self.title + '\n---\n' + self.text + '\n'
        return content.encode('utf-8')


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
            "with_content": {
                "type": "boolean",
                "description": "Serve note content, not only manifests",
            },
        }
    })
    TYPE = 'bear-db'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.bear_db = BearDB(self.params['path'])
        self.with_content = self.params.get('with_content', False)

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--path'], metavar='PATH',
                         help='Path to the SQLite database',
                         required=True),
            click.Option(['--with-content'], is_flag=True,
                         help='Serve note content, not only manifests'),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'path': data['path'],
            'with_content': data['with_content'],
        }

    def make_storage_manifest(self, note: BearNote) -> Manifest:
        '''
        Create a storage manifest for a single note.
        '''

        storage = Storage(
            signer=self.params['signer'],
            storage_type='bear-note',
            container_path=PurePosixPath(f'/.uuid/{note.ident}'),
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
        paths = [PurePosixPath(f'/.uuid/{note.ident}')] + note.get_paths()
        container = Container(
            signer=self.params['signer'],
            paths=paths,
            backends=[storage_manifest.fields],
        )
        manifest = container.to_unsigned_manifest()
        manifest.skip_signing()
        return manifest

    def get_readme(self) -> bytes:
        '''
        Get the contents of note README.md file.
        '''

        readme = '''\
This is an auto-generated directory for a single Bear note. To use it, mount
the `container.yaml` file.

The note itself will be exposed via the Wildland FS tree, depending on what
tags it defines for itself. Thus a note containing `#projects/wildland/bear2fs`
tag will be found under `~/Wildland/projects/bear2fs/` directory.
'''

        if self.with_content:
            readme += '''\

The note files (currently just `note.md`) are also visible here.
'''

        return readme.encode()

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        yield PurePosixPath('.'), Info(is_dir=True)

        for ident in self.bear_db.get_note_idents():
            note = self.bear_db.get_note(ident)
            if not note:
                continue
            path = PurePosixPath(note.ident)
            yield path, Info(is_dir=True)
            yield path / 'container.yaml', Info(is_dir=False)
            yield path / 'README.md', Info(is_dir=False)
            if self.with_content:
                yield path / 'note.md', Info(is_dir=False)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        # we should be called by CachedStorage only with paths from backend_info_all()
        assert len(path.parts) == 2

        ident = path.parts[0]
        note = self.bear_db.get_note(ident)
        if not note:
            raise FileNotFoundError(errno.ENOENT, str(path))

        if path.name == 'container.yaml':
            return self.make_container_manifest(note).to_bytes()
        if path.name == 'README.md':
            return self.get_readme()
        if path.name == 'note.md' and self.with_content:
            return note.get_md()

        raise FileNotFoundError(errno.ENOENT, str(path))


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

    def backend_info_all(self) -> Iterable[Tuple[PurePosixPath, Info]]:
        self.note = self.bear_db.get_note(self.ident)
        if not self.note:
            return

        yield PurePosixPath('.'), Info(is_dir=True)
        yield PurePosixPath(f'note-{self.ident}.md'), Info(is_dir=False)

    def backend_load_file(self, path: PurePosixPath) -> bytes:
        assert len(path.parts) == 1

        if path.name == f'note-{self.ident}.md' and self.note is not None:
            return self.note.get_md()

        raise FileNotFoundError(errno.ENOENT, str(path))
