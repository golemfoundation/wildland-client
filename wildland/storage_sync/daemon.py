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
import os
import signal
import threading

from pathlib import Path, PurePosixPath
from threading import Lock
from typing import List, Optional, Dict, Tuple

import click

from wildland.config import Config
from wildland.exc import WildlandError
from wildland.hashdb import HashDb
from wildland.log import init_logging
from wildland.control_server import ControlServer, control_command
from wildland.manifest.schema import Schema
from wildland.storage_backends.base import StorageBackend, OptionalError
from wildland.storage_sync.base import BaseSyncer, SyncerStatus
from wildland.log import get_logger

logger = get_logger('sync-daemon')

DEFAULT_LOG_PATH = f"{os.path.expanduser('~')}/.local/share/wildland/wl-fuse.log"


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
        if self.continuous:
            self.stop_event.set()

        # TODO: one-shot sync is not interruptible currently, there's no safe way to abort
        # see issue #580
        self.thread.join()

    def syncer_status(self) -> SyncerStatus:
        """
        Status of this sync job as SyncerStatus.
        """
        if self.error:  # worker thread was interrupted, syncer might not have updated its status
            return SyncerStatus.ERROR

        return self.syncer.status()

    def status(self) -> str:
        """
        Status of this sync job as human-readable string.
        """

        ret = f'{self.container_name} {self.syncer.status()} {str(self.source)} ' \
              f'{"->" if self.unidirectional else "<->"} {str(self.target)}'
        if not self.continuous:
            ret += ' [one-shot]'

        try:
            conflict = list(self.syncer.iter_conflicts())
            if len(conflict) > 0:
                for e in conflict:
                    ret += f'\n   {e}'
        except OptionalError:
            pass

        if self.error:
            ret += f'\n   [!] {self.error}'

        return ret

    @staticmethod
    def _worker(job: 'SyncJob'):
        """
        Function for the worker thread.
        """
        try:
            if job.continuous:
                job.syncer.start_sync()
                job.stop_event.wait()
            else:
                job.syncer.one_shot_sync(job.unidirectional)
        except Exception as ex:
            logger.exception('Exception:')
            job.error = f'Error: {ex}'
        finally:
            if job.continuous:
                job.syncer.stop_sync()


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

        config = Config.load(base_dir)
        self.base_dir = config.base_dir

        if socket_path:
            self.socket_path = Path(socket_path)
        else:
            self.socket_path = Path(config.get('sync-socket-path'))

        self.control_server = ControlServer()
        self.control_server.register_commands(self)

        command_schemas = Schema.load_dict('sync-commands.json', 'args')
        self.control_server.register_validators({
            cmd: schema.validate for cmd, schema in command_schemas.items()
        })

    def start_sync(self, container_name: str, job_id: str, continuous: bool, unidirectional: bool,
                   source: dict, target: dict) -> str:
        """
        Start syncing storages, or do a one-shot sync.

        :param container_name: Name of the container (for display purposes only).
        :param job_id: Unique sync job ID, currently 'container_owner|container_uuid'.
        :param continuous: If true, sync in a worker thread until explicitly stopped.
        :param unidirectional: If true, only sync from `source` to `target`.
        :param source: Source storage params.
        :param target: Target storage params.
        :return: Response message.
        """

        source_backend = StorageBackend.from_params(source)
        target_backend = StorageBackend.from_params(target)

        with self.lock:
            if job_id in self.jobs.keys():
                raise WildlandError("Sync process for this container is already running; use "
                                    "stop-sync to stop it.")

            response = f'Using remote backend {target_backend.backend_id} ' \
                       f'of type {target_backend.TYPE}.'

            # Store information about container/backend mappings
            assert self.base_dir
            hash_db = HashDb(self.base_dir)
            uuid = job_id.split('|')[1]
            hash_db.update_storages_for_containers(uuid, [source_backend, target_backend])

            source_backend.set_config_dir(self.base_dir)  # hashdb location
            target_backend.set_config_dir(self.base_dir)
            syncer = BaseSyncer.from_storages(source_storage=source_backend,
                                              target_storage=target_backend,
                                              log_prefix=f'Container: {container_name}',
                                              one_shot=not continuous, continuous=continuous,
                                              unidirectional=unidirectional,
                                              can_require_mount=False)

            self.jobs[job_id] = SyncJob(container_name, syncer, source_backend,
                                        target_backend, continuous, unidirectional)
            self.jobs[job_id].start()

        return response

    def stop_sync(self, job_id: str) -> str:
        """
        Stop syncing storages if continuous, remove the job from internal state if one-shot.

        :param job_id: Unique sync job ID, currently 'container_owner|container_uuid'.
        :return: Response message.
        """
        with self.lock:
            try:
                sync_job = self.jobs[job_id]
                sync_job.stop()
                self.jobs.pop(job_id)
            except KeyError:
                # pylint: disable=raise-missing-from
                raise WildlandError(f'Sync for job {job_id} is not running')
        return f'Sync for job {job_id} stopped'

    @control_command('start')
    def control_start(self, _handler, container_name: str, job_id: str, continuous: bool,
                      unidirectional: bool, source: dict, target: dict) -> str:
        """
        Start syncing storages, or do a one-shot sync.
        """
        return self.start_sync(container_name, job_id, continuous, unidirectional, source, target)

    @control_command('stop')
    def control_stop(self, _handler, job_id: str) -> str:
        """
        Stop syncing storages.
        """
        return self.stop_sync(job_id)

    @control_command('stop-all')
    def control_stop_all(self, _handler):
        """
        Stop all sync jobs.
        """
        with self.lock:
            for job in self.jobs.values():
                job.stop()
            self.jobs.clear()

    @control_command('status')
    def control_status(self, _handler) -> List[str]:
        """
        Return a list of currently running sync jobs with their status.
        """
        with self.lock:
            ret = [x.status() for x in self.jobs.values()]

        return ret

    @control_command('job-status')
    def control_job_status(self, _handler, job_id: str) -> Optional[Tuple[int, str]]:
        """
        Return status of a syncer for the given job.
        """
        if job_id in self.jobs.keys():
            job = self.jobs[job_id]
            return job.syncer_status().value, job.status()

        return None

    @control_command('shutdown')
    def control_shutdown(self, _handler):
        """
        Stops all sync jobs and shuts down the daemon.
        """
        self.stop(0, None)

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
