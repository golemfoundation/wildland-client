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
    def control_hello(self, handler):
        return 'hello world'

    @control_command('test-args')
    def control_test_args(self, handler, test_arg):
        return test_arg

    @control_command('boom')
    def control_boom(self, handler):
        raise ValueError('boom')

    @control_command('send-event')
    def control_event(self, handler):
        handler.send_event('this is event')
        return 'this is result'


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


@pytest.fixture
def conn(server, socket_path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.connect(str(socket_path))
        yield conn


def test_server_simple_command(conn):
    conn.sendall(json.dumps({'cmd': 'hello'}).encode())
    conn.sendall(b'\n\n')

    response_bytes = conn.recv(1024)
    assert response_bytes.endswith(b'\n\n')
    response = json.loads(response_bytes)
    assert response == {'result': 'hello world'}


def test_server_request_id(conn):
    conn.sendall(json.dumps({'cmd': 'hello', 'id': 123}).encode())
    conn.sendall(b'\n\n')

    response = json.loads(conn.recv(1024))
    assert response == {'result': 'hello world', 'id': 123}


def test_server_argument(conn):
    conn.sendall(json.dumps({'cmd': 'test-args', 'args': {'test-arg': 123}}).encode())
    conn.sendall(b'\n\n')

    response = json.loads(conn.recv(1024))
    assert response == {'result': 123}


def test_server_events(conn):
    conn.sendall(json.dumps({'cmd': 'send-event'}).encode())
    conn.sendall(b'\n\n')

    connfile = conn.makefile()

    expected_responses = [
        {'event': 'this is event'},
        {'result': 'this is result'}
    ]

    for expected_response in expected_responses:
        lines = []
        for line in connfile:
            lines.append(line)
            if line == '\n':
                break
        received_response = json.loads(''.join(lines))
        assert received_response == expected_response


def test_server_eof(conn):
    conn.sendall(json.dumps({'cmd': 'hello'}).encode())
    conn.shutdown(socket.SHUT_WR)

    response = json.loads(conn.recv(1024))
    assert response == {'result': 'hello world'}


def test_server_error(conn):
    conn.sendall(b'malformed\n\n')

    response = json.loads(conn.recv(1024))
    assert response['error']['class'] == 'ControlRequestError'

    conn.sendall(json.dumps({'cmd': 'boom', 'id': 123}).encode())
    conn.sendall(b'\n\n')

    response = json.loads(conn.recv(1024))
    assert response['error']['class'] == 'ValueError'
    assert response['error']['desc'] == 'boom'
    assert response['id'] == 123


def test_control_client(client: ControlClient):
    assert client.run_command('hello') == 'hello world'
    assert client.run_command('test-args', test_arg=123) == 123

    assert client.run_command('send-event') == 'this is result'
    assert client.wait_for_events() == ['this is event']


def test_control_client_error(client: ControlClient):
    with pytest.raises(ControlClientError, match='ValueError: boom'):
        client.run_command('boom')
