# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
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
#
# SPDX-License-Identifier: GPL-3.0-or-later

# pylint: disable=too-many-lines

"""
Client class
"""

import collections.abc
import functools
import glob
import os
import sys
import time
from graphlib import TopologicalSorter
from pathlib import Path, PurePosixPath
from subprocess import Popen
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple, Union, Any
from urllib.parse import urlparse, quote

import yaml
import requests

from wildland.bridge import Bridge
from wildland.control_client import ControlClientUnableToConnectError
from wildland.wildland_object.wildland_object import WildlandObject
from .control_client import ControlClient
from .user import User
from .container import Container, ContainerStub
from .link import Link
from .storage import Storage, _get_storage_by_id_or_type
from .wlpath import WildlandPath, PathError
from .manifest.sig import DummySigContext, SodiumSigContext, SigContext
from .manifest.manifest import ManifestDecryptionKeyUnavailableError, ManifestError, Manifest
from .session import Session
from .storage_backends.base import StorageBackend, verify_local_access
from .fs_client import WildlandFSClient
from .config import Config
from .envprovider import EnvProvider
from .exc import WildlandError
from .search import Search
from .storage_driver import StorageDriver
from .log import get_logger

logger = get_logger('client')


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
            config = EnvProvider.shared().load_config({'base_dir': base_dir})
            config.override(**config_kwargs)
        self.config = config

        self.dirs = {
            WildlandObject.Type.USER: Path(self.config.get('user-dir')),
            WildlandObject.Type.CONTAINER: Path(self.config.get('container-dir')),
            WildlandObject.Type.STORAGE: Path(self.config.get('storage-dir')),
            WildlandObject.Type.BRIDGE: Path(self.config.get('bridge-dir')),
            WildlandObject.Type.TEMPLATE: Path(self.config.get('template-dir'))
        }

        for d in self.dirs.values():
            d.mkdir(exist_ok=True, parents=True)

        self.cache_dir = Path(self.config.get('cache-dir'))
        self.cache_dir.mkdir(exist_ok=True, parents=True)

        mount_dir = Path(self.config.get('mount-dir'))
        self.bridge_separator = '\uFF1A' if self.config.get('alt-bridge-separator') else ':'
        fs_socket_path = Path(self.config.get('fs-socket-path'))
        self.fs_client = WildlandFSClient(base_dir, mount_dir, fs_socket_path,
                                          bridge_separator=self.bridge_separator)

        # we only connect to sync daemon if needed
        self._sync_client: Optional[ControlClient] = None
        self.base_dir = base_dir

        try:
            fuse_status = self.fs_client.run_control_command('status')
            default_user = fuse_status.get('default-user')
            if default_user:
                self.config.override(override_fields={'@default': default_user})
        except ControlClientUnableToConnectError:
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
        self.bridges: Set[Bridge] = set()

        self._local_users_cache: Dict[Path, Optional[Any]] = {}
        self._local_bridges_cache: Dict[Path, Optional[Any]] = {}
        self._select_reference_storage_cache: Dict[Tuple[str, str, bool],
                                                   Optional[Tuple[PurePosixPath, Dict]]] = {}

        if load:
            self.recognize_users_and_bridges()
            self.caches: List[Storage] = []
            self.load_local_storage_cache()

    def get_local_users(self, reload: bool = False):
        """
        List of local users (loaded from the appropriate directory).

        Loads local users and caches.
        :@param reload: if False, load only new manifests and use the cache for the rest;
        if True, reload cached manifests and load new ones but DO NOT reload broken manifests,
        as we do not expect these manifests to fix themselves.
        In short, if the manifest fails to load, do not try to reload it.
        To reload the broken manifest, we need to use `clear_cache()` first.
        """
        local_users_cache: Dict[Path, Optional[Any]] = dict(
            self._find_paths_and_load_all(
                WildlandObject.Type.USER, cached=self._local_users_cache, reload_cached=reload))
        self._local_users_cache = local_users_cache
        return [obj for obj in self._local_users_cache.values() if obj is not None]

    def get_local_bridges(self, reload: bool = False):
        """
        List of local bridges (loaded from the appropriate directory).

        Loads local bridges and caches.
        :@param reload: if False, load only new manifests and use the cache for the rest;
        if True, reload cached manifests and load new ones but DO NOT reload broken manifests,
        as we do not expect these manifests to fix themselves.
        In short, if the manifest fails to load, do not try to reload it.
        To reload the broken manifest, we need to use `clear_cache()` first.
        """
        local_bridges_cache: Dict[Path, Optional[Any]] = dict(
            self._find_paths_and_load_all(
                WildlandObject.Type.BRIDGE, cached=self._local_bridges_cache, reload_cached=reload))
        self._local_bridges_cache = local_bridges_cache
        return [obj for obj in self._local_bridges_cache.values() if obj is not None]

    def clear_cache(self):
        """
        Clear cache: users, bridges and reference storages.
        """
        self._local_users_cache.clear()
        self._local_bridges_cache.clear()
        self._select_reference_storage_cache.clear()

    def load_local_storage_cache(self):
        """
        Load local cache storages from manifests to memory for fast access.
        """
        self.caches.clear()
        for cache in self.load_all(WildlandObject.Type.STORAGE, decrypt=True,
                                   base_dir=self.cache_dir, quiet=True):
            cache.params['is-local-owner'] = True
            self.caches.append(cache)

    def connect_sync_daemon(self):
        """
        Connect to the sync daemon. Starts the daemon if not running.
        """
        delay = 0.5
        daemon_started = False
        sync_socket_path = Path(self.config.get('sync-socket-path'))
        self._sync_client = ControlClient()
        for _ in range(20):
            try:
                self._sync_client.connect(sync_socket_path)
                return
            except ControlClientUnableToConnectError:
                if not daemon_started:
                    self.start_sync_daemon()
                    daemon_started = True
            time.sleep(delay)
        raise WildlandError('Timed out waiting for sync daemon')

    def start_sync_daemon(self):
        """
        Start the sync daemon.
        """
        cmd = [sys.executable, '-m', 'wildland.storage_sync.daemon']
        if self.base_dir:
            cmd.extend(['--base-dir', str(self.base_dir)])
        logger.debug('starting sync daemon: %s', cmd)
        Popen(cmd)

    def run_sync_command(self, name, **kwargs) -> Any:
        """
        Run sync command (through the sync daemon).
        """
        if not self._sync_client:
            self.connect_sync_daemon()
        assert self._sync_client is not None
        return self._sync_client.run_command(name, **kwargs)

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
        for user in users or self.load_all(WildlandObject.Type.USER, decrypt=False):
            user.add_user_keys(self.session.sig)

        # duplicated to decrypt manifests catalog correctly
        for user in users or self.get_local_users(reload=True):
            self.users[user.owner] = user

        for bridge in bridges or self.get_local_bridges(reload=True):
            self.bridges.add(bridge)

    def find_local_manifest(self, object_type: Union[WildlandObject.Type, None],
                            name: str) -> Optional[Path]:
        """
        Find local manifest based on a (potentially ambiguous) name. Names can be aliases, user
        fingerprints (for users), name of the file, part of the file name, or complete file path.
        """

        if object_type == WildlandObject.Type.USER:
            # aliases
            if name == '@default':
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
                for user in self.get_local_users():
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
                               object_type: Union[WildlandObject.Type, None],
                               data: bytes,
                               allow_only_primary_key: Optional[bool] = None,
                               file_path: Optional[Path] = None,
                               trusted_owner: Optional[str] = None,
                               local_owners: Optional[List[str]] = None,
                               decrypt: bool = True,
                               expected_owner: Optional[str] = None):
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
        :param expected_owner: if object received has a different owner than that, raise an
        ManifestError
        """

        if allow_only_primary_key is None:
            allow_only_primary_key = object_type == WildlandObject.Type.USER

        manifest = Manifest.from_bytes(data, self.session.sig,
                                       allow_only_primary_key=allow_only_primary_key,
                                       decrypt=decrypt, trusted_owner=trusted_owner,
                                       local_path=file_path)

        wl_object = WildlandObject.from_manifest(manifest, self, object_type,
                                                 local_owners=local_owners)
        if expected_owner and wl_object.owner != expected_owner:
            raise WildlandError(f'Unexpected owner: expected {expected_owner}, '
                                f'encountered {wl_object.owner}')
        return wl_object

    def load_link_object(self, link_dict: dict, expected_owner: Optional[str]) -> Link:
        """Load a Link object from a dictionary"""
        if isinstance(link_dict['storage'], dict):
            if 'version' not in link_dict['storage']:
                link_dict['storage']['version'] = Manifest.CURRENT_VERSION
            storage_obj = self.load_object_from_dict(
                WildlandObject.Type.STORAGE, link_dict['storage'], expected_owner=expected_owner,
                container_path='/')
            storage_backend = StorageBackend.from_params(storage_obj.params, deduplicate=True)
        elif isinstance(link_dict['storage'], StorageBackend):
            storage_backend = link_dict['storage']
        else:
            raise ValueError('Incorrect Link object format')

        link = Link(file_path=link_dict['file'], storage_backend=storage_backend)
        return link

    def load_object_from_dict(self,
                              object_type: Union[WildlandObject.Type, None],
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
        if 'encrypted' in dictionary.keys():
            raise ManifestDecryptionKeyUnavailableError()
        if dictionary.get('object') == 'link':
            link = self.load_link_object(dictionary, expected_owner)
            obj = self.load_object_from_bytes(object_type, link.get_target_file())
            if expected_owner and obj.owner != expected_owner:
                raise WildlandError('Owner mismatch: expected {}, got {}'.format(
                    expected_owner, obj.owner))
            return obj

        if expected_owner:
            if 'owner' not in dictionary:
                dictionary['owner'] = expected_owner
            elif expected_owner != dictionary['owner']:
                raise WildlandError('Owner mismatch: expected {}, got {}'.format(
                    expected_owner, dictionary['owner']))
        local_owners = None

        if object_type == WildlandObject.Type.STORAGE:
            # this can happen if we're loading from a Link object; in the future, this should
            # be handled by Link objects
            if 'object' not in dictionary:
                dictionary['object'] = 'storage'
            if 'container-path' not in dictionary and container_path:
                dictionary['container-path'] = str(container_path)

            local_owners = self.config.get('local-owners')

        wl_object = WildlandObject.from_fields(dictionary, self, object_type,
                                               container_path=container_path,
                                               local_owners=local_owners)
        return wl_object

    def load_object_from_url(self, object_type: WildlandObject.Type, url: str,
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

        if object_type == WildlandObject.Type.CONTAINER and WildlandPath.match(url):
            # special treatment for WL paths: they can refer to a file or to a container
            wlpath = WildlandPath.from_str(url)
            if wlpath.file_path is None:
                containers = self.load_containers_from(wlpath, {'default': owner})
                result = None
                for c in containers:
                    if not result:
                        result = c
                    else:
                        if c.owner != result.owner or c.uuid != result.uuid:
                            raise PathError(f'Expected single container, found multiple: {wlpath}')
                if not result:
                    raise PathError(f'Container not found for path: {wlpath}')
                return result

        content = self.read_from_url(url, owner)

        if object_type == WildlandObject.Type.USER:
            Manifest.verify_and_load_pubkeys(content, self.session.sig)

        local_owners = self.config.get('local-owners')

        obj_ = self.load_object_from_bytes(None, content, local_owners=local_owners)
        if expected_owner and obj_.owner != expected_owner:
            raise WildlandError(f'Unexpected owner: expected {expected_owner}, got {obj_.owner}')

        return obj_

    def load_object_from_file_path(self, object_type: WildlandObject.Type, path: Path,
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

    def load_object_from_url_or_dict(self, object_type: WildlandObject.Type,
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

    def load_object_from_name(self, object_type: WildlandObject.Type, name: str):
        """
        Load a Wildland object from ambiguous name. The name can be a local filename, part of local
        filename (will attempt to look for the object in appropriate local directory), a WL URL,
        another kind of URL etc.
        :param object_type: expected object type
        :param name: ambiguous name
        """
        if object_type == WildlandObject.Type.USER and name in self.users:
            return self.users[name]

        if self.is_url(name):
            return self.load_object_from_url(object_type, name, self.config.get('@default'))

        path = self.find_local_manifest(object_type, name)
        if path:
            return self.load_object_from_file_path(object_type, path)

        raise WildlandError(f'{object_type.value} not found: {name}')

    def find_storage_usage(self, storage_id: Union[Path, str]) \
            -> List[Tuple[Container, Union[Path, str]]]:
        """Find containers which can use storage given by path or backend-id.

        :param storage_id: storage path or backend_id
        :return: list of tuples (container, storage_url_or_dict)
        """
        used_by = []
        for container in self.load_all(WildlandObject.Type.CONTAINER):
            assert container.local_path
            if container.is_backend_in_use(storage_id):
                used_by.append((container, storage_id))
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
                path = self.new_path(WildlandObject.Type.USER, user.owner)
                path.write_bytes(user.manifest.to_bytes())
                path = self.new_path(WildlandObject.Type.BRIDGE, user.owner)
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
                             include_manifests_catalog: bool = False,
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
                            and not include_manifests_catalog:
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

        path = self.find_local_manifest(WildlandObject.Type.CONTAINER, name)
        if path:
            yield self.load_object_from_file_path(WildlandObject.Type.CONTAINER, path)
            return

        paths = sorted(glob.glob(os.path.expanduser(name)))
        logger.debug('expanded %r to %s', name, paths)
        if not paths:
            raise ManifestError(f'No container found matching pattern: {name}')

        failed = False
        exc_msg = 'Failed to load some container manifests:\n'
        for p in paths:
            try:
                yield self.load_object_from_file_path(WildlandObject.Type.CONTAINER, Path(p))
            except WildlandError as ex:
                failed = True
                exc_msg += f"Couldn't load container manifest: {p}: {str(ex)}\n"
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
        container.add_storage_from_obj(storage, inline, storage_name)
        self.save_object(WildlandObject.Type.CONTAINER, container)

    def load_all(self, object_type: WildlandObject.Type, decrypt: bool = True,
                 base_dir: Path = None, quiet: bool = False):
        """
        Load object manifests from the appropriate directory.
        """
        for _, obj in self._find_paths_and_load_all(object_type, decrypt, base_dir, quiet):
            if obj is not None:
                yield obj

    def _find_paths_and_load_all(self,
                                 object_type: WildlandObject.Type,
                                 decrypt: bool = True,
                                 base_dir: Path = None,
                                 quiet: bool = False,
                                 reload_cached: bool = False,
                                 cached: Optional[Dict[Path, Optional[WildlandObject]]] = None):
        """
        Load and return object manifests with corresponding path from the appropriate directory.
        """
        if object_type == WildlandObject.Type.USER:
            # Copy sig context and make a new client to avoid propagating recognize_local_keys
            # where it could be dangerous
            sig = self.session.sig.copy()
            sig.recognize_local_keys()
            client = Client(config=self.config, sig=sig, load=False)
        else:
            client = self

        base_dir = base_dir or self.dirs[object_type]
        if base_dir.exists():
            for path in sorted(base_dir.glob('*.yaml')):
                if cached and path in cached and (not reload_cached or cached[path] is None):
                    yield path, cached[path]
                    continue
                try:
                    obj_ = client.load_object_from_file_path(object_type, path, decrypt=decrypt)
                except WildlandError as e:
                    if not quiet:
                        logger.warning('error loading %s manifest: %s: %s',
                                       object_type.value, path, e)
                    yield path, None
                else:
                    yield path, obj_

    def load_users_with_bridge_paths(self, only_default_user: bool = False) -> \
            Iterable[Tuple[User, Optional[List[PurePosixPath]]]]:
        """
        Helper method to return users with paths from bridges leading to those users.
        """
        bridge_paths: Dict[str, List[PurePosixPath]] = {}
        default_user = self.config.get('@default')

        for bridge in self.get_local_bridges():
            if only_default_user and bridge.owner != default_user:
                continue
            if bridge.user_id not in bridge_paths:
                bridge_paths[bridge.user_id] = []
            bridge_paths[bridge.user_id].extend(bridge.paths)

        for user in self.get_local_users():
            yield user, bridge_paths.get(user.owner)

    def _generate_bridge_paths_recursive(self, path_prefix: List[PurePosixPath],
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
                    yield from self._generate_bridge_paths_recursive(
                        path_prefix + [path],
                        bridge_user,
                        target_user,
                        users_seen | {bridge_user},
                        bridges_map
                    )

    def ensure_mount_reference_container(self, containers: Iterator[Container],
                                         callback_iter_func=iter) -> \
            Tuple[List[Container], str]:
        """
        Ensure that for any storage with ``MOUNT_REFERENCE_CONTAINER`` corresponding
        ``reference_container`` appears in sequence before the referencer.
        """

        dependency_graph: Dict[Container, Set[Container]] = dict()
        exc_msg = ""
        containers_to_process = []
        try:
            for c in containers:
                containers_to_process.append(c)
        except WildlandError as ex:
            exc_msg += str(ex) + '\n'

        def open_node(container: Container):
            for storage in self.all_storages(container):
                if 'reference-container' not in storage.params:
                    continue

                backend_cls = StorageBackend.types()[storage.params['type']]
                if not backend_cls.MOUNT_REFERENCE_CONTAINER:
                    continue

                container_url_or_dict = storage.params['reference-container']
                referenced = self.load_object_from_url_or_dict(
                    WildlandObject.Type.CONTAINER,
                    container_url_or_dict, container.owner
                )

                if container in dependency_graph.keys():
                    dependency_graph[container].add(referenced)
                else:
                    dependency_graph[container] = {referenced}
                if referenced not in containers_to_process:
                    containers_to_process.append(referenced)

        for container in callback_iter_func(containers_to_process):
            try:
                open_node(container)
            except WildlandError as ex:
                exc_msg += str(ex) + '\n'

        ts = TopologicalSorter(dependency_graph)
        dependencies_first = list(ts.static_order())

        final_order = []
        for i in containers_to_process:
            if i in dependencies_first:
                continue
            final_order.append(i)
        final_order = dependencies_first + final_order
        return final_order, exc_msg

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
                owner = self.load_object_from_name(WildlandObject.Type.USER, '@default')
            except WildlandError:
                # if default cannot be loaded, just behave as no bridges were found
                return []

        if isinstance(user, str):
            user = self.load_object_from_name(WildlandObject.Type.USER, user)
            assert isinstance(user, User)

        if owner.primary_pubkey == user.primary_pubkey:
            # a single empty list of paths, meaning 0-length bridge path
            return [[]]

        bridges_map: Dict[str, List[Bridge]] = {}
        for bridge in self.bridges:
            bridges_map.setdefault(bridge.owner, []).append(bridge)

        if owner.owner in bridges_map:
            return set(self._generate_bridge_paths_recursive(
                [],
                owner.owner,
                user.owner,
                {owner.owner},
                bridges_map
            ))

        return set()

    def save_object(self, object_type: WildlandObject.Type,
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
        if object_type == WildlandObject.Type.USER:
            data = self.session.dump_user(obj, path)
        else:
            data = self.session.dump_object(obj, path)

        if storage_driver:
            with storage_driver:
                storage_driver.write_file(path, data)
        else:
            path.write_bytes(data)

        if object_type == WildlandObject.Type.BRIDGE:
            # cache_clear is added by a decorator, which pylint doesn't see
            # pylint: disable=no-member
            self.get_bridge_paths_for_user.cache_clear()

        return path

    def save_new_object(self, object_type: WildlandObject.Type, object_, name: Optional[str] = None,
                        path: Optional[Path] = None):
        """
        Save a new object in appropriate directory. Use the name as a hint for file
        name.
        """
        if not path:
            if not name:
                if object_type == WildlandObject.Type.CONTAINER:
                    name = object_.uuid
                elif object_type == WildlandObject.Type.STORAGE:
                    name = object_.container_path.name
                else:
                    name = object_.owner

            path = self.new_path(object_type, name or object_type.value)

        return self.save_object(object_type, object_, path=path)

    def new_path(self, manifest_type: WildlandObject.Type, name: str,
                 skip_numeric_suffix: bool = False, base_dir: Path = None) -> Path:
        """
        Create a path in Wildland base_dir to save a new object of type manifest_type and name
        name. It follows Wildland conventions.
        :param manifest_type: 'user', 'container', 'storage', 'bridge' or 'set'
        :param name: name of the object
        :param skip_numeric_suffix: should the path be extended with .1 etc. numeric suffix if
        first inferred path already exists
        :param base_dir: override base directory if present
        :return: Path
        """
        base_dir = base_dir or self.dirs[manifest_type]

        if not base_dir.exists():
            base_dir.mkdir(parents=True)

        i = 0
        while True:
            suffix = '' if i == 0 else f'.{i}'
            path = base_dir / f'{name}{suffix}.{manifest_type.value}.yaml'
            if skip_numeric_suffix or not path.exists():
                return path
            i += 1

    def cache_storage(self, container: Container) -> Optional[Storage]:
        """
        Return cache storage for the given container.
        """
        for cache in self.caches:
            if cache.container_path == container.uuid_path and \
                    cache.params['original-owner'] == container.owner:
                return cache
        return None

    @staticmethod
    def all_storages(container: Container, *, predicate=None) -> Iterator[Storage]:
        """
        Return (and load on returning) all storages for a given container.

        In case of proxy storage, this will also load a reference storage and
        inline the manifest.
        """
        for storage in container.load_storages():
            if not StorageBackend.is_type_supported(storage.storage_type):
                logger.warning('Unsupported storage manifest: (type %s)', storage.storage_type)
                continue
            if predicate and not predicate(storage):
                continue
            yield storage

    def select_storage(self, container: Container, *, predicate=None) -> Storage:
        """
        Select and load a storage to mount for a container.

        In case of proxy storage, this will also load an reference storage and
        inline the manifest.
        """
        try:
            return next(self.all_storages(container, predicate=predicate))
        except StopIteration as ex:
            raise ManifestError('no supported storage manifest') from ex

    def get_storages_to_mount(self, container: Container) -> List[Storage]:
        """
        Return valid, mountable storages for the given container
        """
        storages = list(self.all_storages(container))

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
            storages = sorted(storages, key=lambda s: not s.is_primary)

        cache = self.cache_storage(container)
        if cache:
            cache.promote_to_primary()
            cache.params['is-local-owner'] = True
            storages.insert(0, cache)
            storages[1].primary = False

        return storages

    def select_reference_storage(
            self,
            container_url_or_dict: Union[str, Dict],
            owner: str,
            trusted: bool) -> Optional[Tuple[PurePosixPath, Dict]]:
        """
        Select a "reference" storage and default container path based on URL
        or dictionary. This resolves a container specification and then selects
        storage for the container.
        """

        # use custom caching that dumps *container_url_or_dict* to yaml,
        # because dict is not hashable (and there is no frozendict in python)
        cache_key = yaml.dump(container_url_or_dict), owner, trusted
        if cache_key in self._select_reference_storage_cache:
            return self._select_reference_storage_cache[cache_key]

        container = self.load_object_from_url_or_dict(WildlandObject.Type.CONTAINER,
                                                      container_url_or_dict, owner=owner)

        if trusted and container.owner != owner:
            logger.error(
                'owner field mismatch for trusted reference container: outer %s, inner %s',
                owner, container.owner)
            self._select_reference_storage_cache[cache_key] = None
            return None

        reference_storage = self.select_storage(container)
        mount_path = self.fs_client.get_primary_unique_mount_path(container, reference_storage)
        result = mount_path, reference_storage.params
        self._select_reference_storage_cache[cache_key] = result
        return result

    def load_subcontainer_object(
            self, container: Container, storage: Storage,
            subcontainer_obj: Union[ContainerStub, Link]) -> Union[Container, Bridge]:
        """
        Transform a Link or ContainerStub into a real Container or Bridge.
        Fill remaining fields of the subcontainer and possibly apply transformations.
        """
        trusted_owner = None
        if storage.trusted:
            trusted_owner = storage.owner

        if isinstance(subcontainer_obj, Link):
            target_bytes = subcontainer_obj.get_target_file()
            return self.load_object_from_bytes(None,
                                               target_bytes, trusted_owner=trusted_owner,
                                               expected_owner=container.owner)
        return subcontainer_obj.get_container(container)

    def all_subcontainers(self, container: Container) -> Iterator[Union[Container, Bridge]]:
        """
        List subcontainers of this container.

        This takes only the first backend that is capable of sub-containers functionality.
        :param container:
        :return:
        """
        for storage in self.all_storages(container):
            try:
                backend = StorageBackend.from_params(storage.params, deduplicate=True)
                if backend.MOUNT_REFERENCE_CONTAINER:
                    # Encrypted storage backend does not support subcontainers
                    # enumeration in general case. See #419 for details.
                    continue
                with backend:
                    for _, subcontainer in backend.get_children(self):
                        yield self.load_subcontainer_object(container, storage, subcontainer)
            except NotImplementedError:
                continue
            except (WildlandError, ManifestError) as ex:
                logger.warning('Container %s: cannot load subcontainer: %s',
                               container.uuid, str(ex))
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
            try:
                file_bytes = search.read_file()
            except FileNotFoundError as e:
                raise WildlandError(f'File [{url}] does not exist') from e
            return file_bytes

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

    def get_all_storages(self, container: Container, excluded_storage: Optional[str] = None,
                         only_writable: bool = False):
        """
        List of all storages (including cache storages) for the provided container.

        If excluded_storage is provided, it will filter out the corresponding Storage
        object from the resulting list.

        If only_writable is provided as True, it will filter out storages which are
        read only.

        :param container: Container object
        :param excluded_storage: Storage backend_id
        :param only_writable: Bool
        :return: List of Storage objects
        """
        all_storages = list(self.all_storages(container))
        cache = self.cache_storage(container)
        if cache:
            all_storages.append(cache)

        # fixme: we prevent returning storages with multiple identical backend_id
        #  see wildland/wildland-client/-/issues/583
        filtered_storages: Dict[str, Storage] = {}

        for s in all_storages:
            if filtered_storages.get(s.backend_id, None):
                raise WildlandError("Duplicate backend-id found! Aborting...")
            if only_writable and not s.is_writeable:
                continue
            filtered_storages[s.backend_id] = s

        if excluded_storage:
            storage_to_ignore = _get_storage_by_id_or_type(excluded_storage, all_storages)
            filtered_storages.pop(storage_to_ignore.backend_id, None)

        # Sort storages in order to have writable first (python is treating False (0) < True (1))
        return sorted(filtered_storages.values(), key=lambda x: x.is_writeable, reverse=True)

    def get_local_storages(self, container: Container, excluded_storage: Optional[str] = None,
                           only_writable: bool = False):
        """
        List of Storage object representing all local storages
        (as defined by self.is_local_storage) for the provided container.

        If excluded_storage is provided, it will filter out the corresponding Storage object
        from the resulting list.

        :param container: Container object
        :param excluded_storage: Storage backend_id
        :param only_writable: Bool
        :return: List of storages objects
        """
        all_storages = self.get_all_storages(container, excluded_storage, only_writable)
        local_storages = [storage for storage in all_storages
                          if self.is_local_storage(storage.params['type'])]
        return local_storages

    def get_local_storage(self, container: Container, local_storage: Optional[str] = None,
                          excluded_storage: Optional[str] = None, only_writable: bool = False):
        """
        Get first local Storage found for the provided container.

        If local_storage is provided as backend_id, it will return the corresponding Storage object
        if it exists.

        If excluded_storage is provided, it will filter out the corresponding Storage object
        from the result.

        :param container: Container object
        :param local_storage: Storage backend_id
        :param excluded_storage: Storage backend_id
        :param only_writable: Bool
        :return: Storage object
        """
        all_storages = self.get_all_storages(container, excluded_storage, only_writable)
        if local_storage:
            storage = _get_storage_by_id_or_type(local_storage, all_storages)
        else:
            try:
                storage = self.get_local_storages(container, excluded_storage, only_writable)[0]
            except IndexError:
                # pylint: disable=raise-missing-from
                raise WildlandError('No local storage backend found')
        return storage

    def get_remote_storages(self, container: Container, excluded_storage: Optional[str] = None,
                            only_writable: bool = False):
        """
        List of Storage object representing all remote storages
        (as defined as being not self.is_local_storage) for the provided container.

        If excluded_storage is provided, it will filter out the corresponding Storage object
        from the resulting list.

        :param container: Container object
        :param excluded_storage: Storage backend_id
        :param only_writable: Bool
        :return: List of storages objects
        """
        all_storages = self.get_all_storages(container, excluded_storage, only_writable)
        default_remotes = self.config.get('default-remote-for-container')

        target_remote_id = default_remotes.get(container.uuid, None)
        remote_storages = [storage for storage in all_storages
                           if target_remote_id == storage.backend_id or
                           (not target_remote_id and
                            not self.is_local_storage(storage.params['type']))]
        return remote_storages

    def get_remote_storage(self, container: Container, remote_storage: Optional[str] = None,
                           excluded_storage: Optional[str] = None, only_writable: bool = False):
        """
        Get first remote Storage found for the provided container.

        If remote_storage is provided as backend_id, it will return the corresponding Storage object
        if it exists.

        If excluded_storage is provided, it will filter out the corresponding Storage object
        from the result.

        :param container: Container object
        :param remote_storage: Storage backend_id
        :param excluded_storage: Storage backend_id
        :param only_writable: Bool
        :return: Storage object
        """
        all_storages = self.get_all_storages(container, excluded_storage, only_writable)
        default_remotes = self.config.get('default-remote-for-container')

        if remote_storage:
            storage = _get_storage_by_id_or_type(remote_storage, all_storages)
            default_remotes[container.uuid] = storage.backend_id
            self.config.update_and_save({'default-remote-for-container': default_remotes})
        else:
            try:
                storage = self.get_remote_storages(container, excluded_storage, only_writable)[0]
            except IndexError:
                # pylint: disable=raise-missing-from
                raise WildlandError('No remote storage backend found: specify --target-storage.')
        return storage

    def do_sync(self, container_name: str, job_id: str, source: dict, target: dict,
                one_shot: bool, unidir: bool) -> str:
        """
        Start sync between source and target storages
        """
        kwargs = {'container_name': container_name, 'job_id': job_id, 'continuous': not one_shot,
                  'unidirectional': unidir, 'source': source, 'target': target}
        return self.run_sync_command('start', **kwargs)
