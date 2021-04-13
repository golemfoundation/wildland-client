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
Socket server for controlling Wildland FS.
"""

from pathlib import Path
import logging
import threading
from socketserver import ThreadingMixIn, UnixStreamServer, BaseRequestHandler
from contextlib import closing
import json
from typing import Dict, Callable
import socket

logger = logging.getLogger('control-server')


def control_command(name):
    """
    A decorator for a server command, using JSON for arguments and result.

    The function parameters will be used by name, converting underscores to
    dashes, so that 'container_id' in Python will correspond to 'container-id'
    in JSON.

    Example:

        @command('get-manifest')
        def control_get_manifest(handler, container_id):
            return [...]

    This will correspond to a command taking the following JSON request:

        {"cmd": "get-manifest", "args": {"container-id": ...}}
    """

    def _wrapper(func):
        func._control_name = name  # pylint: disable=protected-access
        return func

    return _wrapper


class ControlHandler(BaseRequestHandler):
    """
    A class that handles a single client connection.
    """

    def __init__(self, request, client_address, server):
        self.commands = server.commands
        self.validators = server.validators
        self.lock = threading.Lock()
        self.close_handlers = []

        # Apparently this calls handle() already.
        super().__init__(request, client_address, server)

    def on_close(self, close_handler):
        """
        Register a callback to be called when the connection is finished.
        """

        self.close_handlers.append(close_handler)

    def send_event(self, event):
        """
        Send an asynchronous event to the user. Connection errors will be
        ignored, because the connection might be closed already.
        """

        try:
            self._send_message({'event': event})
        except IOError:
            logger.exception('error while sending event')

    def handle(self):
        try:
            with closing(self.request.makefile()) as f:
                lines = []
                for line in f:
                    lines.append(line)
                    if line == '\n':
                        request = ''.join(lines)
                        if request.strip() != '':
                            lines.clear()
                            self._handle_request(request)

                # The last request can end with EOF instead of separator.
                request = ''.join(lines)
                if request.strip() != '':
                    self._handle_request(request)
        finally:
            with self.lock:
                self.request.close()
            for close_handler in self.close_handlers:
                close_handler()

    def _send_message(self, message):
        message_bytes = json.dumps(message, indent=2).encode() + b'\n\n'
        with self.lock:
            self.request.sendall(message_bytes)

    def _handle_request(self, request_str: str):
        request = None
        try:
            request = json.loads(request_str)

            assert isinstance(request, dict), 'expecting a dictionary'
            assert 'cmd' in request, 'expecting "cmd" key'

            cmd = request['cmd']
            assert cmd in self.commands, f'unknown command: {cmd}'

            args = request.get('args') or {}
            if self.validators is not None:
                assert cmd in self.validators, f'no validator for command: {cmd}'
                validator = self.validators[cmd]
                validator(args)

            args = {key.replace('-', '_'): value for key, value in args.items()}

            result = self.commands[cmd](self, **args)

            response = {'result': result}
            logger.debug('%r -> %r', request, result)
        except Exception as e:
            logger.exception('error when handling: %r', request or request_str)
            response = {'error': {'class': type(e).__name__, 'desc': str(e)}}

        if request and 'id' in request:
            response['id'] = request['id']

        self._send_message(response)


class SocketServer(ThreadingMixIn, UnixStreamServer):
    # pylint: disable=missing-class-docstring
    pass


class ControlServer:
    """
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

        {"cmd": "<name>", "args": {<arguments>}, "id": 10}

    The "args" is an optional dictionary of command arguments, and "id" is an
    optional request token (if present, it will be included in response).

    The response format is:

        {"result": <result>, "id": 10}

    In case of error:

        {"error": {"class": "<class>", "desc": "<description>"}, "id": 10}
    """

    def __init__(self):
        self.socket_server = None
        self.server_thread = None
        self.commands = {}
        self.validators = None

    def register_commands(self, obj):
        """
        Register object methods decorated with @control_command.
        """

        for attr in dir(obj):
            val = getattr(obj, attr)
            name = getattr(val, '_control_name', None)
            if name is not None:
                self.commands[name] = val

    def register_validators(self, validators: Dict[str, Callable]):
        """
        Register a dictionary of schemas to be checked. For a command ``cmd``
        with arguments ``args``, the server will call
        ``validators[cmd](args)``.
        """

        self.validators = validators

    def start(self, path: Path):
        """
        Start listening on a provided path.
        """

        logger.info('starting server at %s', path)
        if path.exists():
            path.unlink()
        self.socket_server = SocketServer(str(path), ControlHandler)
        # pylint: disable=attribute-defined-outside-init
        self.socket_server.commands = self.commands  # type: ignore
        self.socket_server.validators = self.validators  # type: ignore

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
        """
        Shut down the server, closing existing connections.
        """

        assert self.socket_server
        assert self.server_thread

        logger.info('stopping server')
        # TODO: there is a possible deadlock if we call shutdown() while the
        # server is not inside serve_forever() loop
        if self.server_thread.is_alive():
            self.socket_server.shutdown()
            self.server_thread.join()

        # Close connection for all threads and wait for them
        for thread in self.socket_server._threads:  # pylint: disable=protected-access
            if thread.ident is None:
                # Not started yet
                continue

            # Stopped threads do not have _args anymore
            args = getattr(thread, '_args', None)
            if args:
                request = args[0]
                try:
                    request.shutdown(socket.SHUT_RDWR)
                    request.close()
                except OSError:
                    # already shut down
                    pass
            thread.join()

        self.socket_server = None
        self.server_thread = None
