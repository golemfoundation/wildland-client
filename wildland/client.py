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
from typing import Dict, Iterable, Iterator, Optional, Tuple, Union, List, Set
from urllib.parse import urlparse, quote

import yaml
import requests

from .user import User
from .container import Container
from .storage import Storage
from .bridge import Bridge
from .wlpath import WildlandPath, PathError
from .manifest.sig import DummySigContext, SodiumSigContext, SigContext
from .manifest.manifest import ManifestError, Manifest, WildlandObjectType
from .session import Session
from .storage_backends.base import StorageBackend, verify_local_access
from .fs_client import WildlandFSClient
from .config import Config
from .exc import WildlandError
from .search import Search
from .storage_driver import StorageDriver

logger = logging.getLogger('client')


HTTP_TIMEOUT_SECONDS = 5


class Client:
    """
    A high-level interface for operating on Wildland objects.
    """

    def __init__(
            self,
            base_dir: PurePosixPath = None,
            sig: SigContext = None,
            config: Config = None,
            load: bool = True,
            **config_kwargs
    ):
        """
        A high-level interface for operating on Wildland objects.

        :param base_dir: base directory (``~/.config/wildland`` by default)
        :param sig: SigContext to use
        :param config: config object
        :param load: Load initial state (users, bridges etc)
        :param config_kwargs: Override select config options
        """
        if config is None:
            config = Config.load(base_dir)
            config.override(**config_kwargs)
        self.config = config

        self.dirs = {
            WildlandObjectType.USER: Path(self.config.get('user-dir')),
            WildlandObjectType.CONTAINER: Path(self.config.get('container-dir')),
            WildlandObjectType.STORAGE: Path(self.config.get('storage-dir')),
            WildlandObjectType.BRIDGE: Path(self.config.get('bridge-dir')),
            WildlandObjectType.TEMPLATE: Path(self.config.get('template-dir'))
        }

        for d in self.dirs.values():
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
        # FIXME: this doesn't really deduplicate bridges, only avoids the same
        # _instance_ being added multiple times
        self.bridges: Set[Bridge] = set()

        self._select_reference_storage_cache: Dict[Tuple[str, str, bool], Optional[Dict]] = {}

        if load:
            self.recognize_users_and_bridges()

    def sub_client_with_key(self, pubkey: str) -> Tuple['Client', str]:
        """
        Create a copy of the current Client, with a public key imported.
        Returns a tuple (client, owner).
        """

        sig = self.session.sig.copy()
        owner = sig.add_pubkey(pubkey)
        return Client(config=self.config, sig=sig, load=False), owner

    def recognize_users_and_bridges(self, users: Optional[Iterable[User]] = None,
                                    bridges: Optional[Iterable[Bridge]] = None):
        """
        Load users and recognize their keys from the users directory or a given iterable.
        This function loads also all (local) bridges, so it's possible to find paths for the users.
        """
        for user in users or self.load_all(WildlandObjectType.USER, decrypt=False):
            user.add_user_keys(self.session.sig)

        # duplicated to decrypt infrastructures correctly
        for user in users or self.load_all(WildlandObjectType.USER):
            self.users[user.owner] = user

        for bridge in bridges or self.load_all(WildlandObjectType.BRIDGE):
            self.bridges.add(bridge)

    def find_local_manifest(self, object_type: Union[WildlandObjectType, None],
                            name: str) -> Optional[Path]:
        """
        Find local manifest based on a (potentially ambiguous) name. Names can be aliases, user
        fingerprints (for users), name of the file, part of the file name, or complete file path.
        """

        if object_type == WildlandObjectType.USER:
            # aliases
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

            if name in self.config.aliases:
                name = self.config.aliases[name]

            if name in self.users:
                return self.users[name].local_path

            if name.startswith('0x'):
                for user in self.load_all(WildlandObjectType.USER):
                    if user.owner == name:
                        return user.local_path

        if object_type:
            directory = self.dirs[object_type]
            path_candidates = [
                directory / f'{name}.yaml',
                directory / f'{name}.{object_type.value}.yaml',
                directory / name]
        else:
            path_candidates = []

        path_candidates.append(Path(name))

        for path_candidate in path_candidates:
            if path_candidate.exists():
                return path_candidate

        return None

    def load_object_from_bytes(self,
                               object_type: Union[WildlandObjectType, None],
                               data: bytes,
                               allow_only_primary_key: Optional[bool] = None,
                               file_path: Optional[Path] = None,
                               expected_owner: Optional[str] = None,
                               trusted_owner: Optional[str] = None,
                               local_owners: Optional[List[str]] = None,
                               decrypt: bool = True):
        """
        Load and return a Wildland object from raw bytes.
        :param data: object bytes
        :param object_type: expected object type; if not provided, will be guessed based on 'object'
        field. If provided, must match data, or a WildlandError will be raised.
        :param allow_only_primary_key: can the object be signed by any of its owner's keys, or just
        by the primary key. If omitted, assumed to be True for USER objects and False for all other.
        :param file_path: path to local manifest file, if exists
        :param trusted_owner: accept signature-less manifests from this owner
        :param local_owners: owners allowed to access local storages
        :param decrypt: should we attempt to decrypt the bytes
        """

        if allow_only_primary_key is None:
            allow_only_primary_key = object_type == WildlandObjectType.USER

        if not object_type:
            manifest = Manifest.from_bytes(data, self.session.sig,
                                           allow_only_primary_key=allow_only_primary_key,
                                           decrypt=decrypt)

            object_type = WildlandObjectType(manifest.fields['object'])

        if object_type in [WildlandObjectType.USER, WildlandObjectType.BRIDGE,
                           WildlandObjectType.STORAGE, WildlandObjectType.CONTAINER]:
            loaded_object = self.session.load_object(data, object_type, local_path=file_path,
                                                     trusted_owner=trusted_owner,
                                                     local_owners=local_owners,
                                                     decrypt=decrypt)

            if expected_owner and expected_owner != loaded_object.owner:
                raise WildlandError('Owner mismatch: expected {}, got {}'.format(
                    expected_owner, loaded_object.owner))

            return loaded_object

        raise WildlandError(f'Unknown manifest type: {object_type.value}')

    def read_link_object(self,
                         storage: dict,
                         file_path: PurePosixPath,
                         expected_owner: Optional[str]) -> bytes:
        """
        Attempt to find file in storage (aka link object) and return its content
        """
        storage_obj = self.load_object_from_dict(WildlandObjectType.STORAGE, storage,
                                                 expected_owner=expected_owner, container_path='/')
        storage_backend = StorageBackend.from_params(storage_obj.params)
        with StorageDriver(storage_backend, storage) as driver:
            return driver.read_file(file_path.relative_to('/'))

    def load_object_from_dict(self,
                              object_type: Union[WildlandObjectType, None],
                              dictionary: dict,
                              expected_owner: Optional[str] = None,
                              container_path: Optional[Union[str, PurePosixPath]] = None):
        """
        Load Wildland object from a dict.
        :param dictionary: dict containing object data
        :param object_type: expected type of object; if None, will use dict 'object' field.
        On mismatch of expected and actual type, a WildlandError will be raised.
        :param expected_owner: expected owner. On mismatch of expected and actual owner,
        a WildlandError will be raised.
        :param container_path: if object is STORAGE, will be passed to it as container_path. Ignored
        otherwise.
        """
        # handle optional encrypted data - this should not happen normally
        encryption_warning = False
        if 'encrypted' in dictionary:
            dictionary = Manifest.decrypt(dictionary, self.session.sig)
            encryption_warning = True
            if 'encrypted' in dictionary:
                raise ManifestError('This inline storage cannot be decrypted')

        if dictionary.get('object', None) == 'link':
            content = self.read_link_object(
                dictionary['storage'], PurePosixPath(dictionary['file']), expected_owner)

            return self.load_object_from_bytes(object_type, content)

        if object_type:
            if 'object' not in dictionary:
                dictionary['object'] = object_type.value
            else:
                if object_type.value != dictionary['object']:
                    raise WildlandError('Object type mismatch: expected {}, got {}'.format(
                        object_type.value, dictionary['object']))
        else:
            object_type = WildlandObjectType(dictionary['object'])

        local_owners = None

        if expected_owner:
            if 'owner' not in dictionary:
                dictionary['owner'] = expected_owner
            elif expected_owner != dictionary['owner']:
                raise WildlandError('Owner mismatch: expected {}, got {}'.format(
                    expected_owner, dictionary['owner']))

        if object_type == WildlandObjectType.STORAGE:
            if 'container-path' not in dictionary and container_path:
                dictionary['container-path'] = str(container_path)

            local_owners = self.config.get('local-owners')

        content = ('---\n' + yaml.dump(dictionary)).encode()

        obj = self.session.load_object(content, object_type, local_owners=local_owners,
                                       trusted_owner=expected_owner)
        if encryption_warning:
            logger.warning('Unexpected encrypted data encountered in %s', repr(obj))

        return obj

    def load_object_from_url(self, object_type: WildlandObjectType, url: str,
                             owner: str, expected_owner: Optional[str] = None):
        """
        Load and return a Wildland object from any URL, including Wildland URLs.
        :param url: URL. must start with protocol (e.g. wildland: or https:
        :param object_type: expected object type. If not provided, will try to guess it based
        on data (although this will not be successful for WL URLs to containers.). If provided
        will raise an exception if expected type is different than received type.
        :param owner: owner in whose context we should resolve the URL
        :param expected_owner: expected owner. Will raise a WildlandError if receives a
        different owner.
        """

        if object_type == WildlandObjectType.CONTAINER and WildlandPath.match(url):
            # special treatment for WL paths: they can refer to a file or to a container
            wlpath = WildlandPath.from_str(url)
            if wlpath.file_path is None:
                containers = self.load_containers_from(wlpath, {'default': owner})
                result = None
                for c in containers:
                    if not result:
                        result = c
                    else:
                        if c.owner != result.owner or c.ensure_uuid() != result.ensure_uuid():
                            raise PathError(f'Expected single container, found multiple: {wlpath}')
                if not result:
                    raise PathError(f'Container not found for path: {wlpath}')
                return result

        content = self.read_from_url(url, owner)

        if object_type == WildlandObjectType.USER:
            Manifest.verify_and_load_pubkeys(content, self.session.sig)

        local_owners = self.config.get('local-owners')

        obj_ = self.load_object_from_bytes(None, content, local_owners=local_owners)
        if expected_owner and obj_.owner != expected_owner:
            raise WildlandError(f'Unexpected owner: expected {expected_owner}, got {obj_.owner}')

        return obj_

    def load_object_from_file_path(self, object_type: WildlandObjectType, path: Path,
                                   decrypt: bool = True):
        """
        Load and return a Wildland object from local file path (not in URL form).
        :param path: local file path
        :param object_type: expected type of object
        :param decrypt: should we attempt to decrypt the object (default: True)
        """
        trusted_owner = self.fs_client.find_trusted_owner(path)
        local_owners = self.config.get('local-owners')

        return self.load_object_from_bytes(object_type, path.read_bytes(), file_path=path,
                                           trusted_owner=trusted_owner, local_owners=local_owners,
                                           decrypt=decrypt)

    def load_object_from_url_or_dict(self, object_type: WildlandObjectType,
                                     obj: Union[str, dict],
                                     owner: str, expected_owner: Optional[str] = None,
                                     container_path: Optional[str] = None):
        """
        A convenience wrapper for loading objects from either URL or dict. Returns a Wildland
        object.
        :param obj: URL or dict to be turned into WL object
        :param object_type: expected object type
        :param owner: owner in whose context we should resolve URLs
        :param expected_owner: expected owner
        :param container_path: if loading a STORAGE object of dict type, this container path
        will be filled in if the dict does not contain it already.
        """

        if isinstance(obj, str):
            return self.load_object_from_url(object_type, obj, owner, expected_owner)

        if isinstance(obj, collections.abc.Mapping):
            return self.load_object_from_dict(object_type, obj, expected_owner=owner,
                                              container_path=container_path)
        raise ValueError(f'{obj} is neither url nor dict')

    def load_object_from_name(self, object_type: WildlandObjectType, name: str):
        """
        Load a Wildland object from ambiguous name. The name can be a local filename, part of local
        filename (will attempt to look for the object in appropriate local directory), a WL URL,
        another kind of URL etc.
        :param object_type: expected object type
        :param name: ambiguous name
        """
        if object_type == WildlandObjectType.USER and name in self.users:
            return self.users[name]

        if self.is_url(name):
            return self.load_object_from_url(object_type, name, self.config.get('@default'))

        path = self.find_local_manifest(object_type, name)
        if path:
            return self.load_object_from_file_path(object_type, path)

        raise WildlandError(f'{object_type.value} not found: {name}')

    def find_storage_usage(self, storage_id: Union[Path, str]) \
            -> List[Tuple[Container, Union[str, dict]]]:
        """Find containers which can use storage given by path or backend-id.

        :param storage_id: storage path or backend_id
        :return: list of tuples (container, storage_url_or_dict)
        """
        used_by = []
        for container in self.load_all(WildlandObjectType.CONTAINER):
            assert container.local_path
            for url_or_dict in container.backends:
                if isinstance(url_or_dict, str):
                    identifier = self.parse_file_url(url_or_dict, container.owner)
                elif "backend-id" in url_or_dict:
                    identifier = url_or_dict["backend-id"]
                else:
                    continue
                if storage_id == identifier:
                    used_by.append((container, url_or_dict))
        return used_by

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
                path = self.new_path(WildlandObjectType.USER, user.owner)
                path.write_bytes(user.manifest.to_bytes())
                path = self.new_path(WildlandObjectType.BRIDGE, user.owner)
                path.write_bytes(step.bridge.manifest.to_bytes())

        # load encountered users to the current context - may be needed for subcontainers
        self.recognize_users_and_bridges(
            [ustep.user for ustep in final_step.steps_chain()
             if ustep.user is not None],
            [ustep.bridge for ustep in final_step.steps_chain()
             if ustep.bridge is not None])

    def load_containers_from(self, name: Union[str, WildlandPath],
                             aliases: Optional[dict] = None,
                             bridge_placeholders: bool = True,
                             include_user_infrastructure: bool = False,
                             ) -> Iterator[Container]:
        """
        Load a list of containers. Currently supports WL paths, glob patterns (*) and
        tilde (~), but only in case of local files.

        :param name: containers to load - can be a local path (including glob) or a Wildland path
        :param aliases: aliases to use when resolving a Wildland path
        :param bridge_placeholders: include bridges as placeholder containers
        """
        wlpath = None
        if isinstance(name, WildlandPath):
            wlpath = name
            name = str(wlpath)
        elif WildlandPath.match(name):
            wlpath = WildlandPath.from_str(name)

        if wlpath:
            try:
                if aliases is None:
                    aliases = self.config.aliases
                search = Search(self, wlpath, aliases)
                for final_step in search.resolve_raw():
                    if final_step.container is None and final_step.bridge is None:
                        # should not happen right now, but might in the future;
                        # but also makes below conditions a bit nicer, as we can assume it is
                        # either container or a bridge
                        continue
                    if final_step.container is None and not bridge_placeholders:
                        continue
                    if final_step.container is not None \
                            and final_step.user is not None \
                            and not include_user_infrastructure:
                        continue
                    self.recognize_users_from_search(final_step)

                    if final_step.container is None:
                        assert final_step.bridge is not None
                        yield final_step.bridge.to_placeholder_container()
                    else:
                        yield final_step.container
            except WildlandError as ex:
                raise ManifestError(f'Failed to load container {name}: {ex}') from ex
            return

        path = self.find_local_manifest(WildlandObjectType.CONTAINER, name)
        if path:
            yield self.load_object_from_file_path(WildlandObjectType.CONTAINER, path)
            return

        paths = sorted(glob.glob(os.path.expanduser(name)))
        logger.debug('expanded %r to %s', name, paths)
        if not paths:
            raise ManifestError(f'No container found matching pattern: {name}')

        failed = False
        exc_msg = 'Failed to load some container manifests:\n'
        for p in paths:
            try:
                yield self.load_object_from_file_path(WildlandObjectType.CONTAINER, Path(p))
            except WildlandError as ex:
                failed = True
                exc_msg += str(ex) + '\n'
                continue

        if failed:
            raise ManifestError(exc_msg)

    def add_storage_to_container(self, container: Container, storage: Storage, inline: bool = True,
                                 storage_name: Optional[str] = None):
        """
        Add storage to container, save any changes. If the given storage exists in the container
        (as determined by backend_id), it gets updated (if possible).
        If not, it is added. If the passed Storage exists in a container but is referenced by an
        url, it can only be saved for file URLS, for other URLs a WildlandError will be raised.
        :param container: Container to add to
        :param storage: Storage to be added
        :param inline: add as inline or standalone storage (ignored if storage exists)
        :param storage_name: optional name to save storage under if inline == False
        """
        storage_manifest = storage.to_unsigned_manifest()
        storage_manifest.skip_verification()

        for idx, backend in enumerate(container.backends):
            container_storage = self.load_object_from_url_or_dict(
                WildlandObjectType.STORAGE, backend, container.owner,
                expected_owner=container.owner, container_path=str(container.paths[0]))

            if container_storage.backend_id == storage.backend_id:
                if container_storage.params == storage.params:
                    logger.info('No changes in storage %s found. Not saving.', storage.backend_id)
                    return

                if isinstance(backend, dict):
                    if backend.get('object', None) == 'link':
                        tg_storage = self.load_object_from_dict(
                            WildlandObjectType.STORAGE, backend['storage'],
                            expected_owner=container.owner, container_path='/')
                        storage_driver = StorageDriver(
                            StorageBackend.from_params(tg_storage.params), tg_storage)
                        self.save_object(WildlandObjectType.STORAGE, storage,
                                         Path(backend['file']).relative_to('/'), storage_driver)
                        return
                    container.backends[idx] = storage_manifest.fields
                else:
                    if backend.startswith('file://'):
                        self.save_object(WildlandObjectType.STORAGE, storage,
                                         self.parse_file_url(backend, container.owner))
                    else:
                        raise WildlandError(f'Cannot updated a standalone storage: {backend}')
                break
        else:
            if inline:
                container.backends.append(storage_manifest.fields)
            else:
                storage_path = self.save_new_object(WildlandObjectType.STORAGE, storage,
                                                    storage_name)
                container.backends.append(self.local_url(storage_path))

        self.save_object(WildlandObjectType.CONTAINER, container)

    def load_all(self, object_type: WildlandObjectType, decrypt: bool = True):
        """
        Load object manifests from the appropriate directory.
        """
        if object_type == WildlandObjectType.USER:
            # Copy sig context and make a new client to avoid propagating recognize_local_keys
            # where it could be dangerous
            sig = self.session.sig.copy()
            sig.recognize_local_keys()
            client = Client(config=self.config, sig=sig, load=False)
        else:
            client = self

        if self.dirs[object_type].exists():
            for path in sorted(self.dirs[object_type].glob('*.yaml')):
                try:
                    obj_ = client.load_object_from_file_path(object_type, path, decrypt=decrypt)
                except WildlandError as e:
                    logger.warning('error loading %s manifest: %s: %s',
                                   object_type.value, path, e)
                else:
                    yield obj_

    def _generare_bridge_paths_recursive(self, path_prefix: List[PurePosixPath],
                                         last_user: str,
                                         target_user: str,
                                         users_seen: Set[str],
                                         bridges_map: Dict[str, List[Bridge]]):
        """
        A helper function for get_bridge_paths_for_user. It takes *path_prefix* and appends every
        matching bridge path (based on *last_user*) from *bridges_map*,
        until *target_user* is reached.
        It uses recursive call for that.
        The *users_seen* parameter is used to avoid loops.
        :return:
        """

        for bridge in bridges_map[last_user]:
            bridge_user = self.session.sig.fingerprint(bridge.user_pubkey)
            if bridge_user in users_seen:
                # avoid loops
                continue
            if bridge_user == target_user:
                for path in bridge.paths:
                    yield tuple(path_prefix + [path])
            if bridge_user in bridges_map:
                for path in bridge.paths:
                    yield from self._generare_bridge_paths_recursive(
                        path_prefix + [path],
                        bridge_user,
                        target_user,
                        users_seen | {bridge_user},
                        bridges_map
                    )

    @functools.lru_cache
    def get_bridge_paths_for_user(self, user: Union[User, str], owner: Optional[User] = None) \
            -> Iterable[Iterable[PurePosixPath]]:
        """
        Get bridge paths to the *user* using bridges owned by *owner*, including multiple hops.
        If owner is not specified, use default user (``@default``).

        :param user: user to look paths for (user id is accepted too)
        :param owner: owner of bridges to consider
        :return: list of paths collected from bridges - each result is a list of bridge paths,
            to be concatenated
        """
        if owner is None:
            try:
                owner = self.load_object_from_name(WildlandObjectType.USER, '@default')
            except WildlandError:
                # if default cannot be loaded, just behave as no bridges were found
                return []

        if isinstance(user, str):
            user = self.load_object_from_name(WildlandObjectType.USER, user)
            assert isinstance(user, User)

        if owner.primary_pubkey == user.primary_pubkey:
            # a single empty list of paths, meaning 0-length bridge path
            return [[]]

        bridges_map: Dict[str, List[Bridge]] = {}
        for bridge in self.bridges:
            bridges_map.setdefault(bridge.owner, []).append(bridge)

        if owner.owner in bridges_map:
            return set(self._generare_bridge_paths_recursive(
                [],
                owner.owner,
                user.owner,
                {owner.owner},
                bridges_map
            ))

        return set()

    def save_object(self, object_type: WildlandObjectType,
                    obj, path: Optional[Path] = None,
                    storage_driver: Optional[StorageDriver] = None) -> Path:
        """
        Save an existing Wildland object and return the path it was saved to.
        :param obj: Object to be saved
        :param object_type: type of object to be saved
        :param path: (optional), path to save the object to; if omitted, object's local_path will be
        used.
        :param storage_driver: if the object should be written to a given StorageDriver
        """
        path = path or obj.local_path
        assert path is not None
        # check if object matches expected object type
        assert obj.OBJECT_TYPE == object_type

        if object_type == WildlandObjectType.USER:
            data = self.session.dump_user(obj)
        else:
            data = self.session.dump_object(obj)

        if storage_driver:
            with storage_driver:
                storage_driver.write_file(path, data)
        else:
            path.write_bytes(data)

        if not storage_driver:
            obj.local_path = path

        if object_type == WildlandObjectType.BRIDGE:
            # cache_clear is added by a decorator, which pylint doesn't see
            # pylint: disable=no-member
            self.get_bridge_paths_for_user.cache_clear()

        return path

    def save_new_object(self, object_type: WildlandObjectType, object_, name: Optional[str] = None,
                        path: Optional[Path] = None):
        """
        Save a new object in appropriate directory. Use the name as a hint for file
        name.
        """
        if not path:
            if not name:
                if object_type == WildlandObjectType.CONTAINER:
                    name = object_.ensure_uuid()
                elif object_type == WildlandObjectType.STORAGE:
                    name = object_.container_path.name
                else:
                    name = object_.owner

            path = self.new_path(object_type, name or object_type.value)

        return self.save_object(object_type, object_, path=path)

    def new_path(self, manifest_type: WildlandObjectType, name: str,
                 skip_numeric_suffix: bool = False) -> Path:
        """
        Create a path in Wildland base_dir to save a new object of type manifest_type and name
        name. It follows Wildland conventions.
        :param manifest_type: 'user', 'container', 'storage', 'bridge' or 'set'
        :param name: name of the object
        :param skip_numeric_suffix: should the path be extended with .1 etc. numeric suffix if
        first inferred path already exists
        :return: Path
        """
        base_dir = self.dirs[manifest_type]

        if not base_dir.exists():
            base_dir.mkdir(parents=True)

        i = 0
        while True:
            suffix = '' if i == 0 else f'.{i}'
            path = base_dir / f'{name}{suffix}.{manifest_type.value}.yaml'
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
                    storage = self.load_object_from_url(WildlandObjectType.STORAGE, url_or_dict,
                                                        owner=container.owner)
                except FileNotFoundError as e:
                    logging.warning('Error loading manifest: %s', e)
                    continue
                except WildlandError:
                    logging.exception('Error loading manifest: %s', url_or_dict)
                    continue

                # Checking storage owner and path is necessary only in external
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
                    storage = self.load_object_from_dict(
                        WildlandObjectType.STORAGE, url_or_dict, expected_owner=container.owner,
                        container_path=container.paths[0])
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

        container = self.load_object_from_url_or_dict(WildlandObjectType.CONTAINER,
                                                      container_url_or_dict, owner=owner)

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
        manifest.skip_verification()
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

    def read_from_url(self, url: str, owner: Optional[str] = None,
                      use_aliases: bool = False) -> bytes:
        """
        Retrieve data from a given URL. The local (file://) URLs
        are recognized based on the 'local_hostname' and 'local_owners'
        settings.
        """

        if WildlandPath.match(url):
            search = self._wl_url_to_search(url, use_aliases=use_aliases)
            return search.read_file()

        if url.startswith('file:'):
            local_path = self.parse_file_url(url, owner or self.config.get('@default'))
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
