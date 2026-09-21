"""Render the web status view and read back its goldens."""

import inspect
import logging
import socket
from unittest.mock import MagicMock

import pytest
from conftest import FIXTURES, REPOSITORY
from status_fabrications import (
    LOOKED_AT,
    STATUS_REPORTS,
    fabricate_everything,
)

import dreamcatcher.web as web_module
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import WEB_BASE_PORT, WEB_HOST, create_app, serve_web


def find_unused_port() -> int:
    """Return a port that a loopback socket can bind now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((WEB_HOST, 0))
        return candidate.getsockname()[1]


def render_home(*, state: StateDirectory) -> str:
    """Render the home page against a pinned clock."""
    application = create_app(state=state, clock=lambda: LOOKED_AT)
    response = application.test_client().get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("name", sorted(STATUS_REPORTS))
def test_a_state_directory_renders_as_its_golden_home(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    STATUS_REPORTS[name](state=state)

    page = render_home(state=state)

    assert page == (FIXTURES / "web" / f"{name}.html").read_text(encoding="utf-8")


def test_the_home_page_autoescapes_feed_output(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = state.assignments / "GH13-20260819-184158" / "rounds" / "2" / "feed.txt"
    line = FeedLine(at=LOOKED_AT, text="<script>alert('no')</script>")
    append_text(text=line.render(), path=feed)

    page = render_home(state=state)

    assert "&lt;script&gt;alert(&#39;no&#39;)&lt;/script&gt;" in page
    assert "<script>alert('no')</script>" not in page


def test_a_record_that_will_not_read_renders_an_error_page(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    record = state.assignments / "GH13-20260819-184158" / "assignment.json"
    write_text(text="not json\n", path=record)
    application = create_app(state=state, clock=lambda: LOOKED_AT)

    response = application.test_client().get("/")

    assert response.status_code == 500
    assert "Invalid JSON" in response.get_data(as_text=True)


def test_one_repository_always_starts_on_the_same_port(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    ports = []

    def record_port(*, server):
        ports.append(server.server_port)

    for _ in range(2):
        serve_web(
            state=state,
            browser_opener=lambda address: None,
            server_runner=record_port,
        )

    assert ports[0] == ports[1]


def test_an_occupied_starting_port_makes_the_scan_move_on(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    ports = []

    def record_port(*, server):
        ports.append(server.server_port)

    serve_web(
        state=state,
        browser_opener=lambda address: None,
        server_runner=record_port,
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((WEB_HOST, ports[0]))
        occupied.listen()
        serve_web(
            state=state,
            browser_opener=lambda address: None,
            server_runner=record_port,
        )

    assert ports[1] == ports[0] + 1


def test_a_pinned_port_that_is_taken_is_refused(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind((WEB_HOST, 0))
        occupied.listen()
        port = occupied.getsockname()[1]

        with pytest.raises(ReportableError, match=rf"--port {port} is already in use"):
            serve_web(
                state=state,
                port=port,
                browser_opener=lambda address: None,
                server_runner=lambda *, server: None,
            )


def test_the_base_port_starts_a_scan_with_no_repository_record(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()

    assert web_module._derive_starting_port(state=state) == WEB_BASE_PORT


def test_the_browser_receives_the_address_the_server_listens_on(
    tmp_path, capsys, monkeypatch
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    opened = []
    ports = []
    werkzeug_logger = logging.getLogger("werkzeug")
    monkeypatch.setattr(werkzeug_logger, "level", logging.NOTSET)

    def record_port(*, server):
        ports.append(server.server_port)

    port = find_unused_port()
    serve_web(
        state=state,
        port=port,
        browser_opener=opened.append,
        server_runner=record_port,
    )

    address = f"http://{WEB_HOST}:{ports[0]}/"
    assert opened == [address]
    assert capsys.readouterr().out == f"{address}\n"
    assert werkzeug_logger.level == logging.ERROR


def test_an_interruption_ends_the_server_without_an_error(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()

    def interrupt(*, server):
        raise KeyboardInterrupt

    serve_web(
        state=state,
        port=find_unused_port(),
        browser_opener=lambda address: None,
        server_runner=interrupt,
    )


def test_a_scan_with_no_free_port_says_so(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    monkeypatch.setattr(web_module, "WEB_MAX_PORT", WEB_BASE_PORT)
    monkeypatch.setattr(web_module, "make_server", MagicMock(side_effect=SystemExit))

    with pytest.raises(ReportableError, match="no free port"):
        serve_web(
            state=state,
            browser_opener=lambda address: None,
            server_runner=lambda *, server: None,
        )


def test_the_default_server_runner_serves_forever():
    server = MagicMock()

    web_module._run_server(server=server)

    server.serve_forever.assert_called_once_with()


@pytest.mark.parametrize(
    "dependency",
    [
        "dreamcatcher.tui",
        "dreamcatcher.daemon",
        "dreamcatcher.scheduler",
        "dreamcatcher.github",
        "request_agent_assignment_retry",
    ],
)
def test_the_web_view_does_not_import_domain_policy_or_operations(dependency):
    assert dependency not in inspect.getsource(web_module)
