# Wildland Project
#
# Copyright (C) 2020 Golem Foundation
#
# Authors:
#                         Rafal Wojdyla <omeg@invisiblethingslab.com>,
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
Wildland sync daemon.
"""
import logging
import signal
import threading

from pathlib import Path, PurePosixPath
from threading import Lock
from typing import List, Optional, Dict

import click

from wildland.client import Client
from wildland.config import Config
from wildland.exc import WildlandError
from wildland.hashdb import HashDb
from wildland.log import init_logging
from wildland.control_server import ControlServer, control_command
from wildland.manifest.schema import Schema
from wildland.storage import Storage
from wildland.storage_backends.base import StorageBackend, OptionalError
from wildland.storage_sync.base import BaseSyncer
from wildland.wildland_object.wildland_object import WildlandObject

logger = logging.getLogger('sync-daemon')

DEFAULT_LOG_PATH = '/tmp/wl-sync.log'


class SyncJob:
    """
    Encapsulates a thread containing a syncer.
    """
    def __init__(self, container_name: str, syncer: BaseSyncer, source: StorageBackend,
                 target: StorageBackend, continuous: bool, unidirectional: bool):
        self.syncer = syncer
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._worker, args=(self,))
        self.container_name = container_name
        self.source = source
        self.target = target
        self.continuous = continuous
        self.unidirectional = unidirectional
        self.error: Optional[str] = None

    def start(self):
        """
        Starts the worker thread.
        """
        self.thread.start()

    def stop(self):
        """
        Signals the worker thread to stop and waits until it does.
        """
        self.stop_event.set()
        self.thread.join()

    def status(self) -> str:
        """
        Status of this sync job.
        """
        try:
            if self.syncer.is_running():
                running = 'RUNNING '
            else:
                running = 'IDLE '
        except OptionalError:
            running = ' '

        ret = f'{self.container_name} {running}{str(self.source)} ' \
              f'{"->" if self.unidirectional else "<->"} {str(self.target)}'
        if not self.continuous:
            ret += ' [one-shot]'

        try:
            if self.syncer.is_synced():
                ret += ' [SYNCED]'
            else:
                ret += ' [NOT SYNCED]'
        except OptionalError:
            pass

        errors = list(self.syncer.iter_errors())
        if len(errors) > 0:
            for e in errors:
                ret += f'\n   {e}'

        if self.error:
            ret += f'\n   [!] {self.error}'
        return ret

    @staticmethod
    def _worker(job: 'SyncJob'):
        """
        Function for the worker thread.
        """
        try:
            job.syncer.start_sync()
            job.stop_event.wait()
        except Exception as ex:
            logger.exception('Exception:')
            job.error = f'Error: {ex}'
        finally:
            job.syncer.stop_sync()


def _get_storage_by_id_or_type(id_or_type: str, storages: List[Storage]) -> Storage:
    """
    Helper function to find a storage by listed id or type.
    """
    try:
        return [storage for storage in storages
                if id_or_type in (storage.backend_id, storage.params['type'])][0]
    except IndexError:
        # pylint: disable=raise-missing-from
        raise WildlandError(f'Storage {id_or_type} not found')


class SyncDaemon:
    """
    Daemon for processing storage sync requests.
    """
    def __init__(self, base_dir: Optional[str] = None, socket_path: Optional[str] = None,
                 log_path: Optional[str] = None):
        self.lock = Lock()
        self.jobs: Dict[str, SyncJob] = dict()
        self.log_path = log_path
        self.base_dir = PurePosixPath(base_dir) if base_dir else None

        if socket_path:
            self.socket_path = Path(socket_path)
        else:
            config = Config.load(base_dir)
            self.socket_path = Path(config.get('sync-socket-path'))

        self.control_server = ControlServer()
        self.control_server.register_commands(self)

        command_schemas = Schema.load_dict('sync-commands.json', 'args')
        self.control_server.register_validators({
            cmd: schema.validate for cmd, schema in command_schemas.items()
        })

    def start_sync(self, container_name: str, continuous: bool, unidirectional: bool,
                   source: Optional[str] = None, target: Optional[str] = None) -> str:
        """
        Start syncing storages, or do a one-shot sync.

        :param container_name: Name of the container to sync (can be anything that
                               `client.load_object_from_name()` supports).
        :param continuous: If true, sync in a worker thread until explicitly stopped.
        :param unidirectional: If true, only sync from `source` to `target`.
        :param source: Source storage (UUID or storage type). Uses primary storage if not present.
        :param target: Target storage (UUID or storage type). Uses default remote for
                       the container if not present.
        :return: Response message.
        """
        client = Client(base_dir=self.base_dir)
        container = client.load_object_from_name(WildlandObject.Type.CONTAINER, container_name)

        all_storages = list(client.all_storages(container))

        if source:
            source_storage = _get_storage_by_id_or_type(source, all_storages)
        else:
            try:
                source_storage = [storage for storage in all_storages
                                  if client.is_local_storage(storage.params['type'])][0]
            except IndexError:
                # pylint: disable=raise-missing-from
                raise WildlandError('No local storage backend found')

        source_backend = StorageBackend.from_params(source_storage.params)

        default_remotes = client.config.get('default-remote-for-container')

        if target:
            target_storage = _get_storage_by_id_or_type(target, all_storages)
            default_remotes[container.uuid] = target_storage.backend_id
            client.config.update_and_save({'default-remote-for-container': default_remotes})
        else:
            target_remote_id = default_remotes.get(container.uuid, None)
            try:
                target_storage = [storage for storage in all_storages
                                 if target_remote_id == storage.backend_id
                                 or (not target_remote_id and
                                     not client.is_local_storage(storage.params['type']))][0]
            except IndexError:
                # pylint: disable=raise-missing-from
                raise WildlandError('No remote storage backend found: specify --target-storage.')

        target_backend = StorageBackend.from_params(target_storage.params)

        sync_id = container.uuid  # this might also be derived from source and target storages
        with self.lock:
            if sync_id in self.jobs.keys():
                raise WildlandError("Sync process for this container is already running; use "
                                    "stop-sync to stop it.")

            response = f'Using remote backend {target_backend.backend_id} ' \
                       f'of type {target_backend.TYPE}'

            # Store information about container/backend mappings
            hash_db = HashDb(client.config.base_dir)
            hash_db.update_storages_for_containers(container.uuid, [source_backend, target_backend])

            if container.local_path:
                container_path = PurePosixPath(container.local_path)
                container_name = container_name or \
                                 container_path.name.replace(''.join(container_path.suffixes), '')

            source_backend.set_config_dir(client.config.base_dir)
            target_backend.set_config_dir(client.config.base_dir)
            syncer = BaseSyncer.from_storages(source_storage=source_backend,
                                              target_storage=target_backend,
                                              log_prefix=f'Container: {container_name}',
                                              one_shot=not continuous, continuous=continuous,
                                              unidirectional=unidirectional,
                                              can_require_mount=False)

            if not continuous:
                # consider running in a thread and async completion, the process can take a while
                syncer.one_shot_sync()
            else:
                self.jobs[sync_id] = SyncJob(container_name, syncer, source_backend,
                                             target_backend, continuous, unidirectional)
                self.jobs[sync_id].start()

        return response

    def stop_sync(self, container_name: str) -> str:
        """
        Stop syncing storages.

        :param container_name: Name of the container to stop sync (can be anything that
                               `client.load_object_from_name()` supports).
        :return: Response message.
        """
        client = Client(base_dir=self.base_dir)
        container = client.load_object_from_name(WildlandObject.Type.CONTAINER, container_name)
        with self.lock:
            try:
                sync_thread = self.jobs[container.uuid]
                sync_thread.stop()
                self.jobs.pop(container.uuid)
            except KeyError:
                # pylint: disable=raise-missing-from
                raise WildlandError(f'Sync for container {container_name} is not running')
        return f'Sync for container {container_name} stopped'

    @control_command('start')
    def control_start(self, _handler, container: str, continuous: bool, unidirectional: bool,
                      source: Optional[str] = None, target: Optional[str] = None) -> str:
        """
        Start syncing storages, or do a one-shot sync.
        """
        return self.start_sync(container, continuous, unidirectional, source, target)

    @control_command('stop')
    def control_stop(self, _handler, container: str) -> str:
        """
        Stop syncing storages.
        """
        return self.stop_sync(container)

    @control_command('status')
    def control_status(self, _handler) -> List[str]:
        """
        Return a list of currently running sync jobs with their status.
        """
        with self.lock:
            ret = [x.status() for x in self.jobs.values()]

        return ret

    # pylint: disable=unused-argument
    def stop(self, signalnum, frame):
        """
        Stop all sync jobs and exit.
        """
        logger.info('stopping')
        with self.lock:
            for job in self.jobs.values():
                job.stop()

        self.control_server.stop()

    def main(self):
        """
        Main server loop.
        """
        self.init_logging()
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.control_server.start(self.socket_path)
        # main thread exiting seems to cause weird errors in the S3 plugin in other threads
        # (see issue #517)
        assert self.control_server.server_thread
        self.control_server.server_thread.join()

    def init_logging(self):
        """
        Configure logging module.
        """
        log_path = self.log_path or DEFAULT_LOG_PATH
        if log_path == '-':
            init_logging(console=True)
        else:
            init_logging(console=False, file_path=log_path)


@click.command()
@click.option('-l', '--log-path', help=f'path to log file (default: {DEFAULT_LOG_PATH})')
@click.option('-s', '--socket-path', help='path to control socket')
@click.option('-b', '--base-dir', help='base directory for configuration')
def main(log_path, socket_path, base_dir):
    """
    Entry point.
    """
    server = SyncDaemon(base_dir, socket_path, log_path)
    server.main()


# pylint: disable=no-value-for-parameter
if __name__ == '__main__':
    main()
