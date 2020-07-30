
from pathlib import PurePosixPath
import logging
import threading
from socketserver import ThreadingMixIn, UnixStreamServer, BaseRequestHandler
import os
from contextlib import closing
import json

logger = logging.getLogger('control-server')


class RequestHandler(BaseRequestHandler):
    def handle(self):
        self.server.control_handle(self.request)  # type: ignore


class SocketServer(ThreadingMixIn, UnixStreamServer):
    # pytest: disable=mis
    pass


class ControlServer:
    def __init__(self, fs):
        self.fs = fs
        self.socket_server = None
        self.server_thread = None

    def start(self, path):
        logger.info('starting server at %s', path)
        os.unlink(path)
        self.socket_server = SocketServer(path, RequestHandler)
        # pylint: disable=attribute-defined-outside-init
        self.socket_server.control_handle = self.handle_connection  # type: ignore

        self.server_thread = threading.Thread(
            name='control-server',
            target=self.serve_forever)
        self.server_thread.start()

    def serve_forever(self):
        assert self.socket_server
        try:
            self.socket_server.serve_forever()
        except Exception:
            logger.exception('error in server main thread')

    def stop(self):
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

    def handle_connection(self, conn):
        try:
            with closing(conn), closing(conn.makefile()) as f:
                lines = []
                for line in f:
                    lines.append(line)
                    if line == '\n':
                        request_str = ''.join(lines)
                        if request_str.strip() != '':
                            request = json.loads(request_str)
                            lines.clear()
                            response = self.handle_request(request)
                            conn.sendall((json.dumps(response)+'\n\n').encode())
        except Exception:
            logger.exception('error in connection handler')

    def handle_request(self, request):
        try:
            assert 'path' in request
            path = PurePosixPath(request['path'])
            node = self.find_node(path.parts, self.fs)

            if 'arg' in request:
                assert node._control_write, f'{path} is not writable'
                result = node(request['arg'])
            else:
                assert node._control_read, f'{path} is not readable'
                result = node()

            if isinstance(result, bytes):
                result = result.decode()

            response = {'result': result}
            logger.debug('%r -> %r', request, result)
            return response
        except Exception as e:
            logger.exception('error when handling: %r', request)
            return {'error': str(e)}

    @staticmethod
    def find_node(parts, obj):
        for part in parts:
            next_obj = None
            if hasattr(obj, '_control_directory'):
                for name, sub_obj in obj():
                    if name == part:
                        next_obj = sub_obj
                        break
            else:
                for attr in dir(obj):
                    attr = getattr(obj, attr)
                    if getattr(attr, '_control_name', None) == part:
                        next_obj = attr
                        break

            if next_obj is None:
                raise ValueError(f'cannot find {part} in {obj!r}')
            obj = next_obj

        return obj
