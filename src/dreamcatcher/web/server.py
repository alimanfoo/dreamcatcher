"""Bind and run dreamcatcher's local web server."""

import errno
import zlib
from collections.abc import Callable, Iterable
from socketserver import TCPServer
from typing import Protocol

from werkzeug.serving import BaseWSGIServer

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


class _ExclusiveWebServer(BaseWSGIServer):
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
