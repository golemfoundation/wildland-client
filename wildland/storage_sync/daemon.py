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
from queue import Queue
from typing import List, Optional, Dict, Tuple, Set

import click

from wildland.config import Config
from wildland.exc import WildlandError
from wildland.hashdb import HashDb
from wildland.log import init_logging
from wildland.control_server import ControlServer, control_command, ControlHandler
from wildland.manifest.schema import Schema
from wildland.storage_backends.base import StorageBackend, OptionalError
from wildland.storage_backends.watch import FileEvent
from wildland.storage_sync.base import BaseSyncer, SyncState, SyncEvent, SyncStateEvent, \
    SyncConflictEvent, SyncErrorEvent, SyncProgressEvent
from wildland.log import get_logger

logger = get_logger('sync-daemon')

LOG_ENV_NAME = 'WL_SYNC_LOG_PATH'  # environmental variable with log path override
DEFAULT_LOG_PATH = f"{os.path.expanduser('~')}/.local/share/wildland/wl-sync.log"


class SyncJob:
    """
    Encapsulates a worker containing a syncer.
    """
    def __init__(self, job_id: str, container_name: str, syncer: BaseSyncer, source: StorageBackend,
                 target: StorageBackend, continuous: bool, unidirectional: bool,
                 event_queue: Queue, control_handler: ControlHandler):
        self.syncer = syncer
        self.stop_event = threading.Event()
        self.test_error = False
        self.worker = threading.Thread(target=self._worker)
        self.container_name = container_name
        self.source = source
        self.target = target
        self.continuous = continuous
        self.unidirectional = unidirectional
        self.event_queue = event_queue
        self.job_id = job_id
        self.control_handler = control_handler
        # daemon manages fields below because they come from the event queue
        self._state = SyncState.STOPPED
        self._current_item: Optional[FileEvent] = None
        self._conflicts: List[str] = []
        self._error: Optional[str] = None

    @property
    def state(self) -> SyncState:
        """State getter."""
        return self._state

    @state.setter
    def state(self, value: SyncState):
        """State setter."""
        self._state = value

    @property
    def conflicts(self) -> List[str]:
        """Conflicts getter."""
        return self._conflicts

    def add_conflict(self, conflict: str):
        """Add a conflict to the list of conflicts of this job."""
        self._conflicts.append(conflict)

    @property
    def error(self) -> Optional[str]:
        """Error getter."""
        return self._error

    @error.setter
    def error(self, value: str):
        """Error setter."""
        self._error = value

    @property
    def current_item(self) -> Optional[FileEvent]:
        """Current item (file/directory) being synced."""
        return self._current_item

    @current_item.setter
    def current_item(self, value: FileEvent):
        """Current item setter."""
        self._current_item = value

    def start(self):
        """
        Starts the worker.
        """
        self.worker.start()

    def stop(self):
        """
        Signals the worker to stop and waits until it does.
        """
        if self.continuous:
            self.stop_event.set()

        # TODO: one-shot sync is not interruptible currently, there's no safe way to abort
        # see issue #580
        self.worker.join()

    def cause_error(self):
        """
        Cause an exception in the sync worker (for test purposes).
        The exception is WildlandError('Test sync exception')
        """
        assert self.continuous
        self.test_error = True
        self.stop()

    def status(self) -> str:
        """
        Status of this sync job as human-readable string.
        """
        ret = f'{self.container_name} {self._state} {str(self.source)} ' \
              f'{"->" if self.unidirectional else "<->"} {str(self.target)}'
        if not self.continuous:
            ret += ' [one-shot]'

        if self.current_item and self.state in [SyncState.RUNNING, SyncState.ONE_SHOT]:
            ret += f'\n   currently syncing: {self.current_item}'

        try:
            if len(self._conflicts) > 0:
                for conflict in self._conflicts:
                    ret += f'\n   {conflict}'
        except OptionalError:
            pass

        if self._error:
            ret += f'\n   [!] {self._error}'

        return ret

    def _event_handler(self, event: SyncEvent, _context=None):
        """
        Callback for syncer events. Runs in the worker subprocess.
        """
        if not event.job_id:
            event.job_id = self.job_id
        self.event_queue.put([self.job_id, event])

    def _worker(self):
        """
        Function for the worker subprocess.
        """
        self.syncer.set_event_callback(self._event_handler)
        try:
            if self.continuous:
                self.syncer.start_sync()
                self.stop_event.wait()
                if self.test_error:
                    raise WildlandError('Test sync exception')
            else:
                self.syncer.one_shot_sync(self.unidirectional)
        except Exception as ex:
            logger.exception('Sync worker exception:')
            self._event_handler(SyncErrorEvent(str(ex)))
            self._event_handler(SyncStateEvent(SyncState.ERROR))
            # syncer didn't catch the exception so it didn't update its state
            self.syncer.state = SyncState.ERROR
        finally:
            if self.continuous:
                self.syncer.stop_sync()
            # signal that worker is finished to not lose any events in the daemon thread
            # we don't use STOPPED event because it doesn't mean the syncer is stopped permanently
            self.event_queue.put([self.job_id, None])


