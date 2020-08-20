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

from pathlib import PurePosixPath, Path
from typing import Iterable, Optional, List, Set, Dict, Tuple
import logging
from dataclasses import dataclass
from functools import partial
import errno
import os
import threading

import sqlite3
import click

from wildland.storage import Storage
from wildland.container import Container
from wildland.storage_backends.base import StorageBackend
from wildland.storage_backends.generated import \
    GeneratedStorageMixin, FuncFileEntry, CachedDirEntry, \
    StaticFileEntry
from wildland.storage_backends.watch import SimpleStorageWatcher
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

    def get_md(self) -> bytes:
        '''
        Get the contents of note Markdown file.
        '''
        content = 'title: ' + self.title + '\n---\n' + self.text + '\n'
        return content.encode('utf-8')


def get_note_paths(tags: List[str]) -> List[PurePosixPath]:
    '''
    Get the list of paths a note should be mounted under, based on tags.

    This includes only leaf tags, i.e. for tags 'tests', 'tests/cat',
    'tests/cat/subcat', only the last one will be used.
    '''

    result: Set[PurePosixPath] = set()
    for tag in sorted(tags, key=len):
        path = PurePosixPath('/') / PurePosixPath(tag)
        for parent in path.parents:
            if parent in result:
                result.remove(parent)
        result.add(path)
    return sorted(result)


class FileCachedDirEntry(CachedDirEntry):
    '''
    A CachedDirEntry that refreshes only when the underlying file is modified
    (by checking file modification time).
    '''

    def __init__(self, path, *args, **kwargs):
        self.path = path
        super().__init__(*args, **kwargs)

        self.mtime: float = 0.

    def _update(self):
        mtime = os.stat(self.path).st_mtime
        if mtime != self.mtime:
            self._refresh()
            self.mtime = mtime


class BearDB:
    '''
    An class for accessing the Bear SQLite database.
    '''

    # Maintain a single SQLite connection per database.
    # Note that this prevents multi-threaded access to the database.
    # A better solution would be to maintain a thread-local connection.
    global_lock = threading.Lock()
    conn_cache: Dict[str, sqlite3.Connection] = {}
    conn_locks: Dict[str, threading.RLock] = {}
    conn_refcount: Dict[str, int] = {}

    def __init__(self, path):
        self.path = path
        self.db = None
        self.db_lock = None

    def connect(self):
        '''
        Connect to database, reusing existing connection if necessary.
        '''

        assert not self.db

        with self.global_lock:
            if self.path in self.conn_cache:
                self.db = self.conn_cache[self.path]
                self.db_lock = self.conn_locks[self.path]
                self.conn_refcount[self.path] += 1
            else:
                self.db = sqlite3.connect(self.path, check_same_thread=False)
                self.db.row_factory = sqlite3.Row
                self.db_lock = threading.RLock()
                self.conn_cache[self.path] = self.db
                self.conn_locks[self.path] = self.db_lock
                self.conn_refcount[self.path] = 1

    def disconnect(self):
        '''
        Close database connection, if necessary.
        '''

        assert self.db and self.db_lock

        with self.global_lock, self.db_lock:
            self.conn_refcount[self.path] -= 1
            if self.conn_refcount[self.path] == 0:
                del self.conn_refcount[self.path]
                del self.conn_cache[self.path]
                del self.conn_locks[self.path]
                self.db.close()
            self.db = None
            self.db_lock = None

    def get_note_idents(self) -> Iterable[str]:
        '''
        Retrieve list of note IDs.
        '''

        assert self.db and self.db_lock

        with self.db_lock:
            cursor = self.db.cursor()
            cursor.execute('SELECT ZUNIQUEIDENTIFIER FROM ZSFNOTE')
            return [row['ZUNIQUEIDENTIFIER'] for row in cursor.fetchall()]

    def get_note_idents_with_tags(self) -> Iterable[Tuple[str, List[str]]]:
        '''
        Retrieve list of note IDs, along with tags.
        '''

        assert self.db and self.db_lock

        with self.db_lock:
            cursor = self.db.cursor()

            result: Dict[str, List[str]] = {
                ident: []
                for ident in self.get_note_idents()
            }
            cursor.execute('''
                SELECT ZUNIQUEIDENTIFIER, ZSFNOTETAG.ZTITLE FROM ZSFNOTE
                JOIN Z_7TAGS ON Z_7TAGS.Z_7NOTES = ZSFNOTE.Z_PK
                JOIN ZSFNOTETAG ON Z_7TAGS.Z_14TAGS = ZSFNOTETAG.Z_PK
            ''')
            for row in cursor.fetchall():
                ident = row['ZUNIQUEIDENTIFIER']
                tag = row['ZTITLE']
                result.setdefault(ident, []).append(tag)
            return result.items()

    def get_note(self, ident: str) -> Optional[BearNote]:
        '''
        Retrieve a single note.
        '''

        assert self.db and self.db_lock

        with self.db_lock:
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

        assert self.db and self.db_lock

        with self.db_lock:
            cursor = self.db.cursor()
            cursor.execute('''
                SELECT ZTITLE FROM ZSFNOTETAG
                JOIN Z_7TAGS ON Z_7TAGS.Z_7NOTES = ?
                AND Z_7TAGS.Z_14TAGS = ZSFNOTETAG.Z_PK
            ''', [pk])

            return [tag_row['ZTITLE'] for tag_row in cursor.fetchall()]


