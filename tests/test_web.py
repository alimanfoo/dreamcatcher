"""Render the web status view and read back its goldens."""

import errno
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
    fabricate_titles_and_pull_request_states,
)

import dreamcatcher.web as web_module
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import WEB_BASE_PORT, WEB_HOST, create_app, serve_web

WEB_STATUS_REPORTS = {
    **STATUS_REPORTS,
    "titles-and-pull-requests": fabricate_titles_and_pull_request_states,
}


def render_home(*, state: StateDirectory) -> str:
    """Render the home page against a pinned clock."""
    application = create_app(state=state, clock=lambda: LOOKED_AT)
    response = application.test_client().get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("name", sorted(WEB_STATUS_REPORTS))
def test_a_state_directory_renders_as_its_golden_home(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS[name](state=state)

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


def test_issue_references_link_to_github_with_hash_notation(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    issue_url = f"https://github.com/{REPOSITORY}/issues/50"
    assert f'href="{issue_url}">#50</a>' in page
    assert f'blocked by <a class="issue-number" href="{issue_url}">#50</a>' in page
    assert "blocked by GH50" not in page


def test_pull_request_state_remains_without_a_repository_record(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_titles_and_pull_request_states(state=state)
    state.repository.unlink()

    page = render_home(state=state)

    for pull_request_state in ("draft", "ready", "merged", "closed"):
        assert f'<span class="pr-chip">PR #52 {pull_request_state}</span>' in page


def test_a_record_that_will_not_read_renders_an_error_page(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    record = state.assignments / "GH13-20260819-184158" / "assignment.json"
    write_text(text="not json\n", path=record)
    application = create_app(state=state, clock=lambda: LOOKED_AT)

    response = application.test_client().get("/")

    assert response.status_code == 500
    assert "Invalid JSON" in response.get_data(as_text=True)


def test_the_home_page_rejects_a_non_loopback_host(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = create_app(state=state, clock=lambda: LOOKED_AT)

    response = application.test_client().get("/", headers={"Host": "attacker.test"})

    assert response.status_code == 400


def test_one_repository_always_derives_the_same_starting_port(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_text(text=f"{REPOSITORY}\n", path=state.repository)

    assert web_module._derive_starting_port(state=state) == 8262


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

    def record_address(address, /):
        assert capsys.readouterr().out == ""
        opened.append(address)

    serve_web(
        state=state,
        port=0,
        browser_opener=record_address,
        server_runner=record_port,
    )

    address = f"http://{WEB_HOST}:{ports[0]}/"
    assert opened == [address]
    assert capsys.readouterr().out == f"{address}\n"
    assert werkzeug_logger.level == logging.ERROR


def test_an_interruption_ends_the_server_without_an_error(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    servers = []

    def interrupt(*, server):
        servers.append(server)
        raise KeyboardInterrupt

    serve_web(
        state=state,
        port=0,
        browser_opener=lambda address: None,
        server_runner=interrupt,
    )

    assert servers[0].socket.fileno() == -1


def test_an_interruption_while_opening_the_browser_ends_without_an_error(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()

    def interrupt(address, /):
        raise KeyboardInterrupt

    serve_web(
        state=state,
        port=0,
        browser_opener=interrupt,
        server_runner=lambda *, server: None,
    )


def test_a_scan_with_no_free_port_says_so(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    monkeypatch.setattr(web_module, "WEB_MAX_PORT", WEB_BASE_PORT)
    failure = web_module._WebServerBindError(
        error=OSError(errno.EADDRINUSE, "address already in use")
    )
    monkeypatch.setattr(
        web_module, "_ExclusiveWebServer", MagicMock(side_effect=failure)
    )

    with pytest.raises(ReportableError, match="no free port"):
        serve_web(
            state=state,
            browser_opener=lambda address: None,
            server_runner=lambda *, server: None,
        )


def test_a_bind_failure_other_than_contention_is_reported(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    failure = web_module._WebServerBindError(
        error=OSError(errno.EACCES, "permission denied")
    )
    monkeypatch.setattr(
        web_module, "_ExclusiveWebServer", MagicMock(side_effect=failure)
    )

    with pytest.raises(ReportableError, match="permission denied"):
        serve_web(
            state=state,
            port=0,
            browser_opener=lambda address: None,
            server_runner=lambda *, server: None,
        )


def test_the_web_server_refuses_address_reuse():
    assert web_module._ExclusiveWebServer.allow_reuse_address is False


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
