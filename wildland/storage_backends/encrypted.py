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
from typing import Dict, List, Optional, Type

import click

from wildland.storage_backends.base import StorageBackend, File
from wildland.manifest.schema import Schema
from wildland.storage_backends.local import LocalStorageBackend, LocalFile
from wildland.fs_client import WildlandFSError


logger = logging.getLogger('storage-encrypted')

class EncryptedFSRunner(metaclass=abc.ABCMeta):
    '''
    Abstract base class for cryptographic filesystem runner.

    To be returned from ``init()``.
    '''
    binary: str
    cleartextdir: Optional[PurePosixPath]

    @classmethod
    def init(cls, tempdir: PurePosixPath,
             ciphertextdir: PurePosixPath,
             cleartextdir: PurePosixPath) -> 'EncryptedFSRunner':
        '''
        Initialize and configure a cryptographic filesystem storage.
        ``credentials()`` should be available after that.
        '''
        raise NotImplementedError()

    @abc.abstractmethod
    def __init__(self, tempdir: PurePosixPath,
                 ciphertextdir: PurePosixPath,
                 credentials: Optional[str]):
        raise NotImplementedError()

    @abc.abstractmethod
    def run(self, cleartextdir: PurePosixPath, inner_storage: StorageBackend):
        '''
        Mount and decrypt.
        '''
        raise NotImplementedError()

    # pylint: disable=subprocess-run-check
    def stop(self) -> int:
        '''
        Unmount.
        '''
        if self.cleartextdir is None:
            raise WildlandFSError('Unmounting failed: mount point unknown')
        assert self.cleartextdir.is_absolute()
        cmd = ['fusermount', '-u', str(self.cleartextdir)]
        cproc = subprocess.run(cmd, capture_output=True)
        if cproc.returncode == 0:
            return cproc.returncode
        unmounted_msg = 'fusermount: entry for ' + str(self.cleartextdir) + ' not found in '
        if cproc.stderr.decode().find(unmounted_msg) > -1:
            return 0
        return cproc.returncode

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

# pylint: disable=super-init-not-called
class EncFS(EncryptedFSRunner):
    '''
    Runs encfs via subprocess.

    Relevant issues of encfs:
    * it is not very secure - it may leak last 4k of a file when file is rewritten.
    * it uses FUSE (potential problem on OSX later).
    * it leaks metadata about tree structure, including file sizes, access times,
      number of files and directories inside a directory. It encrypts but does not
      randomize file names - leaking information about file duplicates in a single
      filesystem.
    '''
    password: str
    config: str
    ciphertextdir: PurePosixPath
    cleartextdir: Optional[PurePosixPath]
    opts: List[str]

    def __init__(self, _,
                 ciphertextdir: PurePosixPath,
                 credentials: Optional[str]):
        self.binary = 'encfs'
        self.opts = ['--standard', '--require-macs', '-o', 'direct_io']
        self.ciphertextdir = ciphertextdir
        if credentials is not None:
            self._decode_credentials(credentials)
            assert len(self.password) == 30

    def credentials(self) -> str:
        return self._encode_credentials()

    def _encode_credentials(self):
        assert self.password
        assert self.config
        return self.password+";"+ \
            base64.standard_b64encode(self.config.encode()).decode()

    def _decode_credentials(self, encoded_credentials):
        parts = encoded_credentials.split(';')
        self.password = parts[0]
        self.config = base64.standard_b64decode(parts[1]).decode()

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
                bf.flush()
            bf.release(flags)

        _write_file(PurePosixPath('.encfs6.xml'), self.config.encode())

    def run(self, cleartextdir: PurePosixPath, inner_storage: StorageBackend):
        self.cleartextdir = cleartextdir
        self._write_config(inner_storage)
        assert self.ciphertextdir.is_absolute()
        assert self.cleartextdir.is_absolute()
        args = ['--stdinpass', str(self.ciphertextdir), str(self.cleartextdir)]
        sp, err = self.run_binary(self.opts + args)
        if sp.returncode != 0:
            errmsg = "Failed to mount encrypted filesystem. %s exit code: %d."
            logger.error(errmsg, self.binary, sp.returncode)
            if len(err.decode()) > 0:
                logger.error(err.decode())
            raise WildlandFSError(f'Failed to mount EncFS. EncFS exit code: {sp.returncode}')

    @classmethod
    def init(cls, tempdir: PurePosixPath,
             ciphertextdir: PurePosixPath,
             cleartextdir: PurePosixPath) -> 'EncFS':
        '''
        Create a new, empty encfs storage.

        Loads contents of config created by gocryptfs, so we can store it in the storage manifest.
        '''
        encfs = cls(tempdir, ciphertextdir, None)
        encfs.password = generate_password(30)
        assert encfs.ciphertextdir.is_absolute()
        assert cleartextdir.is_absolute()
        options = encfs.opts + ['--stdinpass', str(encfs.ciphertextdir), str(cleartextdir)]
        sp, err = encfs.run_binary(options)
        if sp.returncode != 0:
            logger.error("Failed to initialize encfs encrypted filesystem.")
            if len(err.decode()) > 0:
                logger.error(err.decode())
            raise WildlandFSError("Can't initialize encfs volume")
        with open(PurePosixPath(encfs.ciphertextdir) / '.encfs6.xml') as tf:
            encfs.config = tf.read()
        encfs.cleartextdir = cleartextdir
        encfs.stop() # required, since encfs has the same command for initialization and mounting
        return encfs

    # pylint: disable=consider-using-with
    def run_binary(self, cmd):
        '''
        For internal use only.
        '''
        cmd = [self.binary] + cmd
        sp = Popen(cmd, stdin=PIPE, stderr=PIPE, stdout=PIPE)
        (_, err) = sp.communicate(input=self.password.encode())
        return (sp, err)


