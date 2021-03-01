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
Encrypted proxy backend
'''

import abc
import enum
import subprocess
import tempfile
from subprocess import Popen, PIPE
from pathlib import PurePosixPath
from typing import Iterable, Tuple
import logging
import errno
import secrets
import stat
import string
from typing import List, Optional

import click

from wildland.storage_backends.base import StorageBackend, File, Attr, OptionalError
from wildland.manifest.schema import Schema
from wildland.storage_backends.local import LocalFile, LocalStorageBackend


logger = logging.getLogger('storage-encrypted')

class AbsRunner(metaclass=abc.ABCMeta):
    binary: str

    @abc.abstractmethod
    def run(self):
        raise NotImplementedError()

    @classmethod
    def init(cls):
        raise NotImplementedError()

    @abc.abstractmethod
    def stop(self):
        raise NotImplementedError()

    def reencrypt(self):
        """
        Implements in-place re-encryption to a new key material / password.

        If not implemented, 'copy-to-a-new-encrypted-container' approach will be used.
        """
        raise OptionalError()

    @abc.abstractmethod
    def credentials(self):
        '''
        Return serialized credentials.
        '''
        raise NotImplementedError()

def generate_password(length: int) -> str:
    '''
    Generates an alphanumeric password.

    Note that credentials parsing assumes that password does not contain semicolon (';')
    '''
    alphabet = string.ascii_letters + string.digits
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password

class GoCryptFS(AbsRunner):
    '''
    Runs gocryptfs via subprocess.
    '''
    binary = 'gocryptfs'
    helper = 'gocryptfs-xray'
    masterkey: str
    password: str

    def __init__(self, ciphertextdir: PurePosixPath, cleartextdir: PurePosixPath, credentials: Optional[str]):
        self.ciphertextdir = ciphertextdir
        self.cleartextdir = cleartextdir
        if credentials:
            pos = credentials.index(';')
            self.password = credentials[:pos]
            self.masterkey = credentials[pos+1:]

    def credentials(self):
        assert self.password
        assert self.masterkey
        return self.password+";"+self.masterkey

    def run(self):
        cmd = [self.binary, '-masterkey', 'stdin', self.ciphertextdir, self.cleartextdir]
        p = Popen(cmd, stdin=PIPE)
        p.stdin.write((self.masterkey+'\n').encode())
        p.stdin.flush() # will not unlock without this buffer flush
        # TODO: grep "Filesystem mounted and ready" to avoid returning too early instead of sleeping
        import time
        time.sleep(1)

    def stop(self):
        # TODO A more portable way is needed!
        res = subprocess.run(['umount', self.cleartextdir])
        return res.returncode

    @classmethod
    def init(cls, ciphertextdir: PurePosixPath, cleartextdir: PurePosixPath) -> Optional['GoCryptFS']:
        '''
        Create a new, empty gocryptfs storage.

        Unfortunately requires two steps, since gocryptfs detects if stdout is being captured and hides the masterkey.
        Fortunately, tool that extracts the masterkey is packaged with gocryptfs.
        '''
        gcfs = cls(ciphertextdir, cleartextdir, None)
        gcfs.password = generate_password(20)
        # TODO move tempdir to a secure location (WL operated FUSE mount point?)
        # Otherwise password might be written into an unencrypted storage.
        # Alternatively, input the password via stdin (possibly brittle?)
        with tempfile.TemporaryDirectory(prefix='gocryptfs-password.') as d:
            fn = PurePosixPath(d) / 'file'
            with open(fn, 'w') as f:
                f.write(gcfs.password) # writes with a newline
            cmd = [gcfs.binary, '-init', '-passfile', fn, gcfs.ciphertextdir]
            res = subprocess.run(cmd)
            assert res.returncode == 0
        cmd = [gcfs.helper, '-dumpmasterkey', PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.conf']
        res = subprocess.run(cmd, capture_output=True, input=(gcfs.password + '\n').encode())
        if res.returncode == 0:
            gcfs.masterkey = res.stdout.decode()[:-1]
            return gcfs
        return None

# pylint: disable=no-member

class EncryptedProxyStorageBackend(StorageBackend):
    '''
    The 'reference-container' parameter specifies inner container, either as URL,
    or as an inline manifest. When creating the object instance:

    1. First, the storage parameters for the inner container will be resolved
    (see Client.select_storage()),

    2. Then, the inner storage backend will be instantiated and passed as
    params['storage'] (see StorageBackend.from_params()).
    '''

    # TODO reevaluate separate engines idea
    # TODO reevaluate schema containing engine parameters string
    # TODO update schema to use oneOf for engine
    SCHEMA = Schema({
        "type": "object",
        "required": ["reference-container", "symmetrickey"],
        "properties": {
            "engine-options": {
                "type": "string"
            },
            "engine": {
                "type": "string"
            },
            "symmetrickey": {
                "type": "string"
            },
            "reference-container": {
                "oneOf": [
                    {"$ref": "/schemas/types.json#url"},
                    {"$ref": "/schemas/container.schema.json"}
                ],
                "description": ("Container to be used, either as URL "
                                "or as an inlined manifest"),
            },
        }
    })

    TYPE = 'encrypted-proxy'
    MOUNT_REFERENCE_CONTAINER = True

    def __init__(self, **kwds):
        logger.warning("INIT", kwds)
        super().__init__(**kwds)

        self.read_only = False
        # TODO: find a place for this location
        self.cleartext_path = PurePosixPath('/tmp/enc.cleartext')
        local_params = {'location': self.cleartext_path,
                        'type': 'local'}
        self._gen_backend_id(local_params)
        self.local = LocalStorageBackend(params=local_params)

        self.params['storage-path'] = PurePosixPath('/home/pepesza/wildland/remote/')

        # below parameters are automatically generated based on
        # reference-container and MOUNT_REFERENCE_CONTAINER flag

        # StorageBackend instance matching reference-container (this
        # currently exists)
        self.ciphertext_storage = self.params['storage']

        # the path where it got mounted (this is new)
        self.ciphertext_path = self.params['storage-path']

    def _gen_backend_id(self, params):
        # TODO fix this garbage
        import hashlib
        import yaml
        import uuid
        hasher = hashlib.md5()
        params_for_hash = dict((k, v) for (k, v) in params.items()
                               if k != 'storage')
        hasher.update(yaml.dump(params_for_hash, sort_keys=True).encode('utf-8'))
        params['backend-id'] = str(uuid.UUID(hasher.hexdigest()))


    @classmethod
    def cli_options(cls):
        logger.warning("cli_options")
        return [
            click.Option(['--reference-container-url'], metavar='URL',
                         help='URL for inner container manifest',
                         required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        logger.warning("cli_create")
        # TODO do a real key generation here
        return {'reference-container': data['reference_container_url'],
                'symmetrickey': '741A2eEB4b69EfB229Ae70FC805cbc1BbCDA629'}

    def open(self, path: PurePosixPath, flags: int) -> File:
        return self.local.open(path, flags)

    def getattr(self, path: PurePosixPath):
        return self.local.getattr(path)

    def readdir(self, path: PurePosixPath):
        return self.local.readdir(path)

    def create(self, path: PurePosixPath, flags, mode=0o666):
        return self.local.create(path, flags, mode)

    def unlink(self, path: PurePosixPath):
        return self.local.unlink(path)

