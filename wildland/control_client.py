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
Client class for the control server
"""

from pathlib import Path
import socket
import json
import logging
from typing import Optional, List, Iterator

from .exc import WildlandError
from .control_server import ControlRequest

logger = logging.getLogger('control-server')


class ControlClientError(WildlandError):
    """
    An error originating from the control server.
    """


class ControlClient:
    """
    A client for ControlServer.
    """

    def __init__(self):
        self.conn = None
        self.conn_file = None
        self.pending_events = []
        self.id_counter = 1

    def connect(self, path: Path):
        """
        Connect to a server listening under a given socket path.
        """

        self.conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.conn.connect(str(path))
        self.conn_file = self.conn.makefile()

    def disconnect(self):
        """
        Disconnect from server.
        """

        assert self.conn
        assert self.conn_file

        self.conn_file.close()
        self.conn_file = None
        self.conn.close()
        self.conn = None

    def run_command(self, name, **kwargs):
        """
        Run a command with given name and (named) arguments. The argument names
        will be converted to a proper format ('container_id' -> 'container-id').

        Returns a result, or raises ControlClientError if the server reported
        an error.
        """

        assert self.conn
        assert self.conn_file

        request = ControlRequest(cmd=name, args=kwargs, request_id=self.id_counter)
        logger.debug('cmd: %s', request)
        self.conn.sendall(json.dumps(request.raw()).encode() + b'\n\n')

        self.id_counter += 1

        response = None
        while response is None:
            message = self._recv_message()
            if message is None:
                raise ControlClientError('No response from the server')
            if 'event' in message:
                logger.debug('event (pending): %s', message['event'])
                self.pending_events.append(message['event'])
            else:
                response = message

        response_id = response.get('id')
        if response_id != request.id:
            raise ControlClientError(
                f'Wrong response ID: expected {request.id}, got {response_id}')

        if 'error' in response:
            error_class = response['error']['class']
            error_desc = response['error']['desc']

            logger.debug('%s -> %s: %s', name, error_class, error_desc)
            raise ControlClientError(f'{error_class}: {error_desc}')

        logger.debug('%s -> %s', name, response['result'])
        return response['result']

    def wait_for_events(self) -> List[dict]:
        """
        Wait for the server to send events (or return pending events).

        Empty list means the connection has been closed.
        """

        if self.pending_events:
            events = self.pending_events
            self.pending_events = []
            return events

        message = self._recv_message()
        if not message:
            return []
        if 'event' not in message:
            raise ControlClientError(f'Unexpected message: {message}')
        logger.debug('event: %s', message['event'])
        return [message['event']]

    def iter_events(self) -> Iterator[dict]:
        """
        Iterate over events from server.
        """

        while True:
            events = self.wait_for_events()
            if not events:
                break
            yield from events

    def _recv_message(self) -> Optional[dict]:
        """
        Receive a message from the server. Returns None on EOF.
        """

        assert self.conn_file

        lines = []
        for line in self.conn_file:
            lines.append(line)
            if line == '\n':
                break
        # TODO: this doesn't distinguish empty lines from EOF
        # (in case of empty lines, we should raise an error).
        response_str = ''.join(lines)
        if response_str.strip() == '':
            return None

        return json.loads(response_str)