class GoCryptFS(EncryptedFSRunner):
    '''
    Runs gocryptfs via subprocess.

    Relevant issues of gocryptfs:
    * It does not mix well with Wildland since it does not do direct_io.
      You may observe data loss in some scenarios. More information is in
      this thread: https://gitlab.com/wildland/wildland-client/-/issues/205
    * It uses FUSE (potential problem on OSX later).
    * It leaks metadata about tree structure, including file sizes, access times,
      number of files and directories inside a directory.
    * It allows attacker to modify file permission - they are not encrypted.
    * If remote storage operator is malicious, it can do a lot of damage while staying
      undetected. From audit:
      > Files can be fully or partially restored from earlier versions, duplicated,
      > made to have the same contents as another file, deleted, truncated, and moved.
      > These integrity problems could turn into confidentiality problems depending on
      > the applications that use the filesystem.

    For more information, please read audit report:
    https://defuse.ca/downloads/audits/gocryptfs-cryptography-design-audit.pdf
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
            self._decode_credentials(credentials)
            assert len(self.password) == 30

    def credentials(self) -> str:
        return self._encode_credentials()

    def _encode_credentials(self):
        assert self.password
        assert self.config
        assert self.topdiriv
        return self.password+";"+ \
            base64.standard_b64encode(self.config.encode()).decode()+";"+ \
            base64.standard_b64encode(self.topdiriv).decode()

    def _decode_credentials(self, encoded_credentials):
        parts = encoded_credentials.split(';')
        self.password = parts[0]
        self.config = base64.standard_b64decode(parts[1]).decode()
        self.topdiriv = base64.standard_b64decode(parts[2])

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
                bf.flush()
            bf.release(flags)

        _write_file(PurePosixPath('gocryptfs.conf'), self.config.encode())
        _write_file(PurePosixPath('gocryptfs.diriv'), self.topdiriv)

    def run(self, cleartextdir: PurePosixPath, inner_storage: StorageBackend):
        self.cleartextdir = cleartextdir
        self._write_config(inner_storage)
        out, sp = self.run_binary(['-passfile'], ['--', self.ciphertextdir, self.cleartextdir])
        if sp.returncode != 0:
            errmsg = "Failed to mount %s encrypted filesystem"
            logger.error(errmsg, self.binary)
            if len(out.decode()) > 0:
                logger.error(out.decode())
            raise WildlandFSError("Can't mount gocryptfs")

    @classmethod
    def init(cls, tempdir: PurePosixPath, ciphertextdir: PurePosixPath, _) -> 'GoCryptFS':
        '''
        Create a new, empty gocryptfs storage.

        Loads contents of config and top directory's IV files
        created by gocryptfs, so we can store them in the storage manifest.
        '''
        gcfs = cls(tempdir, ciphertextdir, None)
        gcfs.password = generate_password(30)
        out, sp = gcfs.run_binary(['-init', '-passfile'], ['--', gcfs.ciphertextdir])
        if sp.returncode != 0:
            msg = "Failed to initialize encrypted filesystem. Reason: %s"
            raise WildlandFSError(msg % out.decode())
        with open(PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.conf') as tf:
            gcfs.config = tf.read()
        with open(PurePosixPath(gcfs.ciphertextdir) / 'gocryptfs.diriv', 'rb') as bf:
            gcfs.topdiriv = bf.read()
        return gcfs

    # pylint: disable=consider-using-with
    def run_binary(self, cmd1, cmd2):
        '''
        For internal use only.
        '''
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
        return (out, sp)

class FileOnAMount(LocalFile):
    '''
    When writing / reading, adds a check if mount is still a mount.

    Example scenario - engine (EncFS or GoCryptFS) process is killed by OOM,
    user attempts to write to a file, file ends up on unencrypted partition.
    '''
    def __init__(self, *args, **kwargs):
        self.mount_path = Path(kwargs.pop('mount_path'))
        super().__init__(*args, **kwargs)

    def write(self, *args, **kwarg):
        if not self.mount_path.is_mount():
            raise WildlandFSError('Encrypted filesystem is no longer mounted, can\'t write data')
        return super().write(*args, **kwarg)

    def flush(self):
        if not self.mount_path.is_mount():
            raise WildlandFSError('Encrypted filesystem is no longer mounted, can\'t write data')
        return super().flush()


engines: Dict[str, Type['EncryptedFSRunner']] = {
    'encfs': EncFS,
    'gocryptfs': GoCryptFS
}

# pylint: disable=no-member

class EncryptedStorageBackend(StorageBackend):
    '''
    The 'reference-container' parameter specifies inner container, either as URL,
    or as an inline manifest. When creating the object instance:

    1. First, the storage parameters for the inner container will be resolved
    (see Client.select_storage()),

    2. Then, the inner storage backend will be instantiated and passed as
    params['storage'] (see StorageBackend.from_params()).
    '''

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

    engine_obj: Optional[EncryptedFSRunner]
    engine_cls: Type[EncryptedFSRunner]
    engine: str

    TYPE = 'encrypted'
    MOUNT_REFERENCE_CONTAINER = True


    def __init__(self, **kwds):
        super().__init__(**kwds)

        self.read_only = False
        self.credentials = kwds['params']['symmetrickey']
        self.engine = kwds['params']['engine']
        self.reference_container = kwds['params']['reference-container']
        self.engine_obj = None
        self.engine_cls = engines[self.engine]

        alphabet = string.ascii_letters + string.digits
        default = Path('~/.local/share/').expanduser()
        mountid = ''.join(secrets.choice(alphabet) for i in range(15))
        tmpdir = PurePosixPath(os.getenv('XDG_DATA_HOME', default)) / 'wl' / 'encrypted'
        self.tmpdir_path =  tmpdir / mountid / self.engine
        self.cleartext_path = tmpdir / mountid / 'cleartext'
        Path(self.tmpdir_path).mkdir(parents=True)
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

        # StorageBackend instance matching reference-container
        self.ciphertext_storage = self.params['storage']

        # The path where it got mounted
        self.ciphertext_path = PurePosixPath(self.params['storage-path'])


    @classmethod
    def cli_options(cls):
        return [
            click.Option(['--reference-container-url'], metavar='URL',
                         help='URL for inner container manifest',
                         required=True),
            click.Option(['--engine'], metavar='ENGINE',
                         help='Cryptographic filesystem to use: gocryptfs or encfs.',
                         default="gocryptfs",
                         required=False),
        ]

    @classmethod
    def cli_create(cls, data):
        engine = engines[data['engine']]
        with tempfile.TemporaryDirectory(prefix='encrypted-temp-dir.') as d:
            d1 = PurePosixPath(d) / 'encrypted'
            d2 = PurePosixPath(d) / 'plain'
            Path(d1).mkdir()
            Path(d2).mkdir()
            runner = engine.init(PurePosixPath(d), d1, d2)
        return {'reference-container': data['reference_container_url'],
                'symmetrickey': runner.credentials(),
                'engine': data['engine']
                }

    # pylint: disable=protected-access
    def open(self, path: PurePosixPath, flags: int) -> File:
        if self.local.ignore_own_events and self.local.watcher_instance:
            return FileOnAMount(path, self.local._path(path), flags,
                                mount_path=self.cleartext_path,
                                ignore_callback=self.local.watcher_instance.ignore_event)
        return FileOnAMount(path, self.local._path(path), flags,
                            mount_path=self.cleartext_path)

    def create(self, path: PurePosixPath, flags: int, mode: int=0o666) -> File:
        if self.local.ignore_own_events and self.local.watcher_instance:
            self.local.watcher_instance.ignore_event('create', path)
            return FileOnAMount(path, self.local._path(path), flags, mode,
                                mount_path=self.cleartext_path,
                                ignore_callback=self.local.watcher_instance.ignore_event)
        return FileOnAMount(path, self.local._path(path), flags, mode,
                            mount_path=self.cleartext_path)

    def getattr(self, path: PurePosixPath):
        return self.local.getattr(path)

    def readdir(self, path: PurePosixPath):
        return self.local.readdir(path)

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
        # If ciphertext_path is not available, ask user to mount it!
        if Path(self.ciphertext_path).exists():
            self.engine_obj = self.engine_cls(self.tmpdir_path,
                                              self.ciphertext_path,
                                              self.credentials)
            self.engine_obj.run(self.cleartext_path, self.ciphertext_storage)
            self.local.request_mount()
        else:
            raise WildlandFSError(f'Please run `wl c mount {self.reference_container}` first.')

    def unmount(self) -> None:
        if self.engine_obj is not None:
            self.local.request_unmount()
            if self.engine_obj.stop() != 0:
                raise WildlandFSError('Unmounting failed: mount point is busy')
            self.engine_obj = None
