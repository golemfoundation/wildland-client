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

# pylint: disable=missing-docstring,redefined-outer-name, unused-argument

from pathlib import Path
import tempfile
import socket
import json

import pytest

from ..control_server import ControlServer, control_command
from ..control_client import ControlClient, ControlClientError


class TestObj:
    # pylint: disable=no-self-use

    @control_command('hello')
    def control_hello(self):
        return 'hello world'

    @control_command('add')
    def control_add(self, a, b, c=0):
        return a + b + c

    @control_command('test-args')
    def control_test_args(self, test_arg):
        return test_arg

    @control_command('boom')
    def control_boom(self):
        raise ValueError('boom')


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def socket_path(temp_dir):
    return temp_dir / 'server.sock'


@pytest.fixture
def server(socket_path):
    server = ControlServer()
    test = TestObj()
    server.register_commands(test)
    server.start(socket_path)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def client(server, socket_path):
    client = ControlClient()
    client.connect(socket_path)
    try:
        yield client
    finally:
        client.disconnect()


def test_control_server(server, socket_path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(socket_path))

        conn.sendall(json.dumps({'cmd': 'hello'}).encode())
        conn.sendall(b'\n\n')

        response_bytes = conn.recv(1024)
        assert response_bytes.endswith(b'\n\n')
        response = json.loads(response_bytes)
        assert response == {'result': 'hello world'}

        conn.sendall(json.dumps({'cmd': 'test-args', 'args': {'test-arg': 123}}).encode())
        conn.sendall(b'\n\n')

        response = json.loads(conn.recv(1024))
        assert response == {'result': 123}

        conn.sendall(json.dumps({'cmd': 'add', 'args': {'a': 1, 'b': 2}}).encode())
        conn.shutdown(socket.SHUT_WR)

        response = json.loads(conn.recv(1024))
        assert response == {'result': 3}


def test_control_server_error(server, socket_path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(socket_path))

        conn.sendall(b'malformed\n\n')

        response = json.loads(conn.recv(1024))
        assert response['error']['class'] == 'JSONDecodeError'

        conn.sendall(json.dumps({'cmd': 'boom'}).encode())
        conn.sendall(b'\n\n')

        response = json.loads(conn.recv(1024))
        assert response['error']['class'] == 'ValueError'
        assert response['error']['desc'] == 'boom'


def test_control_client(client: ControlClient):
    assert client.run_command('hello') == 'hello world'
    assert client.run_command('add', a=1, b=2) == 3
    assert client.run_command('test-args', test_arg=123) == 123


def test_control_client_error(client: ControlClient):
    with pytest.raises(ControlClientError, match='ValueError: boom'):
        client.run_command('boom')
