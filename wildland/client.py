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

# pylint: disable=too-many-lines

"""
Client class
"""

import collections.abc
import functools
import glob
import logging
import os
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, Iterator, Optional, Tuple, Union
from urllib.parse import urlparse, quote

import yaml
import requests

from .user import User
from .container import Container
from .storage import Storage
from .bridge import Bridge
from .wlpath import WildlandPath, PathError
from .manifest.sig import DummySigContext, SodiumSigContext
from .manifest.manifest import ManifestError, Manifest
from .session import Session
from .storage_backends.base import StorageBackend, verify_local_access
from .fs_client import WildlandFSClient
from .config import Config
from .exc import WildlandError
from .search import Search

logger = logging.getLogger('client')


HTTP_TIMEOUT_SECONDS = 5


class Client:
    """
    A high-level interface for operating on Wildland objects.
    """

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

        dirs = [self.user_dir, self.container_dir, self.storage_dir,
                self.bridge_dir, self.template_dir]
        for d in dirs:
            d.mkdir(exist_ok=True, parents=True)

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

        #: save (import) users encountered while traversing WL paths
        self.auto_import_users = False

        key_dir = Path(self.config.get('key-dir'))

        if sig is None:
            if self.config.get('dummy'):
                sig = DummySigContext(key_dir)
            else:
                sig = SodiumSigContext(key_dir)

        self.session: Session = Session(sig)

        self.users: Dict[str, User] = {}

        self._select_reference_storage_cache = {}

    def sub_client_with_key(self, pubkey: str) -> Tuple['Client', str]:
        """
        Create a copy of the current Client, with a public key imported.
        Returns a tuple (client, owner).
        """

        sig = self.session.sig.copy()
        owner = sig.add_pubkey(pubkey)
        return Client(config=self.config, sig=sig), owner

    def recognize_users(self, users: Optional[Iterable[User]] = None):
        """
        Load and recognize users from the users directory or a given iterable.
        """

        if users is None:
            users = self.load_users()

        for user in users:
            self.users[user.owner] = user
            self.session.recognize_user(user)

    @staticmethod
    def find_local_manifest(base_dir: Path, suffix: Optional[str], name: str) -> Optional[Path]:
        """
        Find local manifest based on a (potentially ambiguous) name.
        """

        # Short name
        if not name.endswith('.yaml'):
            path = base_dir / f'{name}.yaml'
            if path.exists():
                return path

            if suffix is not None:
                path = base_dir / f'{name}.{suffix}.yaml'
                if path.exists():
                    return path

        # Local path
        path = Path(name)
        if path.exists():
            return path

        return None

    def load_users(self) -> Iterator[User]:
        """
        Load users from the users directory.
        """

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
        """
        Load user from a local file.
        """

        return self.session.load_user(path.read_bytes(), path)

    def load_user_from_url(self, url: str, owner: str, allow_self_signed=False) -> User:
        """
        Load user from an URL
        """

        data = self.read_from_url(url, owner)

        if allow_self_signed:
            Manifest.load_pubkeys(data, self.session.sig)

        return self.session.load_user(data)

    def find_user_manifest(self, name: str) -> Optional[Path]:
        """
        Find user's manifest based on a (potentially ambiguous) name.
        """

        # Aliases
        if name == '@default':
            try:
                fuse_status = self.fs_client.run_control_command('status')
            except (ConnectionRefusedError, FileNotFoundError):
                fuse_status = {}
            name = fuse_status.get('default-user', None)
            if not name:
                name = self.config.get('@default')
            if not name:
                raise WildlandError('user not specified and @default not set')

        if name == '@default-owner':
            name = self.config.get('@default-owner')
            if name is None:
                raise WildlandError('user not specified and @default-owner not set')

        # Already loaded
        if name in self.users:
            return self.users[name].local_path

        # Key
        if name.startswith('0x'):
            for user in self.load_users():
                if user.owner == name:
                    return user.local_path

        # Local path
        return self.find_local_manifest(self.user_dir, 'user', name)

    def load_user_by_name(self, name: str) -> User:
        """
        Load a user based on a (potentially ambiguous) name.
        """
        if name in self.users:
            return self.users[name]
        path = self.find_user_manifest(name)
        if path:
            return self.load_user_from_path(path)

        raise WildlandError(f'User not found: {name}')

    def recognize_users_from_search(self, final_step):
        """
        Recognize users and bridges encountered while traversing WL path.
        If self.auto_import_users is set, bridge and user manifests are
        saved into ~/.config/wildland as is - without changing bridge owner or its paths
        (contrary to wl user import command).

        :param final_step: final step returned by Search.resolve_raw()
        :return:
        """

        # save users and bridges if requested
        if self.auto_import_users:
            for step in final_step.steps_chain():
                if not step.bridge or step.user.owner in self.users:
                    # not a user transition, or user already known
                    continue
                user = step.user
                logger.info('importing user %s', user.owner)
                # save the original manifest, don't risk the need to re-sign
                path = self.new_path('user', user.owner)
                path.write_bytes(user.manifest.to_bytes())
                path = self.new_path('bridge', user.owner)
                path.write_bytes(step.bridge.manifest.to_bytes())

        # load encountered users to the current context - may be needed for subcontainers
        self.recognize_users(
            [ustep.user for ustep in final_step.steps_chain()
             if ustep.user is not None])

    def load_containers(self) -> Iterator[Container]:
        """
        Load containers from the containers directory.
        """

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
        """
        Load container from a local file.
        """

        trusted_owner = self.fs_client.find_trusted_owner(path)
        return self.session.load_container(
            path.read_bytes(), path,
            trusted_owner=trusted_owner)

    def load_container_from_wlpath(self, wlpath: WildlandPath,
            aliases: Optional[dict] = None) -> Iterator[Container]:
        """
        Load containers referring to a given WildlandPath.
        """
        if aliases is None:
            aliases = self.config.aliases
        search = Search(self, wlpath, aliases)
        for final_step in search.resolve_raw():
            if final_step.container is None:
                continue
            self.recognize_users_from_search(final_step)

            yield final_step.container

    def load_container_from_url(self, url: str, owner: str) -> Container:
        """
        Load container from URL.
        """

        if WildlandPath.match(url):
            wlpath = WildlandPath.from_str(url)
            if wlpath.file_path is None:
                try:
                    return next(self.load_container_from_wlpath(wlpath, {'default': owner}))
                except StopIteration as ex:
                    raise PathError(f'Container not found for path: {wlpath}') from ex

        return self.session.load_container(self.read_from_url(url, owner))

    def load_container_from_dict(self, dict_: dict, owner: str) -> Container:
        """
        Load container from a dictionary. Used when a container manifest is inlined
        in another manifest.
        """

        # fill in fields that are determined by the context
        if 'owner' not in dict_:
            dict_['owner'] = owner

        content = ('---\n' + yaml.dump(dict_)).encode()
        trusted_owner = owner
        return self.session.load_container(content, trusted_owner=trusted_owner)

    # pylint: disable=inconsistent-return-statements
    def load_container_from_url_or_dict(self,
            obj: Union[str, dict], owner: str):
        """
        Load container, suitable for loading directly from manifest.
        """
        if isinstance(obj, str):
            return self.load_container_from_url(obj, owner)
        if isinstance(obj, collections.abc.Mapping):
            return self.load_container_from_dict(obj, owner)
        assert False

    def load_containers_from(self, name: str) -> Iterator[Container]:
        """
        Load a list of containers. Currently supports glob patterns (*) and
        tilde (~), but only in case of local files.
        """

        if WildlandPath.match(name):
            wlpath = WildlandPath.from_str(name)
            try:
                yield from self.load_container_from_wlpath(wlpath)
            except WildlandError as ex:
                raise ManifestError(f'Failed to load container {name}: {ex}') from ex
            return

        path = self.find_local_manifest(self.container_dir, 'container', name)
        if path:
            yield self.load_container_from_path(path)
            return

        paths = sorted(glob.glob(os.path.expanduser(name)))
        logger.debug('expanded %r to %s', name, paths)
        if not paths:
            raise ManifestError(f'No container found matching pattern: {name}')

        failed = False
        exc_msg = 'Failed to load some container manifests:\n'
        for p in paths:
            try:
                yield self.load_container_from_path(Path(p))
            except WildlandError as ex:
                failed = True
                exc_msg += str(ex) + '\n'
                continue

        if failed:
            raise ManifestError(exc_msg)

    def load_container_from(self, name: str) -> Container:
        """
        Load a container based on a (potentially ambiguous) name.
        """

        # Wildland path
        if WildlandPath.match(name):
            wlpath = WildlandPath.from_str(name)

            # TODO: what to do if there are more containers that match the path?
            try:
                return next(self.load_container_from_wlpath(wlpath))
            except StopIteration as ex:
                raise PathError(f'Container not found for path: {wlpath}') from ex

        path = self.find_local_manifest(self.container_dir, 'container', name)
        if path:
            return self.load_container_from_path(path)

        raise ManifestError(f'Container not found: {name}')

    def load_storages(self) -> Iterator[Storage]:
        """
        Load storages from the storage directory.
        """

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
        """
        Load storage from a local file.
        """

        trusted_owner = self.fs_client.find_trusted_owner(path)
        return self.session.load_storage(
            path.read_bytes(), path,
            trusted_owner=trusted_owner,
            local_owners=self.config.get('local-owners'))

    def load_storage_from_url(self, url: str, owner: str) -> Storage:
        """
        Load storage from URL.
        """

        return self.session.load_storage(self.read_from_url(url, owner),
                                         local_owners=self.config.get('local-owners'))

    def load_storage_from_dict(self, dict_: dict, owner: str,
            container_path: Union[str, PurePosixPath]) -> Storage:
        """
        Load storage from a dictionary. Used when a storage manifest is inlined
        in another manifest.
        """

        if list(dict_.keys()) == ['encrypted']:
            raise ManifestError('This inline storage cannot be decrypted')

        # fill in fields that are determined by the context
        if 'owner' not in dict_:
            dict_['owner'] = str(owner)
        if 'container-path' not in dict_:
            dict_['container-path'] = str(container_path)
        if 'object' not in dict_:
            dict_['object'] = 'storage'

        content = ('---\n' + yaml.dump(dict_)).encode()
        trusted_owner = owner
        return self.session.load_storage(content,
                                         trusted_owner=trusted_owner,
                                         local_owners=self.config.get('local-owners'))

    def load_storage_from(self, name: str) -> Storage:
        """
        Load a storage based on a (potentially ambiguous) name.
        """
        path = self.find_local_manifest(self.storage_dir, 'storage', name)
        if path:
            return self.load_storage_from_path(path)

        raise ManifestError(f'Storage not found: {name}')

    def load_storage_from_url_or_dict(self,
            obj: Union[str, dict], owner: str, container_path: str) -> Storage:
        '''
        Load storage, suitable for loading directly from manifest.
        '''
        if isinstance(obj, str):
            return self.load_storage_from_url(obj, owner)
        if isinstance(obj, collections.abc.Mapping):
            return self.load_storage_from_dict(obj, owner, container_path)
        assert False

    def load_bridges(self) -> Iterator[Bridge]:
        """
        Load bridge manifests from the bridges directory.
        """

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
        """
        Load a Bridge from a local file.
        """

        trusted_owner = self.fs_client.find_trusted_owner(path)
        return self.session.load_bridge(
            path.read_bytes(), path,
            trusted_owner=trusted_owner)

    @functools.lru_cache
    def get_bridge_paths_for_user(self, user: Union[User, str], owner: Optional[User] = None) \
            -> Iterable[PurePosixPath]:
        """
        Get bridge paths to the *user* using bridges owned by *owner*. If owner is not specified,
        use default user (``@default``).

        :param user: user to look paths for (user id is accepted too)
        :param owner: owner of bridges to consider
        :return: list of paths collected from bridges
        """
        if owner is None:
            try:
                owner = self.load_user_by_name('@default')
            except WildlandError:
                # if default cannot be loaded, just behave as no bridges were found
                return []

        if isinstance(user, str):
            user = self.load_user_by_name(user)

        if owner.primary_pubkey == user.primary_pubkey:
            return [PurePosixPath('/')]

        paths = []
        for bridge in self.load_bridges():
            if bridge.owner != owner.owner:
                continue
            if bridge.user_pubkey != user.primary_pubkey:
                continue
            paths.extend(bridge.paths)

        return set(paths)

    def save_user(self, user: User, path: Optional[Path] = None) -> Path:
        """
        Save a user manifest. If path is None, the user has to have
        local_path set.
        """

        path = path or user.local_path
        assert path is not None
        path.write_bytes(self.session.dump_user(user))
        user.local_path = path
        return path

    def save_new_user(self, user: User, name: Optional[str] = None) -> Path:
        """
        Save a new user in the user directory. Use the name as a hint for file
        name.
        """

        path = self.new_path('user', name or user.owner)
        path.write_bytes(self.session.dump_user(user))
        user.local_path = path
        return path

    def save_container(self, container: Container, path: Optional[Path] = None) -> Path:
        """
        Save a container manifest. If path is None, the container has to have
        local_path set.
        """

        path = path or container.local_path
        assert path is not None
        path.write_bytes(self.session.dump_object(container))
        return path

    def save_new_container(self, container: Container, name: Optional[str] = None) -> Path:
        """
        Save a new container in the container directory. Use the name as a hint for file
        name.
        """

        ident = container.ensure_uuid()
        path = self.new_path('container', name or ident)
        path.write_bytes(self.session.dump_object(container))
        container.local_path = path
        return path

    def save_new_storage(self, storage: Storage, name: Optional[str] = None) -> Path:
        """
        Save a new storage in the storage directory. Use the name as a hint for file
        name.
        """

        path = self.new_path('storage', name or storage.container_path.name)
        path.write_bytes(self.session.dump_object(storage))
        storage.local_path = path
        return path

    def save_new_bridge(self, bridge: Bridge,
                        name: Optional[str], path: Optional[Path]) -> Path:
        """
        Save a new bridge.
        """

        if not path:
            assert name is not None
            path = self.new_path('bridge', name)

        path.write_bytes(self.session.dump_object(bridge))
        bridge.local_path = path
        # cache_clear is added by a decorator, which pylint doesn't see
        # pylint: disable=no-member
        self.get_bridge_paths_for_user.cache_clear()
        return path

    def new_path(self, manifest_type, name: str, skip_numeric_suffix: bool = False) -> Path:
        """
        Create a path in Wildland base_dir to save a new object of type manifest_type and name
        name. It follows Wildland conventions.
        :param manifest_type: 'user', 'container', 'storage', 'bridge' or 'set'
        :param name: name of the object
        :return: Path
        """
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
            if skip_numeric_suffix or not path.exists():
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

                # Checking storage owner and path is neccessary only in external
                # storage files but not in inline ones.

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
            else:
                name = '(inline)'
                try:
                    storage = self.load_storage_from_dict(
                        url_or_dict, container.owner, container.paths[0])
                except WildlandError as e:
                    logging.info('Container %s: error loading inline manifest: %s', container, e)
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
        """
        Select and load a storage to mount for a container.

        In case of proxy storage, this will also load an reference storage and
        inline the manifest.
        """

        try:
            return next(
                self.all_storages(container, backends, predicate=predicate))
        except StopIteration as ex:
            raise ManifestError('no supported storage manifest') from ex

    def get_storages_to_mount(self, container: Container) -> Iterable[Storage]:
        """
        Return valid, mountable storages for the given container
        """
        storages = list(self.all_storages(container, predicate=None))

        if not storages:
            raise WildlandError('No valid storages found')

        primaries = list(filter(lambda s: s.is_primary, storages))

        if len(primaries) > 1:
            raise WildlandError('There cannot be more than 1 primary storage defined. '
                                'Verify the container manifest.')

        if len(primaries) == 0:
            # If no primaries were defined in the manifest, mark the first storage from the list as
            # primary. There must be at least one storage designated as the primary storage.
            storages[0].promote_to_primary()
        else:
            # Make sure the primary storage is first
            storages = sorted(storages, key=lambda s: s.is_primary)

        return storages

    def _select_reference_storage(
            self,
            container_url_or_dict: Union[str, Dict],
            owner: str,
            trusted: bool) -> Optional[Dict]:
        """
        Select a "reference" storage based on URL or dictionary. This resolves a
        container specification and then selects storage for the container.
        """

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
        self._select_reference_storage_cache[cache_key] = reference_storage.params
        return reference_storage.params

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
        subcontainer_params['version'] = Manifest.CURRENT_VERSION
        for sub_storage in subcontainer_params['backends']['storage']:
            sub_storage['object'] = 'storage'
            sub_storage['owner'] = container.owner
            subcontainer_params['version'] = Manifest.CURRENT_VERSION
            sub_storage['container-path'] = subcontainer_params['paths'][0]
            if isinstance(sub_storage.get('reference-container'), str) and \
                    WildlandPath.match(sub_storage['reference-container']):
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
                    for subcontainer in backend.list_subcontainers(
                        sig_context=self.session.sig,
                    ):
                        yield self._postprocess_subcontainer(container, backend, subcontainer)
            except NotImplementedError:
                continue
            else:
                return

    @staticmethod
    def is_url(s: str):
        """
        Check if string can be recognized as URL.
        """

        return '://' in s or WildlandPath.match(s)

    @staticmethod
    def is_local_storage(storage: Union[StorageBackend, Storage, str]):
        """
        Check if the given storage is local. Currently checks for TYPE matching local, local-cached
        or local-dir-cached.
        """

        if isinstance(storage, StorageBackend):
            storage = storage.TYPE
        elif isinstance(storage, Storage):
            storage = storage.params['type']

        return storage in ['local', 'local-cached', 'local-dir-cached']

    def _wl_url_to_search(self, url: str, use_aliases: bool = False):
        wlpath = WildlandPath.from_str(url)
        if not wlpath.owner and not use_aliases:
            raise WildlandError(
                'Wildland path in URL context has to have explicit owner')

        search = Search(self, wlpath,
                        self.config.aliases if use_aliases else {})

        return search

    def read_bridge_from_url(self, url: str, use_aliases: bool = False) -> Iterable[Bridge]:
        """
        Return an iterator over all bridges encountered on a given Wildland path.
        """
        if not WildlandPath.match(url):
            raise WildlandError('Invalid Wildland path')
        search = self._wl_url_to_search(url, use_aliases=use_aliases)
        yield from search.read_bridge()

    def is_url_file_path(self, url: str):
        """
        Determines if the given URL is an URL to file or to a Wildland bridge.
        :param url: str
        """
        if not self.is_url(url):
            return False
        if WildlandPath.match(url):
            wlpath = WildlandPath.from_str(url)
            return bool(wlpath.file_path)
        return True

    def read_from_url(self, url: str, owner: str, use_aliases: bool = False) -> bytes:
        """
        Retrieve data from a given URL. The local (file://) URLs
        are recognized based on the 'local_hostname' and 'local_owners'
        settings.
        """

        if WildlandPath.match(url):
            search = self._wl_url_to_search(url, use_aliases=use_aliases)
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
        """
        Convert an absolute path to a local URL.
        """

        assert path.is_absolute
        return 'file://' + self.config.get('local-hostname') + quote(str(path))

    def parse_file_url(self, url: str, owner: str) -> Optional[Path]:
        """
        Retrieve path from a given file URL, if it's applicable.
        Checks the 'local_hostname' and 'local_owners' settings.
        """
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

        path = Path(parse_result.path)

        try:
            verify_local_access(path, owner, owner in local_owners)
        except PermissionError as e:
            logger.warning('Cannot load %s: %s', url, e)
            return None

        return path
