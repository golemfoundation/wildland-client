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
Client class for the control server
'''

from pathlib import Path
import socket
import json
import logging

from .exc import WildlandError

logger = logging.getLogger('control-server')


class ControlClientError(WildlandError):
    '''
    An error originating from the control server.
    '''


class ControlClient:
    '''
    A client for ControlServer.
    '''

    def __init__(self):
        self.conn = None
        self.conn_file = None

    def connect(self, path: Path):
        '''
        Connect to a server listening under a given socket path.
        '''

        self.conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.conn.connect(str(path))
        self.conn_file = self.conn.makefile()

    def disconnect(self):
        '''
        Disconnect from server.
        '''

        assert self.conn
        assert self.conn_file

        self.conn_file.close()
        self.conn_file = None
        self.conn.close()
        self.conn = None

    def run_command(self, name, **kwargs):
        '''
        Run a command with given name and (named) arguments. The argument names
        will be converted to a proper format ('container_id' -> 'container-id').

        Returns a result, or raises ControlClientError if the server reported
        an error.
        '''

        assert self.conn
        assert self.conn_file

        args = {key.replace('_', '-'): value for key, value in kwargs.items()}
        request = {'cmd': name, 'args': args}
        logger.debug('cmd: %s', request)
        self.conn.sendall(json.dumps(request).encode() + b'\n\n')

        lines = []
        for line in self.conn_file:
            lines.append(line)
            if line == '\n':
                break
        response_str = ''.join(lines)
        if response_str.strip() == '':
            raise ControlClientError('Empty response from server')

        response = json.loads(response_str)

        if 'error' in response:
            error_class = response['error']['class']
            error_desc = response['error']['desc']

            raise ControlClientError(f'{error_class}: {error_desc}')

        return response['result']
