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
Socket server for controlling Wildland FS.
'''

from pathlib import Path
import logging
import threading
from socketserver import ThreadingMixIn, UnixStreamServer, BaseRequestHandler
from contextlib import closing
import json

logger = logging.getLogger('control-server')


def control_command(name):
    '''
    A decorator for a server command, using JSON for arguments and result.

    The function parameters will be used by name, converting underscores to
    dashes, so that 'container_id' in Python will correspond to 'container-id'
    in JSON.

    Example:

        @command('get-manifest')
        def control_get_manifest(container_id):
            return [...]

    This will correspond to a command taking the following JSON request:

        {"cmd": "get-manifest", "args": {"container-id": ...}}
    '''

    def _wrapper(func):
        func._control_name = name
        return func

    return _wrapper


class RequestHandler(BaseRequestHandler):
    '''
    A glue class to proxy the requests back to our ControlServer class.
    '''

    def handle(self):
        self.server.control_handle(self.request)  # type: ignore


class SocketServer(ThreadingMixIn, UnixStreamServer):
    # pylint: disable=missing-class-docstring
    pass


class ControlServer:
    '''
    A JSON-based socket server.

    Usage:

        server = ControlServer()
        server.register_commands(obj)
        server.start()
        ...
        server.stop()

    The server handles JSON requests and responds with JSON responses.
    The requests and responses are separated by an empty line ('\n\n').

    The request format is (TODO: request IDs):

        {"cmd": "<name>", "args": {<arguments>}}

    The "args" is an optional dictionary of command arguments.

    The response format is:

        {"result": <result>}

    In case of error:

        {"error": {"class": "<class>", "desc": "<description>"}}
    '''

    def __init__(self):
        self.socket_server = None
        self.server_thread = None
        self.commands = {}

    def register_commands(self, obj):
        '''
        Register object methods decorated with @control_command.
        '''

        for attr in dir(obj):
            val = getattr(obj, attr)
            name = getattr(val, '_control_name', None)
            if name is not None:
                self.commands[name] = val

    def start(self, path: Path):
        '''
        Start listening on a provided path.
        '''

        logger.info('starting server at %s', path)
        if path.exists():
            path.unlink()
        self.socket_server = SocketServer(str(path), RequestHandler)
        # pylint: disable=attribute-defined-outside-init
        self.socket_server.control_handle = self._handle_connection  # type: ignore

        self.server_thread = threading.Thread(
            name='control-server',
            target=self._serve_forever)
        self.server_thread.start()

    def _serve_forever(self):
        assert self.socket_server
        logger.debug('serve_forever')
        try:
            self.socket_server.serve_forever()
        except Exception:
            logger.exception('error in server main thread')

    def stop(self):
        '''
        Shut down the server. Will wait for all connections to finish.
        '''

        assert self.socket_server
        assert self.server_thread

        logger.info('stopping server')
        # TODO: there is a possible deadlock if we call shutdown() while the
        # server is not inside serve_forever() loop
        if self.server_thread.is_alive():
            self.socket_server.shutdown()
            self.server_thread.join()

        self.socket_server = None
        self.server_thread = None

    def _handle_connection(self, conn):
        try:
            with closing(conn), closing(conn.makefile()) as f:
                lines = []
                for line in f:
                    lines.append(line)
                    if line == '\n':
                        request = ''.join(lines)
                        if request.strip() != '':
                            lines.clear()
                            response = self._handle_request(request)
                            conn.sendall(response.encode())

                # The last request can end with EOF instead of separator.
                request = ''.join(lines)
                if request.strip() != '':
                    response = self._handle_request(request)
                    conn.sendall(response.encode())
        except Exception:
            logger.exception('error in connection handler')

    def _handle_request(self, request_str: str) -> str:
        request = None
        try:
            request = json.loads(request_str)

            assert isinstance(request, dict), 'expecting a dictionary'
            assert 'cmd' in request, 'expecting "cmd" key'

            cmd = request['cmd']
            assert cmd in self.commands, f'unknown command: {cmd}'

            args = request.get('args') or {}
            args = {key.replace('-', '_'): value for key, value in args.items()}

            result = self.commands[cmd](**args)

            response = {'result': result}
            logger.debug('%r -> %r', request, result)
        except Exception as e:
            logger.exception('error when handling: %r', request or request_str)
            response = {'error': {'class': type(e).__name__, 'desc': str(e)}}

        return json.dumps(response, indent=2) + '\n\n'
