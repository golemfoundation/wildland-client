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

"""
Wildland FS client
"""
import itertools
import time
from pathlib import Path, PurePosixPath
import subprocess
import logging
from typing import Callable, Dict, List, Optional, Iterable, Tuple, Iterator
import json
import sys
import hashlib
import dataclasses
import glob
import re

from .cli.cli_base import CliError
from .container import Container
from .storage import Storage
from .exc import WildlandError
from .control_client import ControlClient
from .entity.fileinfo import FileInfo
from .manifest.manifest import Manifest
from .storage_backends.static import StaticStorageBackend

logger = logging.getLogger('fs_client')


@dataclasses.dataclass
class PathTree:
    """
    A prefix tree for efficient determining of mounted storages.
    """

    storage_ids: List[int]
    children: Dict[str, 'PathTree']


@dataclasses.dataclass
class WatchEvent:
    """
    A file change event.
    """

    event_type: str  # create, modify, delete
    pattern: str  # pattern that generated this event
    path: PurePosixPath  # absolute path in Wildland namespace


class WildlandFSError(WildlandError):
    """Error while trying to control Wildland FS."""


class WildlandFSClient:
    """
    A class to communicate with Wildland filesystem over the .control API.
    """

    def __init__(self, mount_dir: Path, socket_path: Path, bridge_separator: str = ':'):
        self.mount_dir = mount_dir
        self.socket_path = socket_path
        self.bridge_separator = bridge_separator

        self.path_cache: Optional[Dict[PurePosixPath, List[int]]] = None
        self.path_tree: Optional[PathTree] = None
        self.info_cache: Optional[Dict[int, Dict]] = None

    def clear_cache(self) -> None:
        """
        Clear cached information after changing state of the system.
        """
        self.path_cache = None
        self.path_tree = None
        self.info_cache = None

    def start(self, foreground=False, debug=False, single_thread=False,
              default_user=None) -> subprocess.Popen:
        """
        Start Wildland and wait until the FUSE daemon is started.

        Returns the called process (running in case of foreground=True).

        Args:
            foreground: Run in foreground instead of daemonizing
            debug: Enable debug logs (only in case of foreground)
            single_thread: Run single-threaded
            default_user: specify a different default user
        """
        self.clear_cache()

        cmd = [sys.executable, '-m', 'wildland.fs', str(self.mount_dir)]
        options = [
            'socket=' + str(self.socket_path)
        ]

        if foreground:
            options.append('log=-')
            cmd.append('-f')
            if debug:
                cmd.append('-d')

        if single_thread:
            options.append('single_thread')

        if foreground and single_thread:
            options.append('breakpoint')

        if default_user:
            options.append('default_user=' + default_user.owner)

        if options:
            cmd += ['-o', ','.join(options)]

        logger.info('running start command: %s', cmd)

        # Start a new session in order to not propagate SIGINT.
        # pylint: disable=consider-using-with
        proc = subprocess.Popen(cmd, start_new_session=True)
        if foreground:
            self.wait_for_mount()
            return proc
        try:
            proc.wait()
            self.wait_for_mount()
            if proc.returncode != 0:
                raise WildlandFSError(f'Command failed: {cmd}')
            return proc
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """
        Stop Wildland.
        """
        self.clear_cache()
        cmd = ['umount', str(self.mount_dir)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise WildlandFSError(f'Failed to stop: {e}') from e

    def is_running(self) -> bool:
        """
        Check if Wildland is currently running.
        """

        client = ControlClient()
        try:
            client.connect(self.socket_path)
        except IOError:
            return False
        client.disconnect()
        return True

    def run_control_command(self, name, **kwargs):
        """
        Run a command using the control socket.
        """

        # TODO: This creates a new connection for every command. Improve
        # performance by keeping an open connection.
        client = ControlClient()
        client.connect(self.socket_path)
        try:
            return client.run_command(name, **kwargs)
        finally:
            client.disconnect()

    def ensure_mounted(self) -> None:
        """
        Check that Wildland is started, and raise an exception otherwise.
        """

        if not self.is_running():
            raise WildlandFSError(
                f'Wildland daemon not started at {self.mount_dir}. Use wl start.')

    def wait_for_mount(self, timeout=2) -> None:
        """
        Wait until Wildland is started.
        """

        delay = 0.1
        n_tries = int(timeout / delay)
        for _ in range(n_tries):
            if self.is_running():
                return
            time.sleep(delay)
        raise WildlandFSError('Timed out waiting for Wildland to start')

    def mount_container(self,
                        container: Container,
                        storages: List[Storage],
                        user_paths: Iterable[Iterable[PurePosixPath]] = ((),),
                        subcontainer_of: Optional[Container] = None,
                        remount: bool = False) -> None:
        """
        Mount a container, assuming a storage has been already selected.
        """

        self.mount_multiple_containers([(container, storages, user_paths, subcontainer_of)],
                                       remount=remount)

    def mount_multiple_containers(
            self,
            params: Iterable[Tuple[Container, Iterable[Storage], Iterable[Iterable[PurePosixPath]],
                                   Optional[Container]]],
            remount: bool = False,
            unique_path_only: bool = False) -> None:
        """
        Mount multiple containers using a single command.
        """
        self.clear_cache()

        storage_commands = self._generate_command_for_mount_container(
            params, remount, unique_path_only)
        pseudomanifests_commands = self._generate_command_for_mount_pseudomanifest_container(
            params, remount, unique_path_only)

        assert len(storage_commands) == len(pseudomanifests_commands)

        commands = storage_commands + pseudomanifests_commands

        self.run_control_command('mount', items=commands)

    def _generate_command_for_mount_container(self,
            params: Iterable[Tuple[Container, Iterable[Storage], Iterable[Iterable[PurePosixPath]],
                                   Optional[Container]]],
            remount: bool = False,
            unique_path_only: bool = False) -> List[Dict]:

        identity_storage_generator = lambda _, storage : storage
        commands = self._get_commands_for_mount_containers(
            params, remount, unique_path_only, False, identity_storage_generator)

        return commands

    def _generate_command_for_mount_pseudomanifest_container(self,
            params: Iterable[Tuple[Container, Iterable[Storage], Iterable[Iterable[PurePosixPath]],
                                   Optional[Container]]],
            remount: bool = False,
            unique_path_only: bool = False) -> List[Dict]:

        pseudomanifest_commands = self._get_commands_for_mount_containers(
            params, remount, unique_path_only, True, self._generate_pseudomanifest_storage)

        return pseudomanifest_commands

    def _get_commands_for_mount_containers(self,
            params: Iterable[Tuple[Container, Iterable[Storage], Iterable[Iterable[PurePosixPath]],
                                   Optional[Container]]],
            remount: bool,
            unique_path_only: bool,
            is_hidden: bool,
            storage_generator: Callable[[Container, Storage], Storage]) -> List[Dict]:

        return [
            self.get_command_for_mount_container(
                container, storage_generator(container, storage), user_paths, remount=remount,
                subcontainer_of=subcontainer_of, unique_path_only=unique_path_only,
                is_hidden=is_hidden)
            for container, storages, user_paths, subcontainer_of in params
            for storage in storages
        ]

    @staticmethod
    def _generate_pseudomanifest_storage(container: Container, storage: Storage) -> Storage:
        """
        Create pseudomanifest storage out of storage params and paths.
        """

        pseudo_manifest_params = {
            'object': 'container',
            'owner': storage.owner,
            'paths': [str(p) for p in container.paths],
            'title': container.title or 'null',
            'categories': [str(p) for p in container.categories],
            'version': storage.params.get('version', 'null'),
            'access': storage.params.get('access', [])
        }
        storage_manifest = Manifest.from_fields(pseudo_manifest_params)
        pseudomanifest_content = storage_manifest.original_data.decode('utf-8')

        static_params = {
            'type': 'static',
            'content': {
                '.manifest.wildland.yaml': pseudomanifest_content
            },
            'primary': storage.is_primary,  # determines how many mountpoints are generated
            'backend-id': storage.backend_id,
            'owner': storage.owner,
            'container-path': str(container.paths[0]),
            'version': Manifest.CURRENT_VERSION,
        }
        return Storage(storage.owner, StaticStorageBackend.TYPE, container.uuid_path,
                       trusted=True, params=static_params, client=container.client)

    def unmount_storage(self, storage_id: int) -> None:
        """
        Unmount a storage with given storage id.
        """

        self.clear_cache()
        self.run_control_command('unmount', storage_id=storage_id)

    def find_primary_storage_id(self, container: Container) -> Optional[int]:
        """
        Find primary storage ID for a given container.
        A primary storage is the one that mounts under all container paths and not just
        under /.backends/...
        """

        mount_path = self.get_user_container_path(container.owner, container.paths[0])
        return self.find_storage_id_by_path(mount_path)

    def find_storage_id_by_path(self, path: PurePosixPath) -> Optional[int]:
        """
        Find first storage ID for a given mount path. ``None` is returned if the given path is not
        related to any storage.
        """
        paths = self.get_paths()
        storage_ids = paths.get(path)

        if not storage_ids:
            return None

        is_pseudomanifest_pair, storage_id = \
            self._is_storage_id_with_pseudomanifest_storage_id(storage_ids)

        if not is_pseudomanifest_pair and len(storage_ids) > 1:
            logger.warning('multiple non-psuedomanifest storages found for path: %s (storage '
                            'ids: %s)', path, str(storage_ids))

        return storage_id

    def find_all_storage_ids_by_path(self, path: PurePosixPath) -> List[int]:
        """
        Find all storage IDs for a given mount path. This method is similar to
        :meth:`WildlandFSClient.find_storage_id_by_path` but instead of returning just one (first)
        storage ID, it returns all of them. This method is useful when unmounting a storage by given
        path.

        Note that this method returns at least 2 storage IDs if called with ``path`` corresponding
        to primary storage: one for pseudomanifest storage (which is also mounted in primary path)
        and one for the underlying storage.
        """
        paths = self.get_paths()
        return paths.get(path, [])

    def get_primary_unique_mount_path_from_storage_id(self, storage_id: int) -> PurePosixPath:
        """
        Get primary unique mount path corresponding to a given storage ID.
        """
        storage_info = self.get_info()
        assert storage_id in storage_info
        return storage_info[storage_id]['paths'][0]

    def _is_storage_id_with_pseudomanifest_storage_id(self, storage_ids: List[int]) -> \
            Tuple[bool, int]:
        """
        Check if the given list of storage IDs contains two items:
        - a storage ID corresponding to pseudo-manifest,
        - backing storage ID corresponding to the above-mentioned pseudo-manifest storage ID.

        If it is True, return ``(True, non-pseudomanifest storage ID)``.
        Otherwise return ``(False, storage_ids[0])``.
        """
        assert len(storage_ids) > 0
        storage_id = storage_ids[0]

        if len(storage_ids) != 2:
            return False, storage_id

        info = self.get_info()
        all_paths = (
            info[storage_ids[0]]['paths'],
            info[storage_ids[1]]['paths']
        )

        assert len(all_paths[0]) > 0
        assert len(all_paths[1]) > 0

        matching_main_paths = False

        for i, j in (0, 1), (1, 0):
            if str(all_paths[i][0]) + '-pseudomanifest' == str(all_paths[j][0]):
                matching_main_paths = True
                storage_id = i
                break

        # pseudomanifest storage has the same mountpoint list as its underlying storage except the
        # first (main) path
        return matching_main_paths and all_paths[0][1:] == all_paths[1][1:], storage_id

    def get_orphaned_container_storage_paths(self, container: Container, storages_to_mount) \
            -> List[PurePosixPath]:
        """
        Returns list of mounted paths that are mounted but do not exist in the given container.
        This situation may happen when you want to remount a container that has some storages
        removed from the manifest since the last mount.
        """
        mounted_paths = self.get_unique_storage_paths(container)
        filtered_mounted_paths = filter(lambda path: not path.name.endswith('-pseudomanifest'),
                                        mounted_paths)
        valid_paths = [
            self.get_primary_unique_mount_path(container, storage)
            for storage in storages_to_mount]

        return list(set(filtered_mounted_paths) - set(valid_paths))

    def get_container_from_storage_id(self, storage_id: int) -> Container:
        """
        Reconstruct a :class:`Container` object from paths.

        This extracts basic metadata from list of paths (uuid, owner etc.) and builds a
        :class:`Container` object that mimics the original one. Some fields cannot be extracted this
        way (like list of backends) so they will be skipped.

        :param storage_id: storage id
        :return:
        """
        # search for uuid path in /.users/
        container_paths = []
        owner = None
        info = self.get_info()
        for path in info[storage_id]['paths']:
            try:
                # this raises ValueError for not matching paths
                users_path = path.relative_to('/.users')
                owner = users_path.parts[0]
                container_paths.append(PurePosixPath('/').joinpath(
                    *users_path.parts[1:]))
            except ValueError:
                continue
        if owner is None:
            raise ValueError('cannot determine owner of the container')
        return Container(
            owner=owner,
            paths=container_paths,
            backends=[],
            client=None
        )

    def find_all_subcontainers_storage_ids(self, container: Container, recursive: bool = True) \
            -> Iterable[int]:
        """
        Find storage ID for a given mount path.
        """

        container_id = f'{container.owner}:{container.paths[0]}'
        info = self.get_info()
        for storage_id in info:
            if info[storage_id]['subcontainer_of'] == container_id:
                yield storage_id
                if recursive:
                    yield from self.find_all_subcontainers_storage_ids(
                        self.get_container_from_storage_id(storage_id),
                        recursive=recursive)

    def find_all_storage_ids_for_path(self, path: PurePosixPath) \
            -> Iterable[Tuple[int, PurePosixPath, PurePosixPath]]:
        """
        Given a path, retrieve all mounted storages this path is inside.

        Note that this doesn't include synthetic directories leading up to mount path, e.g. if a
        storage is mounted under ``/a/b``, then it will be included as a storage for ``/a/b`` and
        ``/a/b/c``, but not for ``/a``.
        """

        tree = self.get_path_tree()
        assert not tree.storage_ids  # root has no storages
        for i, part in enumerate(path.parts):
            if part not in tree.children:
                break
            tree = tree.children[part]
            storage_path = PurePosixPath(*path.parts[:i + 1])
            relpath = PurePosixPath(*path.parts[i + 1:])
            for storage_id in tree.storage_ids:
                yield storage_id, storage_path, relpath

    def pathinfo(self, local_path: Path) -> Iterable[FileInfo]:
        """
        Given an absolute path to a mounted file, return diagnostic information about the file such
        as file's unique hash and storage that is exposing this file.
        """
        assert local_path.is_absolute()

        if not local_path.exists():
            raise CliError(f'[{local_path}] does not exist')

        try:
            relpath = local_path.resolve().relative_to(self.mount_dir)
        except ValueError as e:
            raise CliError(f'Given path [{local_path}] is not a subpath of the mountpoint '
                f'[{self.mount_dir}]') from e

        if local_path.is_dir():
            results = self.run_control_command('dirinfo', path=('/' + str(relpath)))
        else:
            results = [self.run_control_command('fileinfo', path=('/' + str(relpath)))]

        for result in results:
            if result:
                yield FileInfo(
                    container_path=result['storage']['container-path'],
                    backend_id=result['storage']['backend-id'],
                    storage_owner=result['storage']['owner'],
                    storage_read_only=result['storage']['read-only'],
                    storage_id=result['storage']['id'],
                    file_token=result.get('token', ''),
                )

    def find_trusted_owner(self, local_path: Path) -> Optional[str]:
        """
        Given a path in the filesystem, check if this is a path from a trusted
        storage, and if so, return the trusted_owner value.

        If the path potentially belongs to multiple storages, this method will
        conservatively check if all of them would give the same answer.
        """

        if not self.is_running():
            return None

        local_path = local_path.resolve()
        try:
            relpath = local_path.relative_to(self.mount_dir)
        except ValueError:
            # Outside our filesystem
            return None

        path = PurePosixPath('/') / relpath
        storage_ids = [
            storage_id
            for storage_id, _storage_path, _relpath in self.find_all_storage_ids_for_path(path)]
        if len(storage_ids) == 0:
            # Outside of any storage
            return None

        info = self.get_info()
        trusted_owners = set()
        for storage_id in storage_ids:
            trusted_owner = info[storage_id]['trusted_owner']
            if trusted_owner is not None:
                trusted_owners.add(trusted_owner)

        if len(trusted_owners) != 1:
            # More than one trusted owner
            return None

        return list(trusted_owners)[0]

    def get_paths(self) -> Dict[PurePosixPath, List[int]]:
        """
        Read a path -> container ID mapping.
        """
        if self.path_cache is not None:
            return self.path_cache

        data = self.run_control_command('paths')
        self.path_cache = {
            PurePosixPath(p): storage_ids
            for p, storage_ids in data.items()
        }
        return self.path_cache

    def get_path_tree(self) -> PathTree:
        """
        Return a path prefix tree, computing it if necessary.
        """

        if self.path_tree is not None:
            return self.path_tree

        self.path_tree = PathTree([], {})
        for path, storage_ids in self.get_paths().items():
            tree = self.path_tree
            for part in path.parts:
                if part not in tree.children:
                    tree.children[part] = PathTree([], {})
                tree = tree.children[part]
            tree.storage_ids.extend(storage_ids)
        return self.path_tree

    def get_info(self) -> Dict[int, Dict]:
        """
        Read storage info served by the FUSE driver.
        """

        if self.info_cache:
            return self.info_cache

        data = self.run_control_command('info')
        self.info_cache = {
            int(ident_str): {
                'paths': [PurePosixPath(p) for p in storage['paths']],
                'type': storage['type'],
                'tag': storage['extra'].get('tag'),
                'trusted_owner': storage['extra'].get('trusted_owner'),
                'subcontainer_of': storage['extra'].get('subcontainer_of'),
                'hidden': storage['extra'].get('hidden', False),
                'title': storage['extra'].get('title'),
                'categories': [PurePosixPath(c) for c in storage['extra'].get('categories', [])],
                'primary': storage['extra'].get('primary')
            } for ident_str, storage in data.items()
        }
        return self.info_cache

    def get_unique_storage_paths(self, container: Optional[Container] = None) \
            -> Iterable[PurePosixPath]:
        """
        Return list of unique mount paths, i.e.:

            /.backends/{container_uuid}/{backend_uuid}[-pseudomanifest]

        for every mounted storage in a given container. If no container is given, return unique
        mount paths for all mounted storages in every container.

        Note that for every ``/.backends/{container_uuid}/{backend_uuid}`` unique mount path, there
        is a respective ``/.backends/{container_uuid}/{backend_uuid}-pseudomanifest`` corresponding
        to a hidden container holding container's pseudomanifest. Both of those two paths are
        returned for all mounted storages in a given container.
        """

        paths = self.get_paths()

        if container:
            pattern = fr'^/.users/{container.owner}{self.bridge_separator}' \
                      fr'/.backends/{container.uuid}/[0-9a-z-]+$'
        else:
            pattern = fr'^/.users/[0-9a-z-]+{self.bridge_separator}' \
                      r'/.backends/[0-9a-z-]+/[0-9a-z-]+$'

        path_regex = re.compile(pattern)

        for path, _storage_id in paths.items():
            if path_regex.match(str(path)):
                yield path

    def should_remount(self, container: Container, storage: Storage,
                       user_paths: Iterable[Iterable[PurePosixPath]]) -> bool:
        """
        Check if a storage needs to be remounted.
        """

        info = self.get_info()

        mount_paths = self.get_storage_mount_paths(container, storage, user_paths)
        storage_id = self.find_storage_id_by_path(mount_paths[0])

        if storage_id is None:
            logger.debug('Storage %s is new. Remounting it inside %s container.',
                         storage.backend_id, container.paths[0])
            return True

        tag = self.get_storage_tag(mount_paths, storage.params)

        if info[storage_id]['tag'] != tag:
            logger.debug('Storage %s has changed. Remounting it inside %s container.',
                         storage.backend_id, container.paths[0])
            return True

        return False

    def get_command_for_mount_container(self,
                                        container: Container,
                                        storage: Storage,
                                        user_paths: Iterable[Iterable[PurePosixPath]],
                                        subcontainer_of: Optional[Container],
                                        unique_path_only: bool = False,
                                        remount: bool = False,
                                        is_hidden: bool = False) -> Dict:
        """
        Prepare parameters for the control client to mount a container.

        Args:
            container (Container): the container to be mounted storages
            storage: the storage selected for container
            user_paths: paths to the owner, should include ``/`` for default user
            unique_path_only: mount only under internal unique path
            (``/.backends/{container_uuid}/{backend_id}``)
            remount: remount if mounted already (otherwise, will fail if mounted already)
        """

        if unique_path_only:
            mount_paths = [self.get_primary_unique_mount_path(container, storage)]
        else:
            mount_paths = self.get_storage_mount_paths(container, storage, user_paths)

        trusted_owner: Optional[str]
        if storage.params.get('trusted'):
            trusted_owner = storage.owner
        else:
            trusted_owner = None

        if is_hidden:
            old_main_path = mount_paths[0]
            new_main_path = old_main_path.parent / (old_main_path.name + '-pseudomanifest')
            mount_paths[0] = new_main_path

        return {
            'paths': [str(p) for p in mount_paths],
            'storage': storage.params,
            'extra': {
                'tag': self.get_storage_tag(mount_paths, storage.params),
                'primary': storage.is_primary,
                'trusted_owner': trusted_owner,
                'subcontainer_of': (f'{subcontainer_of.owner}:{subcontainer_of.paths[0]}'
                                    if subcontainer_of else None),
                'title': container.title,
                'categories': [str(p) for p in container.categories],
                'hidden': is_hidden,
            },
            'remount': remount,
        }

    def join_bridge_paths_for_mount(self, bridges: Iterable[PurePosixPath], path: PurePosixPath)\
            -> PurePosixPath:
        """
        Construct a full mount paths given bridge paths and a container path. This function joins
        the paths using appropriate separator (':'), but also ensures no unwanted characters
        are present in the individual paths.

        :param bridges: list of bridge paths to join
        :param path: container path
        :return:
        """

        return PurePosixPath(
            self.bridge_separator.join(
                str(p).replace(self.bridge_separator, '_')
                for p in itertools.chain(bridges, [path])
            )
        )

    def get_storage_mount_paths(self, container: Container, storage: Storage,
            user_paths: Iterable[Iterable[PurePosixPath]]) -> List[PurePosixPath]:
        """
        Return all mount paths (incl. synthetic ones) for the given storage.

        Container paths always start with ``/.uuid/{container_uuid}`` path which must always be
        present (as defined in Container's constructor'). If a storage is a secondary storage, we
        want to mount it solely under ``/.backends/{container_uuid}/{storage_uuid}`` and
        ``/.users/{uid}/.backends/{container_uuid}/{storage_id}`` directory, otherwise mount it
        additionally under ``/.users/{uid}/.uuid/{uuid}``, ``/.users/{uid}/{path}``,
        ``/.uuid/{uuid}`` and ``/{path}``.
        """
        paths = container.expanded_paths  # only primary storage is mounted in here

        unique_backend_path = storage.get_mount_path(container)

        if storage.is_primary:
            storage_paths = [unique_backend_path, *paths]
        else:
            storage_paths = [unique_backend_path]

        paths = [
            self.join_bridge_paths_for_mount(user_path, path)
            for path in storage_paths
            for user_path in itertools.chain(
                [[self.get_user_path(container.owner)]],
                user_paths)
        ]

        return paths

    def get_primary_unique_mount_path(self, container: Container, storage: Storage) \
            -> PurePosixPath:
        """
        Return a primary unique mount path. This is the mount path that uniquely identify a
        storage of a given container and also where the storage is always mounted -
        regardless of user-provided paths.
        """

        unique_backend_path = storage.get_mount_path(container)
        return self.get_user_container_path(container.owner, unique_backend_path)

    @staticmethod
    def get_storage_tag(paths: List[PurePosixPath], params):
        """
        Compute a hash of storage params, to decide if a storage needs to be
        remounted.
        """

        param_str = json.dumps({
            'params': params,
            'paths': [str(path) for path in paths],
        }, sort_keys=True)
        return hashlib.sha1(param_str.encode()).hexdigest()

    @staticmethod
    def get_user_path(owner: str) -> PurePosixPath:
        """
        Get an FS path for owner namespace.
        """
        return PurePosixPath('/.users/') / owner

    def get_user_container_path(self, owner: str, path: PurePosixPath) -> PurePosixPath:
        """
        Prepend an absolute path with owner namespace.
        """
        return self.get_user_path(owner + self.bridge_separator) / path.relative_to('/')

    def watch(self, patterns: Iterable[str], with_initial=False) \
            -> Iterator[List[WatchEvent]]:
        """
        Watch for changes under the provided list of patterns (as absolute paths).
        lists of WatchEvent objects (so that simultaneous events can be grouped).

        If ``with_initial`` is true, also include initial synthetic events for
        files already found.
        """

        client = ControlClient()
        client.connect(self.socket_path)
        try:
            watches = {}
            for pattern in patterns:
                found = list(self.find_all_storage_ids_for_path(
                    PurePosixPath(pattern)))
                if not found:
                    raise WildlandError(f"couldn't resolve to storage: {pattern}")
                for storage_id, storage_path, relpath in found:
                    logger.debug('watching %d:%s', storage_id, relpath)
                    watch_id = client.run_command(
                        'add-watch', storage_id=storage_id, pattern=str(relpath))
                    watches[watch_id] = (storage_path, pattern)

            if with_initial:
                initial = []
                for pattern in patterns:
                    local_path = self.mount_dir / (PurePosixPath(pattern).relative_to('/'))
                    for file_path in glob.glob(str(local_path)):
                        fs_path = PurePosixPath('/') / Path(file_path).relative_to(
                            self.mount_dir)
                        initial.append(WatchEvent('create', pattern, fs_path))
                if initial:
                    yield initial

            for events in client.iter_events():
                watch_events = []
                for event in events:
                    watch_id = event['watch-id']
                    storage_path, pattern = watches[watch_id]
                    event_type = event['type']
                    path = PurePosixPath(event['path'])
                    watch_events.append(WatchEvent(event_type, pattern, storage_path / path))
                yield watch_events
        except GeneratorExit:
            pass
        finally:
            client.disconnect()
