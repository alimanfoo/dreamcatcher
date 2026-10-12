"""Bind and run dreamcatcher's local web server."""

import errno
import zlib
from _thread import interrupt_main
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from queue import SimpleQueue
from socketserver import TCPServer
from threading import Event, Thread
from typing import Protocol

from werkzeug.serving import BaseWSGIServer, ThreadedWSGIServer

from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import read_repository

WEB_HOST = "127.0.0.1"
_WEB_BASE_PORT = 8100
_WEB_PORT_RANGE = 400
WEB_MAX_PORT = 65535


class _WebServerBindError(Exception):
    def __init__(self, *, error: OSError) -> None:
        super().__init__(str(error))
        self.error = error


class _ExclusiveWebServer(ThreadedWSGIServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        """Bind exclusively without resolving the loopback address."""
        try:
            TCPServer.server_bind(self)
        except OSError as error:
            raise _WebServerBindError(error=error) from error
        self.server_name = WEB_HOST
        self.server_port = self.server_address[1]


class WebServerRunner(Protocol):
    """Run a bound local web server until the process should stop."""

    def __call__(self, *, server: BaseWSGIServer) -> None:
        """Run the server, which has already started listening."""
        ...


def run_web_server(*, server: BaseWSGIServer) -> None:
    """Serve requests on a bound web server until the process stops."""
    server.serve_forever()


class _BackgroundWebServer:
    def __init__(
        self,
        *,
        server: BaseWSGIServer,
        notify_main: Callable[[], None],
    ) -> None:
        self.server = server
        self.notify_main = notify_main
        self.failures: SimpleQueue[BaseException] = SimpleQueue()
        self.is_stopping = Event()
        self.thread = Thread(target=self._serve)

    def start(self) -> None:
        """Start serving in the background."""
        self.thread.start()

    def stop(self) -> None:
        """Stop serving, join the thread, and close the server."""
        self.is_stopping.set()
        if self.thread.ident is not None:
            if self.thread.is_alive():
                self.server.shutdown()
            self.thread.join()
        self.server.server_close()

    def raise_if_failed(self) -> None:
        """Raise a reportable failure when the serving thread failed."""
        if self.failures.empty():
            return
        failure = self.failures.get()
        if isinstance(failure, ReportableError):
            raise failure
        raise ReportableError(f"The web server failed: {failure}") from failure

    def _serve(self) -> None:
        try:
            self.server.serve_forever()
        except BaseException as error:
            self.failures.put(error)
        else:
            if not self.is_stopping.is_set():
                self.failures.put(
                    ReportableError("The web server stopped unexpectedly.")
                )
        finally:
            if not self.is_stopping.is_set():
                self.notify_main()


@contextmanager
def run_web_server_in_background(
    *,
    server: BaseWSGIServer,
    notify_main: Callable[[], None] = interrupt_main,
) -> Generator[None, None, None]:
    """Own and serve a bound server until the surrounding action ends."""
    background = _BackgroundWebServer(server=server, notify_main=notify_main)
    try:
        background.start()
        yield
    finally:
        background.stop()
        background.raise_if_failed()


def create_web_server(
    *,
    state: StateDirectory,
    port: int | None,
    application: Callable[..., Iterable[bytes]],
) -> BaseWSGIServer:
    """Bind a local web server to the given port or the first free one."""
    starting_port = port if port is not None else _derive_starting_port(state=state)
    ending_port = starting_port if port is not None else WEB_MAX_PORT
    for candidate in range(starting_port, ending_port + 1):
        try:
            return _ExclusiveWebServer(WEB_HOST, candidate, application)
        except _WebServerBindError as failure:
            if failure.error.errno == errno.EADDRINUSE:
                if port is not None:
                    raise ReportableError(f"--port {port} is already in use") from None
                continue
            raise ReportableError(
                f"could not listen on port {candidate}: {failure.error}"
            ) from None
    raise ReportableError(f"no free port is available from {starting_port}")


def _derive_starting_port(*, state: StateDirectory) -> int:
    repository = read_repository(state=state)
    if repository is None:
        return _WEB_BASE_PORT
    repository_digest = zlib.crc32(repository.encode("utf-8"))
    return _WEB_BASE_PORT + repository_digest % _WEB_PORT_RANGE