class SyncDaemon:
    """
    Daemon for processing storage sync requests.
    """
    def __init__(self, base_dir: Optional[str] = None, socket_path: Optional[str] = None,
                 log_path: Optional[str] = None):
        self.lock = threading.Lock()
        self.jobs: Dict[str, SyncJob] = dict()
        self.log_path = log_path
        self.base_dir = PurePosixPath(base_dir) if base_dir else None

        config = Config.load(base_dir)
        self.base_dir = config.base_dir

        if socket_path:
            self.socket_path = Path(socket_path)
        else:
            self.socket_path = Path(config.get('sync-socket-path'))

        self.event_queue: Queue = Queue()
        self.event_thread = threading.Thread(target=self._event_thread_proc, daemon=True)
        self.event_thread.name = 'events'

        # these are jobs queued for removal from the event thread
        self.stop_queue: Set[str] = set()
        self.stop_event = threading.Event()

        self.control_server = ControlServer()
        self.control_server.register_commands(self)

        command_schemas = Schema.load_dict('sync-commands.json', 'args')
        self.control_server.register_validators({
            cmd: schema.validate for cmd, schema in command_schemas.items()
        })

    def _event_thread_proc(self):
        """
        Thread for receiving syncer events.
        """
        while True:
            try:
                job_id, event = self.event_queue.get(block=True)
            except Exception:
                logger.exception('event exception:')
                break

            try:
                job = self.jobs[job_id]
                if not event:  # worker finished
                    logger.debug('Sync event (%s): worker finished', job_id)
                    if job.continuous:
                        # signal the main thread that it's safe to return from stop command
                        # otherwise we get a race condition
                        self.stop_queue.add(job_id)
                        self.stop_event.set()
                    continue

                logger.debug('Sync event (%s): %s', job_id, event)
                if isinstance(event, SyncStateEvent):
                    job.state = event.state
                elif isinstance(event, SyncProgressEvent):
                    job.current_item = FileEvent(event.event_type, event.path)
                elif isinstance(event, SyncConflictEvent):
                    job.add_conflict(event.value)
                elif isinstance(event, SyncErrorEvent):
                    job.error = event.value
                else:
                    logger.warning('Unknown event type')

                # notify the client
                job.control_handler.send_event(event.toJSON())
            except KeyError:  # nonexistent job, shouldn't happen
                logger.warning("Event %s not delivered, unknown job %s", event, job_id)
            except Exception as e:
                logger.exception(e)
        logger.debug('Event thread exiting')

    def start_sync(self, container_name: str, job_id: str, continuous: bool, unidirectional: bool,
                   source: dict, target: dict, active_events: List[str],
                   control_handler: ControlHandler) -> str:
        """
        Start syncing storages, or do a one-shot sync.

        :param container_name: Name of the container (for display purposes only).
        :param job_id: Unique sync job ID, currently 'container_owner|container_uuid'.
        :param continuous: If true, sync in a worker thread until explicitly stopped.
        :param unidirectional: If true, only sync from `source` to `target`.
        :param source: Source storage params.
        :param target: Target storage params.
        :param active_events: List of sync event types to be sent to the notification callback.
                              Empty list means all events.
        :param control_handler: ControlServer's handler to be associated with the job
                                (used to send event notifications).
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

            if not active_events:
                active_events = []
            logger.debug('Setting event filters for %s to %s', job_id, active_events)
            syncer.set_active_events(active_events)
            self.jobs[job_id] = SyncJob(job_id, container_name, syncer, source_backend,
                                        target_backend, continuous, unidirectional,
                                        self.event_queue, control_handler)
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
                job = self.jobs[job_id]
                job.stop()
                if job.continuous:
                    # we wait here to avoid race condition (client thinks that a job
                    # is stopped but we still have it in the jobs list)
                    self.stop_event.wait()
                    self.stop_event.clear()
                    if job_id in self.stop_queue:
                        # we're good, job is clean to remove
                        self.stop_queue.remove(job_id)
                    else:
                        # something very wrong happened
                        raise WildlandError(f'Internal sync error: failed to remove job {job_id}')
                self.jobs.pop(job_id)
            except KeyError:
                # pylint: disable=raise-missing-from
                raise WildlandError(f'Sync for job {job_id} is not running')
        return f'Sync for job {job_id} stopped'

    @control_command('start')
    def control_start(self, handler: ControlHandler, container_name: str, job_id: str,
                      continuous: bool, unidirectional: bool, source: dict, target: dict,
                      **kwargs) -> str:
        """
        Start syncing storages, or do a one-shot sync.
        """
        events: List[str] = kwargs['active-events'] if 'active-events' in kwargs else []
        return self.start_sync(container_name, job_id, continuous, unidirectional, source, target,
                               events, handler)

    @control_command('stop')
    def control_stop(self, _handler, job_id: str) -> str:
        """
        Stop syncing storages.
        """
        return self.stop_sync(job_id)

    @control_command('active-events')
    def control_active_events(self, _handler, job_id: str, active_events: List[str]):
        """
        Set which sync events should be active for a job (empty means all).
        """
        with self.lock:
            try:
                job = self.jobs[job_id]
                logger.debug('Setting event filters for %s to %s', job_id, active_events)
                job.syncer.set_active_events(active_events)
            except KeyError:
                # pylint: disable=raise-missing-from
                raise WildlandError(f'Sync for job {job_id} is not running')

    @control_command('test-error')
    def control_test_error(self, _handler, job_id: str):
        """
        Cause an exception in the specified job (for test purposes).
        The exception is WildlandError('Test sync exception')
        """
        self.jobs[job_id].cause_error()

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

    @control_command('job-state')
    def control_job_state(self, _handler, job_id: str) -> Optional[Tuple[int, str]]:
        """
        Return status of a syncer for the given job.
        """
        with self.lock:
            if job_id in self.jobs.keys():
                job = self.jobs[job_id]
                return job.state.value, job.status()

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
        logger.debug('stopping')
        with self.lock:
            for job in self.jobs.values():
                job.stop()

        # self.event_queue.close()  # so event thread can exit
        self.control_server.stop()

    def main(self):
        """
        Main server loop.
        """
        threading.current_thread().name = 'main'
        self.init_logging()
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

        self.event_thread.start()
        self.control_server.start(self.socket_path)

        # main thread exiting seems to cause weird errors in the S3 plugin in other threads
        # (see issue #517)
        assert self.control_server.server_thread
        self.control_server.server_thread.join()

    def init_logging(self):
        """
        Configure logging module.
        """
        if self.log_path:  # command line param
            log_path = self.log_path
        elif LOG_ENV_NAME in os.environ:
            log_path = os.environ[LOG_ENV_NAME]
        else:
            log_path = DEFAULT_LOG_PATH

        if log_path == '-':
            init_logging(console=True)
        else:
            init_logging(console=False, file_path=log_path)


@click.command()
@click.option('-l', '--log-path', help=f'path to log file (default: {DEFAULT_LOG_PATH}),\n'
                                       f'can be set in {LOG_ENV_NAME} environment variable')
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
