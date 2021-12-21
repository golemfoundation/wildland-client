# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                    Rafał Wojdyła <omeg@invisiblethingslab.com>,
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
Generic persistent key-value store for use by storage backends.
"""
import pickle
import sqlite3
import threading
from pathlib import PurePosixPath
from typing import Any, Set
from ..log import get_logger

logger = get_logger('kv-store')


class KVStore:
    """
    Persistent key-value store backed by SQLite.
    """
    def __init__(self, base_dir: PurePosixPath, backend_id: str):
        self.db_path = base_dir / 'backend.db'
        self.backend_id = backend_id
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_data_table()

    def _create_data_table(self):
        logger.debug('Trying to create [data] SQLite table in [%s]', self.db_path)
        with self.lock, self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS data '
                            '(backend_id TEXT NOT NULL, '
                            'key TEXT NOT NULL, '
                            'value BLOB, PRIMARY KEY (backend_id, key))')

    def get_object(self, key: str) -> Any:
        """
        Retrieve object by key.
        """
        with self.lock, self.db:
            cursor = self.db.cursor()
            cursor.execute('SELECT value FROM data WHERE backend_id = ? AND key = ?',
                           (self.backend_id, key))
            val = cursor.fetchone()
            if not val:
                return None

            blob = val[0]
            return pickle.loads(blob)

    def store_object(self, key: str, value: Any):
        """
        Store object by key.
        """
        blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO data VALUES (?, ?, ?)',
                            (self.backend_id, key, blob))

    def del_object(self, key: str):
        """
        Delete stored object.
        """
        with self.lock, self.db:
            self.db.execute('DELETE FROM data WHERE backend_id = ? AND key = ?',
                            (self.backend_id, key))

    def get_all_keys(self) -> Set[str]:
        """
        Get all keys for given backend ID.
        """
        with self.lock, self.db:
            cursor = self.db.cursor()
            cursor.execute('SELECT key FROM data WHERE backend_id = ?',
                           (self.backend_id,))
            return {val[0] for val in cursor.fetchall()}
