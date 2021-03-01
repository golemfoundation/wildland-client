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

import os
import abc
import base64
import subprocess
import tempfile
from subprocess import Popen, PIPE
from pathlib import PurePosixPath, Path
import logging
import secrets
import string
from typing import Optional

import click

from wildland.storage_backends.base import StorageBackend, File, OptionalError
from wildland.manifest.schema import Schema
from wildland.storage_backends.local import LocalStorageBackend
from wildland.fs_client import WildlandFSError


logger = logging.getLogger('storage-encrypted')

class EncryptedFSRunner(metaclass=abc.ABCMeta):
    '''
    Abstract base class for cryptographic filesystem runner.

    To be returned from ``init()``.
    '''
    binary: str

    @classmethod
    def init(cls, basedir: PurePosixPath, ciphertextdir: PurePosixPath) -> 'EncryptedFSRunner':
        '''
        Initialize and configure a cryptographic filesystem storage.
        ``credentials()`` should be available after that.
        '''
        raise NotImplementedError()

    @abc.abstractmethod
    def run(self, cleartextdir: PurePosixPath):
        '''
        Mount and decrypt.
        '''
        raise NotImplementedError()

    @abc.abstractmethod
    def stop(self):
        '''
        Unmount.
        '''
        raise NotImplementedError()

    def reencrypt(self, credentials: str):
        """
        Implements in-place re-encryption to a new key material / password.

        If not implemented, 'copy-to-a-new-encrypted-container' approach will be used.
        """
        raise OptionalError()

    @abc.abstractmethod
    def credentials(self) -> str:
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

def _encode_credentials(password, config, topdiriv):
    assert password
    assert config
    assert topdiriv
    return password+";"+ \
        base64.standard_b64encode(config.encode()).decode()+";"+ \
        base64.standard_b64encode(topdiriv).decode()

def _decode_credentials(encoded_credentials):
    parts = encoded_credentials.split(';')
    password = parts[0]
    config = base64.standard_b64decode(parts[1]).decode()
    topdiriv = base64.standard_b64decode(parts[2])
    return (password, config, topdiriv)

class GoCryptFS(EncryptedFSRunner):
    '''
    Runs gocryptfs via subprocess.
    '''
    password: str
    config: str
    topdiriv: bytes
    ciphertextdir: PurePosixPath
    cleartextdir: Optional[PurePosixPath]

    def __init__(self, basedir: PurePosixPath,
                 ciphertextdir: PurePosixPath,
                 credentials: Optional[str]):
        self.binary = 'gocryptfs'
        self.ciphertextdir = ciphertextdir
        self.basedir = basedir
        if credentials is not None:
            (self.password, self.config, self.topdiriv) = _decode_credentials(credentials)

    def credentials(self) -> str:
        return _encode_credentials(self.password, self.config, self.topdiriv)

    def _write_config(self):
        config_fn = self.ciphertextdir / 'gocryptfs.conf'
        if not config_fn.exists():
            with open(config_fn, 'w') as tf:
                tf.write(self.config)
        diriv_fn = self.ciphertextdir / 'gocryptfs.diriv'
        if not diriv_fn.exists():
            with open(diriv_fn, 'wb') as bf:
                bf.write(self.topdiriv)

    def run(self, cleartextdir):
        self._write_config()
        self.cleartextdir = cleartextdir
        fn = self.basedir / 'gocryptfs-password-pipe2'
        try:
            os.mkfifo(fn)
        except FileExistsError:
            pass
        cmd = [self.binary, '-passfile', fn, self.ciphertextdir, self.cleartextdir]
        sp = Popen(cmd, stdout=PIPE)
        with open(fn, 'w') as f:
            f.write(self.password)
            f.flush()
        out, _ = sp.communicate()
        assert out.decode().find('Filesystem mounted and ready.') > -1
        os.unlink(fn)

    def stop(self):
        if self.cleartextdir is None:
            raise WildlandFSError('Unmounting failed: mount point unknown')
        res = subprocess.run(['umount', self.cleartextdir], check=True)
        return res.returncode

    @classmethod
    def init(cls, basedir: PurePosixPath, ciphertextdir: PurePosixPath) -> 'GoCryptFS':
        '''
        Create a new, empty gocryptfs storage.

        Loads contents of config and top directory's IV files
        created by gocryptfs, so we can store them in the storage manifest.
        '''
        gcfs = cls(basedir, ciphertextdir, None)
        gcfs.password = generate_password(30)
        passwordpipe = basedir / 'gocryptfs-password-pipe'
        try:
            os.mkfifo(passwordpipe)
        except FileExistsError:
            pass
        cmd = [gcfs.binary, '-init', '-passfile', passwordpipe, gcfs.ciphertextdir]
        sp = Popen(cmd, stdout=PIPE)
        with open(passwordpipe, 'w') as f:
            f.write(gcfs.password)
            f.flush()
        out, _ = sp.communicate()
        os.unlink(passwordpipe)
        assert out.decode().find('filesystem has been created successfully') > -1
        with open(PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.conf') as tf:
            gcfs.config = tf.read()
        with open(PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.diriv', 'rb') as bf:
            gcfs.topdiriv = bf.read()
        return gcfs

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
        print("INIT kwds", kwds)
        print("INIT kwds", dir(kwds))
        super().__init__(**kwds)

        self.read_only = False
        # TODO: find a place for this location
        self.cleartext_path = PurePosixPath('/tmp/enc.cleartext')
        local_params = {'location': self.cleartext_path,
                        'type': 'local'}
        self._gen_backend_id(local_params)
        self.local = LocalStorageBackend(params=local_params)

        self.params['storage-path'] = PurePosixPath('/home/pepesza/wildland/encrypted/')

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
        with tempfile.TemporaryDirectory(prefix='gocryptfs-encrypted-temp-dir.') as d:
            d1 = PurePosixPath(d)
            os.mkdir(d1 / 'encrypted')
            runner = GoCryptFS.init(d1, d1 / 'encrypted')
        return {'reference-container': data['reference_container_url'],
                'symmetrickey': runner.credentials()}

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

    def mount(self) -> None:
        logger.warning("mount")

    def unmount(self) -> None:
        logger.warning("unmount")
