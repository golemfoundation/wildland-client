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
from typing import Optional, Iterator

from .user import User
from .container import Container
from .storage import Storage
from .wlpath import WildlandPath
from .manifest.sig import SigContext, DummySigContext, GpgSigContext
from .manifest.manifest import ManifestError
from .session import Session
from .storage_backends.base import StorageBackend

from .config import Config
from .exc import WildlandError

logger = logging.getLogger('client')


class Client:
    '''
    A high-level interface for operating on Wildland objects.
    '''

    def __init__(self, base_dir=None, **config_kwargs):
        self.config = Config.load(base_dir)
        self.config.override(**config_kwargs)

        self.user_dir = Path(self.config.get('user_dir'))
        self.container_dir = Path(self.config.get('container_dir'))
        self.storage_dir = Path(self.config.get('storage_dir'))

        sig: SigContext
        if self.config.get('dummy'):
            sig = DummySigContext()
        else:
            sig = GpgSigContext(self.config.get('gpg_home'))

        self.session: Session = Session(sig)

        self.users = []
        self.closed = False

    def close(self):
        '''
        Clean up.
        '''
        self.session.sig.close()
        self.closed = True

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

        return self.session.load_container(path.read_bytes(), path)

    def load_container_from_wlpath(self, wlpath: WildlandPath) -> Container:
        '''
        Load a container from WildlandPath.
        '''

        # TODO: Still a circular dependency with resolve.py
        # pylint: disable=import-outside-toplevel, cyclic-import
        from .resolve import Search
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

        return self.session.load_storage(path.read_bytes(), path)

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

        # TODO: currently just file URLs
        for url in container.backends:
            try:
                storage = self.load_storage_from_path(Path(url))
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
