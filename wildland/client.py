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
Client class
'''

from pathlib import Path
import logging
from typing import Optional, Iterator, List
from urllib.parse import urlparse, quote

from .user import User
from .container import Container
from .storage import Storage
from .wlpath import WildlandPath
from .manifest.sig import DummySigContext, SignifySigContext
from .manifest.manifest import ManifestError
from .session import Session
from .storage_backends.base import StorageBackend
from .fs_client import WildlandFSClient

from .config import Config
from .exc import WildlandError

logger = logging.getLogger('client')


class Client:
    '''
    A high-level interface for operating on Wildland objects.
    '''

    def __init__(
            self,
            base_dir=None,
            sig=None,
            config=None,
            **config_kwargs
    ):
        if config is None:
            config = Config.load(base_dir)
            config.override(**config_kwargs)
        self.config = config

        self.user_dir = Path(self.config.get('user_dir'))
        self.container_dir = Path(self.config.get('container_dir'))
        self.storage_dir = Path(self.config.get('storage_dir'))

        mount_dir = Path(self.config.get('mount_dir'))
        self.fs_client = WildlandFSClient(mount_dir)

        if sig is None:
            if self.config.get('dummy'):
                sig = DummySigContext()
            else:
                key_dir = Path(self.config.get('key_dir'))
                sig = SignifySigContext(key_dir)

        self.session: Session = Session(sig)

        self.users: List[User] = []

    def sub_client_with_key(self, pubkey: str) -> 'Client':
        '''
        Create a copy of the current Client, with a public key imported.
        '''

        sig = self.session.sig.copy()
        sig.add_pubkey(pubkey)
        return Client(config=self.config, sig=sig)

    def recognize_users(self):
        '''
        Load and recognize users from the users directory.
        '''

        for user in self.load_users():
            self.users.append(user)
            self.session.recognize_user(user)

    def load_users(self) -> Iterator[User]:
        '''
        Load users from the users directory.
        '''

        if self.user_dir.exists():
            for path in sorted(self.user_dir.glob('*.yaml')):
                try:
                    user = self.load_user_from_path(path)
                except WildlandError as e:
                    logger.warning('error loading user manifest: %s: %s',
                                   path, e)
                else:
                    yield user

    def load_user_from_path(self, path: Path) -> User:
        '''
        Load user from a local file.
        '''

        return self.session.load_user(path.read_bytes(), path)

    def load_user_from(self, name: Optional[str]) -> User:
        '''
        Load a user based on a (potentially ambiguous) name.
        '''

        # Default user
        if name is None:
            default_user = self.config.get('default_user')
            if default_user is None:
                raise WildlandError('user not specified and default_user not set')
            return self.load_user_from(default_user)

        # Short name
        if not name.endswith('.yaml'):
            path = self.user_dir / f'{name}.yaml'
            if path.exists():
                return self.load_user_from_path(path)

        # Key
        if name.startswith('0x'):
            for user in self.load_users():
                if user.signer == name:
                    return user

        # Local path
        path = Path(name)
        if path.exists():
            return self.load_user_from_path(path)

        raise ManifestError(f'User not found: {name}')

    def load_containers(self) -> Iterator[Container]:
        '''
        Load containers from the containers directory.
        '''

        if self.container_dir.exists():
            for path in sorted(self.container_dir.glob('*.yaml')):
                try:
                    container = self.load_container_from_path(path)
                except WildlandError as e:
                    logger.warning('error loading container manifest: %s: %s',
                                   path, e)
                else:
                    yield container

    def load_container_from_path(self, path: Path) -> Container:
        '''
        Load container from a local file.
        '''

        trusted_signer = self.fs_client.find_trusted_signer(path)
        return self.session.load_container(
            path.read_bytes(), path,
            trusted_signer=trusted_signer)

    def load_container_from_wlpath(self, wlpath: WildlandPath) -> Container:
        '''
        Load a container from WildlandPath.
        '''

        # TODO: Still a circular dependency with search
        # pylint: disable=import-outside-toplevel, cyclic-import
        from .search import Search
        search = Search(self, wlpath)
        return search.read_container(remote=True)

    def load_container_from(self, name: str) -> Container:
        '''
        Load a container based on a (potentially ambiguous) name.
        '''

        # Wildland path
        if WildlandPath.match(name):
            wlpath = WildlandPath.from_str(name)
            return self.load_container_from_wlpath(wlpath)

        # Short name
        if not name.endswith('.yaml'):
            path = self.container_dir / f'{name}.yaml'
            if path.exists():
                return self.load_container_from_path(path)

        # Local path
        path = Path(name)
        if path.exists():
            return self.load_container_from_path(path)

        raise ManifestError(f'Container not found: {name}')

    def load_storages(self) -> Iterator[Storage]:
        '''
        Load storages from the storage directory.
        '''

        if self.storage_dir.exists():
            for path in sorted(self.storage_dir.glob('*.yaml')):
                try:
                    storage = self.load_storage_from_path(path)
                except WildlandError as e:
                    logger.warning('error loading storage manifest: %s: %s',
                                   path, e)
                else:
                    yield storage

    def load_storage_from_path(self, path: Path) -> Storage:
        '''
        Load storage from a local file.
        '''

        trusted_signer = self.fs_client.find_trusted_signer(path)
        return self.session.load_storage(
            path.read_bytes(), path,
            trusted_signer=trusted_signer)

    def load_storage_from_url(self, url: str, signer: str) -> Storage:
        '''
        Load storage from URL.
        '''

        return self.session.load_storage(self.read_from_url(url, signer))

    def load_storage_from(self, name: str) -> Storage:
        '''
        Load a storage based on a (potentially ambiguous) name.
        '''

        # Short name
        if not name.endswith('.yaml'):
            path = self.storage_dir / f'{name}.yaml'
            if path.exists():
                return self.load_storage_from_path(path)

        # Local path
        path = Path(name)
        if path.exists():
            return self.load_storage_from_path(path)

        raise ManifestError(f'Storage not found: {name}')

    def save_user(self, user: User, path: Optional[Path] = None) -> Path:
        '''
        Save a user manifest. If path is None, the user has to have
        local_path set.
        '''

        path = path or user.local_path
        assert path is not None
        path.write_bytes(self.session.dump_user(user))
        user.local_path = path
        return path

    def save_new_user(self, user: User, name: Optional[str] = None) -> Path:
        '''
        Save a new user in the user directory. Use the name as a hint for file
        name.
        '''

        path = self._new_path(self.user_dir, name or user.signer)
        path.write_bytes(self.session.dump_user(user))
        user.local_path = path
        return path

    def save_container(self, container: Container, path: Optional[Path] = None) -> Path:
        '''
        Save a container manifest. If path is None, the container has to have
        local_path set.
        '''

        path = path or container.local_path
        assert path is not None
        path.write_bytes(self.session.dump_container(container))
        return path

    def save_new_container(self, container: Container, name: Optional[str] = None) -> Path:
        '''
        Save a new container in the container directory. Use the name as a hint for file
        name.
        '''

        ident = container.ensure_uuid()
        path = self._new_path(self.container_dir, name or ident)
        path.write_bytes(self.session.dump_container(container))
        container.local_path = path
        return path

    def save_new_storage(self, storage: Storage, name: Optional[str] = None) -> Path:
        '''
        Save a new storage in the storage directory. Use the name as a hint for file
        name.
        '''

        path = self._new_path(self.storage_dir, name or storage.container_path.name)
        path.write_bytes(self.session.dump_storage(storage))
        storage.local_path = path
        return path

    @staticmethod
    def _new_path(base_dir: Path, name: str) -> Path:
        if not base_dir.exists():
            base_dir.mkdir(parents=True)

        i = 0
        while True:
            suffix = '' if i == 0 else f'.{i}'
            path = base_dir / f'{name}{suffix}.yaml'
            if not path.exists():
                return path
            i += 1

    def select_storage(self, container: Container) -> Storage:
        '''
        Select a storage to mount for a container.
        '''

        for url in container.backends:
            try:
                storage = self.load_storage_from_url(url, container.signer)
            except WildlandError:
                logging.exception('Error loading manifest: %s', url)
                continue

            if storage.signer != container.signer:
                logging.error(
                    '%s: signer field mismatch: storage %s, container %s',
                    url,
                    storage.signer,
                    container.signer
                )
                continue

            if storage.container_path not in container.paths:
                logging.error(
                    '%s: unrecognized container path for storage: %s, %s',
                    url,
                    storage.container_path,
                    container.paths
                )
                continue

            if not StorageBackend.is_type_supported(storage.storage_type):
                logging.warning('Unsupported storage manifest: %s', url)
                continue

            return storage

        raise ManifestError('no supported storage manifest')

    def read_from_url(self, url: str, signer: str) -> bytes:
        '''
        Retrieve data from a given URL. The local (file://) URLs
        are recognized based on the 'local_hostname' and 'local_signers'
        settings.
        '''

        parse_result = urlparse(url)
        if parse_result.scheme == 'file':
            hostname = parse_result.netloc or 'localhost'
            local_hostname = self.config.get('local_hostname')
            local_signers = self.config.get('local_signers')

            if hostname != local_hostname:
                raise WildlandError(
                    'Unrecognized file URL hostname: {} (expected {})'.format(
                        url, local_hostname))

            if signer not in local_signers:
                raise WildlandError(
                    'Trying to load file URL for invalid signer: {} (expected {})'.format(
                        signer, local_signers))

            try:
                return Path(parse_result.path).read_bytes()
            except IOError as e:
                raise WildlandError('Error retrieving file URL: {}: {}'.format(
                    url, e))
        raise WildlandError(f'Unrecognized URL: {url}')

    @staticmethod
    def _is_url(url: str):
        return '://' in url

    def local_url(self, path: Path) -> str:
        '''
        Convert an absolute path to a local URL.
        '''

        assert path.is_absolute
        return 'file://' + self.config.get('local_hostname') + quote(str(path))
