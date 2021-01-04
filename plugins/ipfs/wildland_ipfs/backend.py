# Wildland Project
#
# Copyright (C) 2021 Golem Foundation,
#                    Pawel Peregud <pepesza@wildland.io>
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
IPFS storage backend
'''

from pathlib import PurePosixPath
from typing import Iterable, Tuple
import logging
from urllib.parse import urlparse
import os
import errno
import stat

import ipfshttpclient
import click

from wildland.storage_backends.base import StorageBackend, Attr
from wildland.storage_backends.buffered import File, FullBufferedFile
from wildland.storage_backends.cached import CachedStorageMixin
from wildland.manifest.schema import Schema
from .unixfsv1_pb2 import Data


logger = logging.getLogger('storage-ipfs')


# pylint: disable=no-member

class IPFSFile(FullBufferedFile):
    '''
    A buffered IPFS file.
    '''

    def __init__(self, client, cid, attr, clear_cache_callback):
        super().__init__(attr, clear_cache_callback)
        self.client = client
        self.cid = cid

    def read_full(self) -> bytes:
        return Data.FromString(self.client.object.data(self.cid)).Data

    def write_full(self, data: bytes) -> int:
        raise IOError(errno.EROFS, str(self.cid))


class IPFSStorageBackend(CachedStorageMixin, StorageBackend):
    '''
    IPFS (readonly) storage.
    '''

    SCHEMA = Schema({
        "title": "Storage manifest (ipfs)",
        "type": "object",
        "required": ["ipfs_hash"],
        "properties": {
            "ipfs_hash": {
                "type": ["string"],
                "description": "IPFS URL, in the ipfs:///ipfs/IPFS_CID or ipfs:///ipns/IPNS_NAME",
                "pattern": "^ipfs://.*$"
            },
            "endpoint_addr": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "null"}
                ],
                "description": "Override default IPFS gateway "
                "(/ip4/127.0.0.1/tcp/8080/http) URL with the given URL."
            }
        }
    })
    TYPE = 'ipfs'

    def __init__(self, **kwds):
        super().__init__(**kwds)

        ipfs_hash = urlparse(self.params['ipfs_hash'])
        assert ipfs_hash.scheme == 'ipfs'
        assert ipfs_hash.netloc == ""

        if 'endpoint_addr' in self.params.keys():
            endpoint = self.params['endpoint_addr']
        else:
            endpoint = '/ip4/127.0.0.1/tcp/8080/http'

        self.client = ipfshttpclient.connect(endpoint)
        self.base_path = PurePosixPath(ipfs_hash.path)
        if ipfs_hash.path[:6] == '/ipns/':
            self.base_path = PurePosixPath(self.client.name.resolve(self.base_path)['Path'])

        resp = self.client.object.stat(self.base_path)
        if self._is_file(resp):
            logger.error("IPFS path points to a file, it cannot be mounted!")
            raise IOError(errno.ENOTDIR, str(self.base_path))

    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--ipfs-hash'], metavar='URL', required=True,
                         help='IPFS cid or IPNS name to access the '
                         'resource in ipfs:///{ipfs,ipns}/{cid,name} format'),
            click.Option(['--endpoint-addr'], metavar='MULTIADDRESS', required=False,
                         help='Override default IPFS gateway address '
                         '(/ip4/127.0.0.1/tcp/8080/http) with the given address.',
                         default='/ip4/127.0.0.1/tcp/8080/http'),
        ]

    @classmethod
    def cli_create(cls, data):
        return {
            'ipfs_hash': data['ipfs_hash'],
            'endpoint_addr': data['endpoint_addr'],
        }

    def key(self, path: PurePosixPath) -> str:
        '''
        Convert path to IPFS path.
        '''
        return str((self.base_path / path))

    @staticmethod
    def _stat(obj) -> Attr:
        '''
        Size is taken from IPFS API reply. Date is not available, so setting it to UNIX EPOCH
        '''
        if 'Size' in obj:
            size = obj['Size']
        else:
            size = obj['DataSize']
        return Attr(
            mode=stat.S_IFREG | 0o444,
            size=size,
            timestamp=1)

    @staticmethod
    def _is_file(obj) -> bool:
        return obj['LinksSize'] + obj['DataSize'] == obj['CumulativeSize']

    def info_all(self) -> Iterable[Tuple[PurePosixPath, Attr]]:
        all_dirs = set()
        to_visit = set()
        to_visit.add(self.base_path)
        while to_visit:
            full_ipfs_path = to_visit.pop()
            relative_path = PurePosixPath(os.path.relpath(full_ipfs_path, self.base_path))
            resp = self.client.object.links(
                full_ipfs_path
            )

            for summary in resp['Links']:
                try:
                    ipfs_path = full_ipfs_path / summary['Name']
                    local_path = relative_path / summary['Name']
                    resp = self.client.object.stat(ipfs_path)
                except ValueError:
                    logger.info("skipping %s", ipfs_path)
                    continue

                if self._is_file(resp):
                    yield local_path, self._stat(summary)
                else:
                    to_visit.add(ipfs_path)
                    all_dirs.add(local_path)

        all_dirs.add(PurePosixPath('.'))
        dir_stat = Attr(
            mode=stat.S_IFDIR | 0o555,
            size=0,
            timestamp=1)
        for dir_path in all_dirs:
            yield dir_path, dir_stat


    def open(self, path: PurePosixPath, flags: int) -> File:

        def clear_cache_noop():
            pass

        key = self.key(path)
        head = self.client.object.stat(key)
        attr = self._stat(head)
        if flags & (os.O_WRONLY | os.O_RDWR):
            return IPFSFile(
                self.client, self.key(path),
                attr, clear_cache_noop)

        return IPFSFile(self.client, self.key(path), attr, clear_cache_noop)


    def truncate(self, path: PurePosixPath, length: int) -> None:
        raise IOError(errno.EROFS, str(path))

    def create(self, path: PurePosixPath, flags: int, mode: int = 0o666):
        raise IOError(errno.EROFS, str(path))
