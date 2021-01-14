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

import glob
import logging
import os
from pathlib import Path, PurePosixPath
from typing import Optional, Iterator, List, Tuple, Union, Dict, Iterable
from urllib.parse import urlparse, quote

import yaml
import requests

from .user import User
from .container import Container
from .storage import Storage
from .bridge import Bridge
from .wlpath import WildlandPath
from .manifest.sig import DummySigContext, SignifySigContext
from .manifest.manifest import ManifestError, Manifest
from .session import Session
from .storage_backends.base import StorageBackend
from .fs_client import WildlandFSClient
from .config import Config
from .exc import WildlandError

logger = logging.getLogger('client')


WILDLAND_URL_PREFIX = 'wildland:'  # XXX or 'wildland://'?
HTTP_TIMEOUT_SECONDS = 5


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

        self.user_dir = Path(self.config.get('user-dir'))
        self.container_dir = Path(self.config.get('container-dir'))
        self.storage_dir = Path(self.config.get('storage-dir'))
        self.bridge_dir = Path(self.config.get('bridge-dir'))
        self.template_dir = Path(self.config.get('template-dir'))

        mount_dir = Path(self.config.get('mount-dir'))
        socket_path = Path(self.config.get('socket-path'))
        self.fs_client = WildlandFSClient(mount_dir, socket_path)

        try:
            fuse_status = self.fs_client.run_control_command('status')
            default_user = fuse_status.get('default-user', None)
            if default_user:
                self.config.override(override_fields={'@default': default_user})
        except (ConnectionRefusedError, FileNotFoundError):
            pass

        if sig is None:
            if self.config.get('dummy'):
                sig = DummySigContext()
            else:
                key_dir = Path(self.config.get('key-dir'))
                sig = SignifySigContext(key_dir)

        self.session: Session = Session(sig)

        self.users: List[User] = []

        self._select_reference_storage_cache = {}

    def sub_client_with_key(self, pubkey: str) -> Tuple['Client', str]:
        '''
        Create a copy of the current Client, with a public key imported.
        Returns a tuple (client, owner).
        '''

        sig = self.session.sig.copy()
        owner = sig.add_pubkey(pubkey)
        return Client(config=self.config, sig=sig), owner

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

        sig = self.session.sig.copy()
        sig.recognize_local_keys()
        sub_client = Client(config=self.config, sig=sig)

        if self.user_dir.exists():
            for path in sorted(self.user_dir.glob('*.yaml')):
                try:
                    user = sub_client.load_user_from_path(path)
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

    def load_user_from_url(self, url: str, owner: str, allow_self_signed=False) -> User:
        '''
        Load user from an URL
        '''

        data = self.read_from_url(url, owner)

        if allow_self_signed:
            Manifest.load_pubkeys(data, self.session.sig)

        return self.session.load_user(data)

    def load_user_by_name(self, name: str) -> User:
        '''
        Load a user based on a (potentially ambiguous) name.
        '''

        # Default user
        if name == '@default':
            try:
                fuse_status = self.fs_client.run_control_command('status')
            except (ConnectionRefusedError, FileNotFoundError):
                fuse_status = {}
            default_user = fuse_status.get('default-user', None)
            if not default_user:
                default_user = self.config.get('@default')
            if default_user is None:
                raise WildlandError('user not specified and @default not set')
            return self.load_user_by_name(default_user)

        if name == '@default-owner':
            default_owner = self.config.get('@default-owner')
            if default_owner is None:
                raise WildlandError('user not specified and @default-owner not set')
            return self.load_user_by_name(default_owner)

        # Short name
        if not name.endswith('.yaml'):
            path = self.user_dir / f'{name}.yaml'
            if path.exists():
                return self.load_user_from_path(path)

            path = self.user_dir / f'{name}.user.yaml'
            if path.exists():
                return self.load_user_from_path(path)

        # Key
        if name.startswith('0x'):
            for user in self.load_users():
                if user.owner == name:
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

        trusted_owner = self.fs_client.find_trusted_owner(path)
        return self.session.load_container(
            path.read_bytes(), path,
            trusted_owner=trusted_owner)

    def load_container_from_wlpath(self, wlpath: WildlandPath) -> Iterable[Container]:
        '''
        Load containers referring to a given WildlandPath.
        '''

        # TODO: Still a circular dependency with search
        # pylint: disable=import-outside-toplevel, cyclic-import
        from .search import Search
        search = Search(self, wlpath, self.config.aliases)
        yield from search.read_container()

    def load_container_from_url(self, url: str, owner: str) -> Container:
        '''
        Load container from URL.
        '''

        if url.startswith(WILDLAND_URL_PREFIX):
            wlpath = WildlandPath.from_str(url[len(WILDLAND_URL_PREFIX):])
            if wlpath.file_path is None:
                # TODO: Still a circular dependency with search
                # pylint: disable=import-outside-toplevel, cyclic-import
                from .search import Search

                search = Search(self, wlpath, {'default': owner})
                return next(search.read_container())

        return self.session.load_container(self.read_from_url(url, owner))

    def load_container_from_dict(self, dict_: dict, owner: str) -> Container:
        '''
        Load container from a dictionary. Used when a container manifest is inlined
        in another manifest.
        '''

        content = ('---\n' + yaml.dump(dict_)).encode()
        trusted_owner = owner
        return self.session.load_container(content, trusted_owner=trusted_owner)

    def load_containers_from(self, name: str) -> Iterator[Container]:
        '''
        Load a list of containers. Currently supports glob patterns (*) and
        tilde (~), but only in case of local files.
        '''

        if '*' not in name and '~' not in name:
            yield self.load_container_from(name)
            return

        assert not WildlandPath.match(name), \
            'glob patterns in WildlandPath are not supported'

        paths = sorted(glob.glob(os.path.expanduser(name)))
        logger.debug('expanded %r to %s', name, paths)
        if not paths:
            raise ManifestError(f'No container found matching pattern: {name}')
        for path in paths:
            yield self.load_container_from_path(Path(path))

    def resolve_container_name_to_path(self, name: str) -> Optional[Path]:
        """
        Resolve a (non-Wildland Path) container name/path to Path.
        """
        # Short name
        if not name.endswith('.yaml'):
            path = self.container_dir / f'{name}.yaml'
            if path.exists():
                return path

            path = self.container_dir / f'{name}.container.yaml'
            if path.exists():
                return path

        # Local path
        path = Path(name)
        if path.exists():
            return path

        return None

    def load_container_from(self, name: str) -> Container:
        '''
        Load a container based on a (potentially ambiguous) name.
        '''

        # Wildland path
        if WildlandPath.match(name):
            wlpath = WildlandPath.from_str(name)
            # TODO: what to do if there are more containers that match the path?
            return next(self.load_container_from_wlpath(wlpath))

        path = self.resolve_container_name_to_path(name)
        if path:
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

        trusted_owner = self.fs_client.find_trusted_owner(path)
        return self.session.load_storage(
            path.read_bytes(), path,
            trusted_owner=trusted_owner)

    def load_storage_from_url(self, url: str, owner: str) -> Storage:
        '''
        Load storage from URL.
        '''

        return self.session.load_storage(self.read_from_url(url, owner))

    def load_storage_from_dict(self, dict_: dict, owner: str) -> Storage:
        '''
        Load storage from a dictionary. Used when a storage manifest is inlined
        in another manifest.
        '''

        content = ('---\n' + yaml.dump(dict_)).encode()
        trusted_owner = owner
        return self.session.load_storage(content, trusted_owner=trusted_owner)

    def resolve_storage_name_to_path(self, name: str) -> Optional[Path]:
        """
        Resolve a storage name (potentially ambiguous) into a Path.
        """
        # Short name
        if not name.endswith('.yaml'):
            path = self.storage_dir / f'{name}.yaml'
            if path.exists():
                return path

            path = self.storage_dir / f'{name}.storage.yaml'
            if path.exists():
                return path

        # Local path
        path = Path(name)
        if path.exists():
            return path

        return None

    def load_storage_from(self, name: str) -> Storage:
        '''
        Load a storage based on a (potentially ambiguous) name.
        '''
        path = self.resolve_storage_name_to_path(name)
        if path:
            return self.load_storage_from_path(path)

        raise ManifestError(f'Storage not found: {name}')

    def load_bridges(self) -> Iterator[Bridge]:
        '''
        Load bridge manifests from the bridges directory.
        '''

        if self.bridge_dir.exists():
            for path in sorted(self.bridge_dir.glob('*.yaml')):
                try:
                    bridge = self.load_bridge_from_path(path)
                except WildlandError as e:
                    logger.warning('error loading bridge manifest: %s: %s',
                                   path, e)
                else:
                    yield bridge

    def load_bridge_from_path(self, path: Path) -> Bridge:
        '''
        Load a Bridge from a local file.
        '''

        trusted_owner = self.fs_client.find_trusted_owner(path)
        return self.session.load_bridge(
            path.read_bytes(), path,
            trusted_owner=trusted_owner)

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

        path = self._new_path('user', name or user.owner)
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
        path = self._new_path('container', name or ident)
        path.write_bytes(self.session.dump_container(container))
        container.local_path = path
        return path

    def save_new_storage(self, storage: Storage, name: Optional[str] = None) -> Path:
        '''
        Save a new storage in the storage directory. Use the name as a hint for file
        name.
        '''

        path = self._new_path('storage', name or storage.container_path.name)
        path.write_bytes(self.session.dump_storage(storage))
        storage.local_path = path
        return path

    def save_new_bridge(self, bridge: Bridge,
                        name: Optional[str], path: Optional[Path]) -> Path:
        '''
        Save a new bridge.
        '''

        if not path:
            assert name is not None
            path = self._new_path('bridge', name)

        path.write_bytes(self.session.dump_bridge(bridge))
        bridge.local_path = path
        return path

    def _new_path(self, manifest_type, name: str) -> Path:
        if manifest_type == 'user':
            base_dir = self.user_dir
        elif manifest_type == 'container':
            base_dir = self.container_dir
        elif manifest_type == 'storage':
            base_dir = self.storage_dir
        elif manifest_type == 'bridge':
            base_dir = self.bridge_dir
        elif manifest_type == 'set':
            base_dir = self.template_dir
        else:
            assert False, manifest_type

        if not base_dir.exists():
            base_dir.mkdir(parents=True)

        i = 0
        while True:
            suffix = '' if i == 0 else f'.{i}'
            path = base_dir / f'{name}{suffix}.{manifest_type}.yaml'
            if not path.exists():
                return path
            i += 1

    def all_storages(self, container: Container, backends=None, *,
            predicate=None) -> Iterator[Storage]:
        """
        Return (and load on returning) all storages for a given container.

        In case of proxy storage, this will also load an reference storage and
        inline the manifest.
        """
        if backends is None:
            backends = container.backends

        for url_or_dict in backends:
            if isinstance(url_or_dict, str):
                name = url_or_dict
                try:
                    storage = self.load_storage_from_url(url_or_dict, container.owner)
                except FileNotFoundError as e:
                    logging.warning('Error loading manifest: %s', e)
                    continue
                except WildlandError:
                    logging.exception('Error loading manifest: %s', url_or_dict)
                    continue
            else:
                name = '(inline)'
                try:
                    storage = self.load_storage_from_dict(url_or_dict, container.owner)
                except WildlandError:
                    logging.exception('Error loading inline manifest')
                    continue

            if storage.owner != container.owner:
                logger.error(
                    '%s: owner field mismatch: storage %s, container %s',
                    name,
                    storage.owner,
                    container.owner
                )
                continue

            if storage.container_path not in container.expanded_paths:
                logger.error(
                    '%s: unrecognized container path for storage: %s, %s',
                    name,
                    storage.container_path,
                    container.expanded_paths
                )
                continue

            if not StorageBackend.is_type_supported(storage.storage_type):
                logging.warning('Unsupported storage manifest: %s (type %s)',
                                name, storage.storage_type)
                continue

            # If there is a 'container' parameter with a backend URL, convert
            # it to an inline manifest.
            if 'reference-container' in storage.params:
                storage.params['storage'] = self._select_reference_storage(
                    storage.params['reference-container'], container.owner, storage.trusted
                )
                if storage.params['storage'] is None:
                    continue

            if predicate is not None and not predicate(storage):
                continue

            yield storage

    def select_storage(self, container: Container, backends=None, *,
            predicate=None) -> Storage:
        '''
        Select and load a storage to mount for a container.

        In case of proxy storage, this will also load an reference storage and
        inline the manifest.
        '''

        try:
            return next(
                self.all_storages(container, backends, predicate=predicate))
        except StopIteration as ex:
            raise ManifestError('no supported storage manifest') from ex

    def _select_reference_storage(
            self,
            container_url_or_dict: Union[str, Dict],
            owner: str,
            trusted: bool) -> Optional[Dict]:
        '''
        Select an "reference" storage based on URL or dictionary. This resolves a
        container specification and then selects storage for the container.
        '''

        # use custom caching that dumps *container_url_or_dict* to yaml,
        # because dict is not hashable (and there is no frozendict in python)
        cache_key = yaml.dump(container_url_or_dict), owner, trusted
        if cache_key in self._select_reference_storage_cache:
            return self._select_reference_storage_cache[cache_key]

        if isinstance(container_url_or_dict, str):
            container = self.load_container_from_url(
                container_url_or_dict, owner
            )

        else:
            container = self.load_container_from_dict(
                container_url_or_dict, owner
            )

        if trusted and container.owner != owner:
            logger.error(
                'owner field mismatch for trusted reference container: outer %s, inner %s',
                owner, container.owner)
            self._select_reference_storage_cache[cache_key] = None
            return None

        reference_storage = self.select_storage(container)
        reference_manifest = reference_storage.to_unsigned_manifest()
        reference_manifest.skip_signing()
        self._select_reference_storage_cache[cache_key] = reference_manifest.fields
        return reference_manifest.fields

    @staticmethod
    def _postprocess_subcontainer(container: Container,
                                  backend: StorageBackend,
                                  subcontainer_params: dict) -> Container:
        """
        Fill remaining fields of the subcontainer and possibly apply transformations.

        :param container: parent container
        :param backend: storage backend generating this subcontainer
        :param subcontainer_params: subcontainer manifest dict
        :return:
        """  # pylint: disable=unused-argument
        subcontainer_params['object'] = 'container'
        subcontainer_params['owner'] = container.owner
        for sub_storage in subcontainer_params['backends']['storage']:
            sub_storage['object'] = 'storage'
            sub_storage['owner'] = container.owner
            sub_storage['container-path'] = subcontainer_params['paths'][0]
            if isinstance(sub_storage.get('reference-container'), str) and \
                    sub_storage['reference-container'].startswith(
                        WILDLAND_URL_PREFIX):
                sub_storage['reference-container'] = \
                    sub_storage['reference-container'].replace(
                        ':@parent-container:', f':{container.paths[0]}:')
        manifest = Manifest.from_fields(subcontainer_params)
        manifest.skip_signing()
        return Container.from_manifest(manifest)

    def all_subcontainers(self, container: Container) -> Iterator[Container]:
        """
        List subcontainers of this container.

        This takes only the first backend that is capable of sub-containers functionality.
        :param container:
        :return:
        """
        container.ensure_uuid()

        for storage in self.all_storages(container):
            try:
                with StorageBackend.from_params(storage.params, deduplicate=True) as backend:
                    for subcontainer in backend.list_subcontainers():
                        yield self._postprocess_subcontainer(container, backend, subcontainer)
            except NotImplementedError:
                continue
            else:
                return

    @staticmethod
    def is_url(s: str):
        '''
        Check if string can be recognized as URL.
        '''

        return '://' in s or s.startswith(WILDLAND_URL_PREFIX)

    def read_from_url(self, url: str, owner: str) -> bytes:
        '''
        Retrieve data from a given URL. The local (file://) URLs
        are recognized based on the 'local_hostname' and 'local_owners'
        settings.
        '''

        if url.startswith(WILDLAND_URL_PREFIX):
            wlpath = WildlandPath.from_str(url[len(WILDLAND_URL_PREFIX):])
            if not wlpath.owner:
                raise WildlandError(
                    'Wildland path in URL context has to have explicit owner')

            # TODO: Still a circular dependency with search
            # pylint: disable=import-outside-toplevel, cyclic-import
            from .search import Search

            search = Search(self, wlpath, {})
            return search.read_file()

        if url.startswith('file:'):
            local_path = self.parse_file_url(url, owner)
            if local_path:
                try:
                    return local_path.read_bytes()
                except IOError as e:
                    raise WildlandError('Error retrieving file URL: {}: {}'.format(
                        url, e)) from e
            raise FileNotFoundError(2, 'File URL not found', url)

        if url.startswith('http:') or url.startswith('https:'):
            try:
                resp = requests.get(url)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                raise WildlandError('Error retrieving HTTP/HTTPS URL: {}: {}'.format(
                    url, e)) from e

        raise WildlandError(f'Unrecognized URL: {url}')

    def local_url(self, path: Path) -> str:
        '''
        Convert an absolute path to a local URL.
        '''

        assert path.is_absolute
        return 'file://' + self.config.get('local-hostname') + quote(str(path))

    def parse_file_url(self, url: str, owner: str) -> Optional[Path]:
        '''
        Retrieve path from a given file URL, if it's applicable.
        Checks the 'local_hostname' and 'local_owners' settings.
        '''
        parse_result = urlparse(url)
        if parse_result.scheme != 'file':
            return None

        hostname = parse_result.netloc or 'localhost'
        local_hostname = self.config.get('local-hostname')
        local_owners = self.config.get('local-owners')

        if hostname != local_hostname:
            logger.warning(
                'Unrecognized file URL hostname: %s (expected %s)',
                url, local_hostname)
            return None

        if owner not in local_owners:
            logger.warning(
                'Trying to load file URL for invalid owner: %s (expected %s)',
                owner, local_owners)
            return None

        return Path(parse_result.path)

    @staticmethod
    def _select_storage_for_publishing(storage):
        return storage.manifest_pattern is not None

    @staticmethod
    def _manifest_filenames_from_patern(container: Container, path_pattern):
        path_pattern = path_pattern.replace('*', container.ensure_uuid())
        if '{path}' in path_pattern:
            for path in container.paths:
                yield PurePosixPath(path_pattern.replace(
                    '{path}', str(path.relative_to('/')))).relative_to('/')
        else:
            yield PurePosixPath(path_pattern).relative_to('/')

    def publish_container(self, container: Container,
            wlpath: Optional[WildlandPath] = None) -> None:
        '''
        Publish a container to another container owner by the same user
        '''

        # pylint: disable=import-outside-toplevel, cyclic-import
        from .search import Search, StorageDriver

        data = self.session.dump_container(container)

        if wlpath is not None:
            search = Search(self, wlpath, self.config.aliases)
            search.write_file(data)
            return

        owner = self.load_user_by_name(container.owner)
        containers = owner.containers
        for cont in containers:
            cont = (self.load_container_from_url(cont, container.owner)
                if isinstance(cont, str)
                else self.load_container_from_dict(cont, container.owner))

            if cont.paths == container.paths:
                # do not publish container to itself
                continue

            try:
                storage = self.select_storage(cont,
                    predicate=self._select_storage_for_publishing)
                break
            except ManifestError:
                continue

        else: # didn't break, i.e. storage not found
            raise WildlandError(
                'cannot find any container suitable as publishing platform')

        assert storage.manifest_pattern['type'] == 'glob'
        for relpath in self._manifest_filenames_from_patern(container,
                                                            storage.manifest_pattern['path']):
            with StorageDriver.from_storage(storage) as driver:
                driver.makedirs(relpath.parent)
                driver.write_file(relpath, data)
