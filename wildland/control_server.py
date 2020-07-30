
import logging
import threading
from socketserver import ThreadingMixIn, UnixStreamServer, BaseRequestHandler

logger = logging.getLogger('control-server')


class RequestHandler(BaseRequestHandler):
    def handle(self):
        self.server.control_handle(self.request)  # type: ignore


class SocketServer(ThreadingMixIn, UnixStreamServer):
    # pytest: disable=mis
    pass


class ControlServer:
    def __init__(self):
        self.socket_server = None
        self.server_thread = None

    def start(self, path):
        logger.info('starting server at %s', path)
        self.socket_server = SocketServer(path, RequestHandler,
                                          bind_and_activate=False)
        # pylint: disable=attribute-defined-outside-init
        self.socket_server.control_handle = self.handle  # type: ignore

        self.server_thread = threading.Thread(
            name='control-server',
            target=self.serve_forever)
        self.server_thread.start()

    def serve_forever(self):
        assert self.socket_server
        try:
            self.socket_server.server_bind()
            self.socket_server.server_activate()
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

    def handle(self, request):
        logger.info('got connection, closing')
        request.close()
