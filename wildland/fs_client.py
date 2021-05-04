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

"""
Wildland FS client
"""
import itertools
import time
from pathlib import Path, PurePosixPath
import subprocess
import logging
from typing import Dict, List, Optional, Iterable, Tuple, Iterator
import json
import sys
import hashlib
import dataclasses
import glob
import re

from .container import Container
from .storage import Storage
from .exc import WildlandError
from .control_client import ControlClient
from .entity.fileinfo import FileInfo

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

    def __init__(self, mount_dir: Path, socket_path: Path):
        self.mount_dir = mount_dir
        self.socket_path = socket_path

        self.path_cache: Optional[Dict[PurePosixPath, List[int]]] = None
        self.path_tree: Optional[PathTree] = None
        self.info_cache: Optional[Dict[int, Dict]] = None

    def clear_cache(self):
        """
        Clear cached information after changing mount state of the system.
        """
        self.path_cache = None
        self.path_tree = None
        self.info_cache = None

    def mount(self, foreground=False, debug=False, single_thread=False,
              default_user=None) -> subprocess.Popen:
        """
        Mount the Wildland filesystem and wait until it is mounted.

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

        logger.info('running mount command: %s', cmd)

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
            self.unmount()
            raise

    def unmount(self):
        """
        Unmount the Wildland filesystem.
        """
        self.clear_cache()
        cmd = ['umount', str(self.mount_dir)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            raise WildlandFSError(f'Failed to unmount: {e}') from e

    def is_mounted(self) -> bool:
        """
        Check if Wildland is currently mounted.
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

    def ensure_mounted(self):
        """
        Check that Wildland is mounted, and raise an exception otherwise.
        """

        if not self.is_mounted():
            raise WildlandFSError(
                f'Wildland not mounted at {self.mount_dir}')

    def wait_for_mount(self, timeout=2):
        """
        Wait until Wildland is mounted.
        """

        delay = 0.1
        n_tries = int(timeout / delay)
        for _ in range(n_tries):
            if self.is_mounted():
                return
            time.sleep(delay)
        raise WildlandFSError('Timed out waiting for Wildland to mount')

    def mount_container(self,
                        container: Container,
                        storages: List[Storage],
                        user_paths: Iterable[Iterable[PurePosixPath]] = ((),),
                        subcontainer_of: Optional[Container] = None,
                        remount: bool = False):
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
            unique_path_only: bool = False):
        """
        Mount multiple containers using a single command.
        """
        self.clear_cache()

        commands = [
            self.get_command_for_mount_container(
                container, storage, user_paths,
                remount=remount, subcontainer_of=subcontainer_of, unique_path_only=unique_path_only)
            for container, storages, user_paths, subcontainer_of in params
            for storage in storages
        ]
        self.run_control_command('mount', items=commands)

    def unmount_storage(self, storage_id: int):
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
        Find storage ID for a given mount path.
        """
        paths = self.get_paths()
        storage_ids = paths.get(path)
        if storage_ids is None:
            return None
        if len(storage_ids) > 1:
            logger.warning('multiple storages found for path: %s', path)
        return storage_ids[0]

    def get_orphaned_container_storage_paths(self, container: Container, storages_to_mount):
        """
        Returns list of mounted paths that are mounted but do not exist in the given container.
        This situation may happen when you want to remount a container that has some storages
        removed from the manifest since the last mount.
        """
        mounted_paths = self.get_unique_storage_paths(container)
        valid_paths = [
            self.get_primary_unique_mount_path(container, storage)
            for storage in storages_to_mount]

        return list(set(mounted_paths) - set(valid_paths))

    def get_container_from_storage_id(self, storage_id: int):
        """
        Reconstruct a *Container* object from paths.

        This extracts basic metadata from list of paths (uuid, owner etc) and build a Container
        object that mimic the original one. Some fields cannot be extracted this way
        (like list of backends) so they will be skipped.

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
            raise ValueError('cannot determine owner')
        return Container(
            owner=owner,
            paths=container_paths,
            backends=[],
        )

    def find_all_subcontainers_storage_ids(self, container: Container,
                                           recursive: bool = True) -> Iterable[int]:
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
        Give a path to a mounted file, return diag information about the
        file such as file's unique hash and storage that is exposing this
        file.
        """
        try:
            relpath = local_path.resolve().relative_to(self.mount_dir)
        except ValueError:
            logger.warning('Given path [%s] is not relative to mountpoint', local_path)
            return

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

        if not self.is_mounted():
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
        Read storage info served by FUSE driver.
        """

        if self.info_cache is not None:
            return self.info_cache

        data = self.run_control_command('info')
        self.info_cache = {
            int(ident_str): {
                'paths': [PurePosixPath(p) for p in storage['paths']],
                'type': storage['type'],
                'tag': storage['extra'].get('tag', None),
                'trusted_owner': storage['extra'].get('trusted_owner', None),
                'subcontainer_of': storage['extra'].get('subcontainer_of', None),
            }
            for ident_str, storage in data.items()
        }
        return self.info_cache

    def get_unique_storage_paths(self, container: Optional[Container] = None
            ) -> Iterable[PurePosixPath]:
        """
        Returns list of unique mount paths (ie ``/.backends/{container_uuid}/{backend_uuid}``) for
        every mounted storage in a given container. If no container is given, return unique mount
        paths for all mounted storages in every container.
        """

        paths = self.get_paths()

        if container:
            pattern = fr'^/.users/{container.owner}:' \
                fr'/.backends/{container.ensure_uuid()}/[0-9a-z-]+$'
        else:
            pattern = r'^/.users/[0-9a-z-]+:/.backends/[0-9a-z-]+/[0-9a-z-]+$'

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
                                        remount: bool = False):
        """
        Prepare parameters for the control client to mount a container

        Args:
            container (Container): the container to be mounted storages List(Storage): the storage
            selected for container user_paths: paths to the owner, should include ``/`` for default
            user unique_path_only: mount only under internal unique path
            (``/.backends/{container_uuid}/{backend_id}``) remount: remount if mounted already
            (otherwise, will fail if mounted already)
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

        return {
            'paths': [str(p) for p in mount_paths],
            'storage': storage.params,
            'extra': {
                'tag': self.get_storage_tag(mount_paths, storage.params),
                'primary': storage.is_primary,
                'trusted_owner': trusted_owner,
                'subcontainer_of': (f'{subcontainer_of.owner}:{subcontainer_of.paths[0]}'
                                    if subcontainer_of else None),
            },
            'remount': remount,
        }

    @staticmethod
    def join_bridge_paths_for_mount(bridges: Iterable[PurePosixPath], path: PurePosixPath)\
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
            ':'.join(
                str(p).replace(':', '_')
                for p in itertools.chain(bridges, [path])
            )
        )

    def get_storage_mount_paths(self, container: Container, storage: Storage,
                                user_paths: Iterable[Iterable[PurePosixPath]])\
            -> List[PurePosixPath]:
        """
        Return all mount paths (incl. synthetic ones) for given storage.

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

    def get_primary_unique_mount_path(self, container: Container, storage: Storage):
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
        return self.get_user_path(owner + ":") / path.relative_to('/')

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
