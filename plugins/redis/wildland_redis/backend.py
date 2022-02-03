# Wildland Project
#
# Copyright (C) 2021 Golem Foundation
#
# Authors:
#                    Michał Kluczek <michal@wildland.io>
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
Redis storage backend
"""

from pathlib import PurePosixPath
from typing import Iterable, Tuple, Union, Optional

import click
from redis import Redis

from wildland.exc import WildlandError
from wildland.link import Link
from wildland.storage_backends.base import StorageBackend, Attr, File
from wildland.storage_backends.buffered import FullBufferedFile
from wildland.storage_backends.cached import DirectoryCachedStorageMixin

from wildland.storage_backends.file_children import FileChildrenMixin

from wildland.manifest.schema import Schema
from wildland.log import get_logger

logger = get_logger('storage-redis')


class RedisFile(FullBufferedFile):
    """
    Redis implementation of Buffered File class
    """

    def __init__(self,
                 redis_client,
                 redis_key: str,
                 attr: Attr = Attr.file()):
        super().__init__(attr)
        self.redis_client = redis_client
        self.redis_key = redis_key

    def read_full(self) -> bytes:
        return self.redis_client.get(self.redis_key)

    def write_full(self, data: bytes) -> int:
        self.redis_client.set(self.redis_key, data)

        return len(data)


class RedisStorageBackend(FileChildrenMixin, DirectoryCachedStorageMixin, StorageBackend):
    """
    Redis KV storage backend
    """

    SCHEMA = Schema({
        "type": "object",
        "required": ["database", "hostname", "port"],
        "properties": {
            "prefix": {
                "$ref": "/schemas/types.json#abs-path",
                "description": "Redis key prefix as an absolute path, defaults to /",
            },
            "database": {
                "type": "integer",
                "description": "Redis DB index",
            },
            "hostname": {
                "type": "string",
                "description": "Server hostname",
            },
            "port": {
                "type": "integer",
                "description": "Server port",
            },
            "username": {
                "type": "string",
                "description": "Server username",
            },
            "password": {
                "type": "string",
                "description": "Server password",
            },
            "tls": {
                "type": "boolean",
                "description": "Use TLS",
            },
            "manifest-pattern": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#pattern-glob"},
                    {"$ref": "/schemas/types.json#pattern-list"},
                ]
            },
        }
    })
    TYPE = 'redis'
    LOCATION_PARAM = 'prefix'

    # Dummy key used to "hold" directory
    DIRECTORY_PLACEHOLDER = '.__dir'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.hostname = str(self.params.get('hostname'))
        self.port: int = self.params.get('port', 6379)
        self.database: int = self.params.get('database', 0)

        # Init Redis client. This does not initialize any network connection.
        self.redis = Redis(
            host=self.hostname,
            port=self.port,
            db=self.database,
            username=self.params.get('username', 'default'),
            password=self.params.get('password'),
            ssl=self.params.get('tls', False),
        )

        self.read_only = False
        self.key_prefix = PurePosixPath(self.params.get('prefix', '/'))

        if self.key_prefix.parts[0] != '/':
            raise WildlandError('Redis prefix path must be an absolute path')

    def mount(self):
        """
        Check for Redis server responsiveness.
        The ping() call will initialize network connection to the Redis server, verify credentials
        (if provided) and confirm that the server is responsive.
        """
        try:
            self.redis.ping()
        except Exception as ex:
            raise WildlandError('Could not connect to [%s:%d] redis server. Error: %s' %
                                (self.hostname, self.port, str(ex))) from ex

    def unmount(self):
        self.redis.connection_pool.disconnect()

    @classmethod
    def cli_options(cls):
        opts = super(RedisStorageBackend, cls).cli_options()
        opts.extend([
            click.Option(['--prefix'], required=False, metavar='PATH',
                         help='Redis key prefix as an absolute path, defaults to /'),
            click.Option(['--database'], required=True, metavar='INTEGER',
                         help='Redis DB index'),
            click.Option(['--hostname'], required=True, metavar='HOST',
                         help='Server hostname'),
            click.Option(['--port'], required=False, metavar='INTEGER',
                         help='Server port (defaults to 6379)'),
            click.Option(['--password'], required=False,
                         help='Server password'),
            click.Option(['--username'], required=False,
                         help='Server username (defaults to "default")'),
            click.Option(['--tls'], required=False, metavar='BOOL',
                         help='Use TLS'),
        ])
        return opts

    @classmethod
    def cli_create(cls, data):
        opts = super(RedisStorageBackend, cls).cli_create(data)
        opts.update({
            'prefix': data.get('prefix', '/'),
            'database': int(data.get('database') or 0),
            'hostname': data.get('hostname'),
            'port': int(data.get('port') or 6379),
            'password': data.get('password', None),
            'tls': data.get('tls', None),
            'username': data.get('username'),
        })
        return opts

    def get_children(
            self,
            client=None,
            query_path: PurePosixPath = PurePosixPath('*'),
            paths_only: bool = False
    ) -> Iterable[Tuple[PurePosixPath, Optional[Link]]]:

        # Make use of Redis' multi-get (blocking) feature
        children = list(super().get_children(client, query_path, paths_only))

        if paths_only:
            for res_path, _ in children:
                yield res_path, None

        keys = [self._generate_key(path) for path, _ in children]
        manifests = self.redis.mget(keys)

        for (res_path, res_obj), manifest in zip(children, manifests):
            assert isinstance(res_obj, Link)
            assert res_obj.storage_driver.storage_backend is self

            # Setting file_bytes param will prevent the Client to call Link's backend to fetch it
            res_obj.file_bytes = manifest
            yield res_path, res_obj

    def info_dir(self, path: PurePosixPath) -> Iterable[Tuple[PurePosixPath, Attr]]:
        posix_path = PurePosixPath(path)
        scan_prefix = self._generate_key(posix_path)

        # Directories
        for key in self.redis.keys(self._prepare_scan_query(scan_prefix, find_dirs=True)):
            # Result will look like foo:::/.__dir, but we only need foo:::
            key_path = PurePosixPath(key.decode('utf-8'))
            rel_path = PurePosixPath(key_path.relative_to(scan_prefix).parts[0])

            yield self._normalize_key(rel_path), Attr.dir()

        # Files
        file_names = []

        with self.redis.pipeline() as pipe:
            for key in self.redis.keys(self._prepare_scan_query(scan_prefix, find_dirs=False)):
                key_path = PurePosixPath(key.decode('utf-8'))
                rel_path = key_path.relative_to(scan_prefix)

                file_name = self._normalize_key(rel_path)

                if str(file_name) != self.DIRECTORY_PLACEHOLDER:
                    pipe.strlen(key)
                    file_names.append(file_name)

            file_sizes = pipe.execute()

        for file_name, file_size in zip(file_names, file_sizes):
            yield file_name, Attr.file(size=file_size)

    def open(self, path: PurePosixPath, _flags: int) -> File:
        return RedisFile(self.redis, self._generate_key(path), self.getattr(path))

    def create(self, path: PurePosixPath, _flags: int, _mode: int = 0o666) -> File:
        self._redis_set(self._generate_key(path), b'')
        self.update_cache(path, Attr.file())

        return RedisFile(self.redis, self._generate_key(path), self.getattr(path))

    def flush(self, path: PurePosixPath, obj: File) -> None:
        """
        Performance hack. Assumes the buffer is going to be dumped to the file,
        without sending get() request to the backend server to verify that the bytes
        were actually written. Situation like that should not happen though as if
        the dirty buffer failed to write to the backend, it should throw an exception.
        """
        attr = obj.fgetattr()
        super().flush(path, obj)

        self.update_cache(path, attr)

    def release(self, path: PurePosixPath, flags: int, obj: File) -> None:
        """
        Same performance hack as in flush()
        """
        attr = obj.fgetattr()
        super().release(path, flags, obj)

        self.update_cache(path, attr)

    def unlink(self, path: PurePosixPath):
        self._redis_del(self._generate_key(path))
        self.update_cache(path, None)

    def mkdir(self, path: PurePosixPath, _mode: int = 0o777):
        self._redis_set(self._generate_key(path, is_dir=True), b'')
        self.update_cache(path, Attr.dir())

    def rmdir(self, path: PurePosixPath):
        self._redis_del(self._generate_key(path, is_dir=True))
        self.update_cache(path, None)

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        self._rename(move_from, move_to)

    def truncate(self, path: PurePosixPath, length: int):
        f = RedisFile(self.redis, self._generate_key(path), self.getattr(path))
        f.ftruncate(length)
        f.flush()
        self.update_cache(path, Attr.file(size=length))

    def _rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        """
        Internal recursive handler for rename()
        """
        if self.getattr(move_from).is_dir():
            for obj in self.readdir(move_from):
                self._rename(move_from / obj, move_to / obj)

            self._redis_rename(
                self._generate_key(move_from, is_dir=True),
                self._generate_key(move_to, is_dir=True)
            )

            self.update_cache(move_to, Attr.dir())
            self.update_cache(move_from, None)
        else:
            attr = self.getattr(move_from)

            self._redis_rename(
                self._generate_key(move_from),
                self._generate_key(move_to)
            )

            self.update_cache(move_to, attr)
            self.update_cache(move_from, None)

    def chmod(self, path: PurePosixPath, mode: int):
        logger.debug("chmod dummy op %s mode %d", str(path), mode)

    def chown(self, path: PurePosixPath, uid: int, gid: int):
        logger.debug("chown dummy op %s uid %d gid %d", str(path), uid, gid)

    def utimens(self, path: PurePosixPath, _atime, _mtime) -> None:
        logger.debug("utimens dummy op %s", str(path))

    # pylint: disable=pointless-string-statement
    '''
    Padding helpers section

    To maximize efficiency of keys being fetched from Redis, and Redis lacking Tree structure for
    its keys, as well as, no support for regex queries, there is no way to fetch files from a
    specific "directory". So, for example, having the following keys in Redis DB ...

        /dir/.__dir
        /dir/foo.txt
        /dir/nested_dir/bar.txt

    ... to fetch all files and directories in /dir directory, the query would have to look like so

        ->get('/dir*')

    although this query will return all descendants of /dir and not just the children.

    To optimize that (ref #728), knowing that file names in POSIX must be up to 255 bytes long,
    we pad each file and dir name with a :(colon) character so that each file/dir is represented
    using exactly 256 characters in redis keys. So, the above structure will look like so

        /dir::::(up to 256 total)/.__dir::::(up to 256 total)
        /dir::::(up to 256 total)/foo.txt::::(up to 256 total)
        /dir::::(up to 256 total)/nested_dir::::(up to 256 total)/bar.txt::::(up to 256 total)

    Searching of such keys has still O(1) complexity and the increased query size is still smaller
    than the potential results (ie. when querying a root) by a few orders of magnitude.

    The search queries for a /foo directory listing would then looks like so

        files: ->get('/foo/[256-any-non-slash-characters]')
        dirs:  ->get('/foo/[256-any-non-slash-characters]/.__dir')

    Finally, the keys received from the DB will be normalized (by trimming the paddings)
    '''

    @staticmethod
    def _pad_string(k: str) -> str:
        return k.ljust(256, ':')

    @staticmethod
    def _normalize_key(k: Union[PurePosixPath, str]) -> PurePosixPath:
        return PurePosixPath(str(k).rstrip('/').rstrip(':'))

    def _generate_key(self, path: PurePosixPath, is_dir: bool = False) -> str:
        if is_dir:
            path = path / self.DIRECTORY_PLACEHOLDER

        # Discard first element from the path (it is always "/" since key_prefix *must*
        # be an absolute path)
        parts = (self.key_prefix / path).parts[1:]

        # Add `:` padding to every element in the path and form a new, padded, path
        padded_path = str(PurePosixPath('/', *[self._pad_string(p) for p in parts]))

        return padded_path

    def _prepare_scan_query(self, str_path: str, find_dirs: bool) -> str:
        # If the path was not just '/' (root), append trailing slash
        if str_path != '/':
            str_path += '/'

        # Finally, append the ugly search (MATCH) rule
        str_path += ('[^/]' * 256)

        if find_dirs:
            str_path += '/' + self._pad_string(self.DIRECTORY_PLACEHOLDER)

        return str_path

    def _redis_set(self, key: str, contents: bytes):
        self.redis.set(key, contents)

    def _redis_del(self, key: str):
        self.redis.unlink(key)

    def _redis_rename(self, old: str, new: str):
        self.redis.rename(old, new)
