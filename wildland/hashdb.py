# Wildland Project
#
# Copyright (C) 2020 Golem Foundation,
#                    Marta Marczykowska-Górecka <marmarta@invisiblethingslab.com>,
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
"""
Hash db.
"""

import logging
import sqlite3
from pathlib import PurePosixPath
from typing import List, Optional, Tuple, NamedTuple

logger = logging.getLogger('hashdb')

class HashCache(NamedTuple):
    """
    Hash cache
    """
    hash: str
    token: str

class HashDb:
    """
    Class that handles operations related to hash storage and retrieval, and auxiliary
    functions like tracking which storage has been noted to be associated with a given
    container.
    """
    def __init__(self, base_dir: PurePosixPath):
        self.base_dir = base_dir
        self.hash_db_path = base_dir / 'wlhashes.db'
        with sqlite3.connect(self.hash_db_path) as conn:
            self._create_container_backends_table(conn)

            if self._hashes_table_has_outdated_schema(conn):
                logger.warning('SQLite hashes table from [%s] is outdated', self.hash_db_path)
                self._remove_hashes_table(conn)

            self._create_hashes_table_if_not_exist(conn)

    @staticmethod
    def _hashes_table_has_outdated_schema(conn) -> bool:
        cursor = conn.cursor()
        table_name = 'hashes'
        column_name = 'token'
        cursor.execute('SELECT type FROM pragma_table_info(?) WHERE name = ?',
                       (table_name, column_name))
        result = cursor.fetchone()
        if not result:
            return False
        (column_type,) = result
        # hashes.token column used to be integer instead of a string
        return column_type != 'TEXT'

    def _create_container_backends_table(self, conn) -> None:
        logger.debug('Trying to create [container_backends] SQLite table in [%s]',
                     self.hash_db_path)
        conn.execute('CREATE TABLE IF NOT EXISTS container_backends '
                     '(container_id TEXT NOT NULL, '
                     'backend_id TEXT NOT NULL, '
                     'PRIMARY KEY (container_id, backend_id))')

    def _create_hashes_table_if_not_exist(self, conn) -> None:
        logger.debug('Trying to create [hashes] SQLite table in [%s]', self.hash_db_path)
        conn.execute('CREATE TABLE IF NOT EXISTS hashes '
                     '(backend_id TEXT NOT NULL, '
                     'path TEXT NOT NULL, '
                     'hash TEXT, '
                     'token TEXT, PRIMARY KEY (backend_id, path))')

    def _remove_hashes_table(self, conn) -> None:
        logger.warning('Removing SQLite hashes table from [%s]', self.hash_db_path)
        conn.execute('DROP TABLE hashes')

    def update_storages_for_containers(self, container_uuid, storages) -> None:
        """
        Storage information that given storages were associated with the given container.
        """
        with sqlite3.connect(self.hash_db_path) as conn:
            for storage in storages:
                conn.execute('INSERT OR REPLACE INTO container_backends VALUES (?, ?)',
                             (container_uuid, storage.backend_id))

    def get_conflicts(self, container_uuid) -> List[Tuple[str, str, str]]:
        """
        List all known file conflicts for a given storage across all known backends; the result
        is a list of tuples (path, container_1_uuid, container_2_uuid).
        """
        with sqlite3.connect(self.hash_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT DISTINCT h1.path, c1.backend_id, c2.backend_id '
                'FROM '
                'hashes h1 INNER JOIN container_backends c1 ON h1.backend_id = c1.backend_id '
                'INNER JOIN container_backends c2 ON c2.container_id = c1.container_id '
                'AND c1.backend_id > c2.backend_id '
                'INNER JOIN hashes h2 ON h2.backend_id = c2.backend_id AND h1.path = h2.path '
                'WHERE h1.hash <> h2.hash AND c1.container_id = ?', [container_uuid])

            return cursor.fetchall()

    def store_hash(self, backend_id, path, hash_cache) -> None:
        """
        Stores given HashCache tuple.
        :param backend_id: uuid of the backend
        :param path: path to file (can be PurePosixPath or str)
        :param hash_cache: HashCache named tuple (with two elements, hash (sha256 hash) and token)
        :return: None
        """
        with sqlite3.connect(self.hash_db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO hashes VALUES (?, ?, ?, ?)',
                         (backend_id, str(path), hash_cache.hash, hash_cache.token))

    def retrieve_hash(self, backend_id, path) -> Optional[HashCache]:
        """
        Retrieve hash (if available) for a given path.
        :param backend_id: uuid of the backend
        :param path: path to file (can be PurePosixPath or str)
        :return: HashCache named tuple (with two elements, hash (sha256 hash) and token)
        """
        with sqlite3.connect(self.hash_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT hash, token from hashes WHERE backend_id = ? AND path = ?',
                (backend_id, str(path)))
            result = cursor.fetchone()
            if not result:
                return None
            hash_value, token = result
            return HashCache(hash_value, token)