class BearDBWatcher(SimpleStorageWatcher):
    '''
    A watcher for the Bear database.
    '''

    def __init__(self, backend: 'BearDBStorageBackend'):
        super().__init__(backend)
        self.db_path = Path(backend.bear_db.path)

    def get_token(self):
        try:
            st = self.db_path.stat()
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime)


class BearDBStorageBackend(GeneratedStorageMixin, StorageBackend):
    '''
    Main BearDB storage that serves individual manifests.

    Must be created with the 'trusted' option in order to work.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs-path",
                "description": "Path to the Bear SQLite database",
            },
            "with-content": {
                "type": "boolean",
                "description": "Serve note content, not only manifests",
            },
        }
    })
    TYPE = 'bear-db'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.bear_db = BearDB(self.params['path'])
        self.with_content = self.params.get('with-content', False)

        self.root = FileCachedDirEntry(self.bear_db.path, '.', self._dir_root)

    def mount(self):
        self.bear_db.connect()

    def unmount(self):
        self.bear_db.disconnect()

    def watcher(self):
        return BearDBWatcher(self)

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
            'with-content': data['with_content'],
            'trusted': True,
            'manifest_pattern': {'type': 'glob', 'path': '/*/container.yaml'},
        }

    def _make_storage_manifest(self, ident: str) -> Manifest:
        '''
        Create a storage manifest for a single note.
        '''

        storage = Storage(
            signer=self.params['signer'],
            storage_type='bear-note',
            container_path=PurePosixPath(f'/.uuid/{ident}'),
            trusted=False,
            params={
                'path': self.params['path'],
                'note': ident,
            })
        storage.validate()
        manifest = storage.to_unsigned_manifest()
        manifest.skip_signing()
        return manifest

    def _make_container_manifest(self, ident: str, tags: List[str]) -> Manifest:
        '''
        Create a container manifest for a single note. The container paths will
        be derived from note tags.
        '''

        storage_manifest = self._make_storage_manifest(ident)
        paths = [PurePosixPath(f'/.uuid/{ident}')] + get_note_paths(tags)
        container = Container(
            signer=self.params['signer'],
            paths=paths,
            backends=[storage_manifest.fields],
        )
        manifest = container.to_unsigned_manifest()
        manifest.skip_signing()
        return manifest

    def get_root(self):
        return self.root

    def clear_cache(self):
        self.root.clear_cache()

    def _dir_root(self):
        try:
            for ident, tags in self.bear_db.get_note_idents_with_tags():
                yield FileCachedDirEntry(self.bear_db.path,
                                         ident, partial(self._dir_note, ident, tags))
        except sqlite3.DatabaseError:
            logger.exception('error loading database')
            return

    def _dir_note(self, ident: str, tags: List[str]):
        yield StaticFileEntry('container.yaml', self._get_manifest(ident, tags))
        yield StaticFileEntry('README.md', self._get_readme())
        if self.with_content:
            yield FuncFileEntry('note.md', partial(self._get_note, ident))

    def _get_readme(self) -> bytes:
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

    def _get_manifest(self, ident, tags):
        return self._make_container_manifest(ident, tags).to_bytes()

    def _get_note(self, ident):
        note = self.bear_db.get_note(ident)
        if not note:
            raise FileNotFoundError(errno.ENOENT, '')
        return note.get_md()


class BearNoteStorageBackend(GeneratedStorageMixin, StorageBackend):
    '''
    A backend responsible for serving an individual Bear note.
    '''

    SCHEMA = Schema({
        "type": "object",
        "required": ["path"],
        "properties": {
            "path": {
                "$ref": "types.json#abs-path",
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
        self.root = FileCachedDirEntry(self.bear_db.path, '.', self._dir_root)

    def clear_cache(self):
        self.root.clear_cache()

    def mount(self):
        self.bear_db.connect()

    def unmount(self):
        self.bear_db.disconnect()

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

    def get_root(self):
        return self.root

    def _dir_root(self):
        yield StaticFileEntry(f'note-{self.ident}.md', self._get_note())

    def _get_note(self):
        note = self.bear_db.get_note(self.ident)
        if not note:
            raise FileNotFoundError(errno.ENOENT, '')
        return note.get_md()
