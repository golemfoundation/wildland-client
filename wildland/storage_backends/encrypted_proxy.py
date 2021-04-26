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
    def init(cls, tempdir: PurePosixPath, ciphertextdir: PurePosixPath) -> 'EncryptedFSRunner':
        '''
        Initialize and configure a cryptographic filesystem storage.
        ``credentials()`` should be available after that.
        '''
        raise NotImplementedError()

    @abc.abstractmethod
    def run(self, cleartextdir: PurePosixPath, inner_storage: StorageBackend):
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

    # pylint: disable=no-self-use
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

    Relevant issues of gocryptfs:
    * it uses FUSE (potential problem on OSX later)
    * it leaks metadata about tree structure
    * it allows attacker to modify file permission - they are not encrypted
    '''
    password: str
    config: str
    topdiriv: bytes
    ciphertextdir: PurePosixPath
    cleartextdir: Optional[PurePosixPath]

    def __init__(self, tmpdir: PurePosixPath,
                 ciphertextdir: PurePosixPath,
                 credentials: Optional[str]):
        self.binary = 'gocryptfs'
        self.tmpdir = tmpdir
        self.ciphertextdir = ciphertextdir
        if credentials is not None:
            (self.password, self.config, self.topdiriv) = _decode_credentials(credentials)
            assert len(self.password) == 30

    def credentials(self) -> str:
        return _encode_credentials(self.password, self.config, self.topdiriv)

    def _write_config(self, storage: StorageBackend):

        def _write_file(path: PurePosixPath, data: bytes):
            '''
            Write file, if it does not exist already
            '''
            flags = os.O_WRONLY | os.O_APPEND
            try:
                bf = storage.open(path, flags)
            except FileNotFoundError:
                flags = flags | os.O_CREAT
                bf = storage.create(path, flags)
                bf.write(data, 0)
            bf.release(flags)

        _write_file(PurePosixPath('gocryptfs.conf'), self.config.encode())
        _write_file(PurePosixPath('gocryptfs.diriv'), self.topdiriv)

    def run(self, cleartextdir: PurePosixPath, inner_storage: StorageBackend):
        self.cleartextdir = cleartextdir
        self._write_config(inner_storage)
        out = self._run_binary(['-passfile'], ['--', self.ciphertextdir, self.cleartextdir])
        if out.decode().find('Filesystem mounted and ready.') == -1:
            logger.error("FAILED TO MOUNT THE ENCRYPTED FILESYSTEM")
            logger.error(out.decode())
            raise WildlandFSError("Can't mount gocryptfs")

    def stop(self):
        if self.cleartextdir is None:
            raise WildlandFSError('Unmounting failed: mount point unknown')
        res = subprocess.run(['fusermount', '-u', self.cleartextdir], check=True)
        return res.returncode

    @classmethod
    def init(cls, tempdir: PurePosixPath, ciphertextdir: PurePosixPath) -> 'GoCryptFS':
        '''
        Create a new, empty gocryptfs storage.

        Loads contents of config and top directory's IV files
        created by gocryptfs, so we can store them in the storage manifest.
        '''
        gcfs = cls(tempdir, ciphertextdir, None)
        gcfs.password = generate_password(30)
        out = gcfs._run_binary(['-init', '-passfile'], ['--', gcfs.ciphertextdir])
        assert out.decode().find('filesystem has been created successfully') > -1
        with open(PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.conf') as tf:
            gcfs.config = tf.read()
        with open(PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.diriv', 'rb') as bf:
            gcfs.topdiriv = bf.read()
        return gcfs

    def _run_binary(self, cmd1, cmd2):
        passwordpipe = self.tmpdir / 'password-pipe'
        try:
            os.mkfifo(passwordpipe)
        except FileExistsError:
            pass
        cmd = [self.binary] + cmd1  + [passwordpipe] + cmd2
        sp = Popen(cmd, stdout=PIPE)
        with open(passwordpipe, 'w') as f:
            f.write(self.password)
            f.flush()
        out, _ = sp.communicate()
        os.unlink(passwordpipe)
        return out

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

    # TODO update schema to use oneOf for engine
    # TODO revisit "symmetrickey" name
    SCHEMA = Schema({
        "type": "object",
        "required": ["reference-container", "symmetrickey", "engine"],
        "properties": {
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

    engine_obj: EncryptedFSRunner
    engine: str

    TYPE = 'encrypted-proxy'
    MOUNT_REFERENCE_CONTAINER = True

    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.read_only = False
        self.credentials = kwds['params']['symmetrickey']
        self.engine = kwds['params']['engine']

        alphabet = string.ascii_letters + string.digits
        mountid = ''.join(secrets.choice(alphabet) for i in range(15))
        tmpdir = PurePosixPath(os.getenv('XDG_RUNTIME_DIR', '/tmp/')) / 'wl' / 'encrypted'
        self.tmpdir_path =  tmpdir / mountid / self.engine
        Path(self.tmpdir_path).mkdir(parents=True)
        # Specification says that XDG_RUNTIME_DIR might be cleaned up automatically every 6 hours.
        # That would mean data loss if container is mounted. Thus cleartext is mounted to /tmp/...
        # Specification offers workarounds (updating timestamps, setting sticky bit) but they
        # don't look good since they interefe with user's data.
        # https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html
        self.cleartext_path = PurePosixPath('/tmp') / 'wl' / 'encrypted' / mountid / 'cleartext'
        Path(self.cleartext_path).mkdir(parents=True)
        local_params = {'location': self.cleartext_path,
                        'type': 'local',
                        'owner': kwds['params']['owner'],
                        'is-local-owner': True,
                        'backend-id': mountid + '/cleartext'
                        }
        self.local = LocalStorageBackend(params=local_params)

        # below parameters are automatically generated based on
        # reference-container and MOUNT_REFERENCE_CONTAINER flag

        # StorageBackend instance matching reference-container (this
        # currently exists)
        self.ciphertext_storage = self.params['storage']

        # the path where it got mounted (this is new)
        self.ciphertext_path = self.params['storage-path']


    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'], metavar='URL',
                         help='URL for inner container manifest',
                         required=True),
        ]

    @classmethod
    def cli_create(cls, data):
        with tempfile.TemporaryDirectory(prefix='gocryptfs-encrypted-temp-dir.') as d:
            d1 = PurePosixPath(d) / 'encrypted'
            Path(d1).mkdir()
            runner = GoCryptFS.init(PurePosixPath(d), d1)
        return {'reference-container': data['reference_container_url'],
                'symmetrickey': runner.credentials(),
                'engine': 'gocryptfs'
                }

    def open(self, path: PurePosixPath, flags: int) -> File:
        return self.local.open(path, flags)

    def getattr(self, path: PurePosixPath):
        return self.local.getattr(path)

    def readdir(self, path: PurePosixPath):
        return self.local.readdir(path)

    def create(self, path: PurePosixPath, flags, mode=0o666):
        return self.local.create(path, flags, mode)

    def truncate(self, path: PurePosixPath, length: int) -> None:
        return self.local.truncate(path, length)

    def unlink(self, path: PurePosixPath):
        return self.local.unlink(path)

    def mkdir(self, path: PurePosixPath, mode: int = 0o777) -> None:
        return self.local.mkdir(path, mode)

    def rmdir(self, path: PurePosixPath) -> None:
        return self.local.rmdir(path)

    def chmod(self, path: PurePosixPath, mode: int) -> None:
        return self.local.chmod(path, mode)

    def chown(self, path: PurePosixPath, uid: int, gid: int) -> None:
        return self.local.chown(path, uid, gid)

    def rename(self, move_from: PurePosixPath, move_to: PurePosixPath):
        return self.local.rename(move_from, move_to)

    def utimens(self, path: PurePosixPath, atime, mtime) -> None:
        return self.local.utimens(path, atime, mtime)

    def mount(self) -> None:
        self.engine_obj = GoCryptFS(self.tmpdir_path, self.ciphertext_path, self.credentials)
        self.engine_obj.run(self.cleartext_path, self.ciphertext_storage)
        self.local.request_mount()

    def unmount(self) -> None:
        self.local.request_unmount()
        self.engine_obj.stop()
