"""Render the web status view and read back its goldens."""

import errno
import inspect
import logging
import re
import socket
from unittest.mock import MagicMock

import pytest
from conftest import FIXTURES, REPOSITORY
from status_fabrications import (
    LOOKED_AT,
    STATUS_REPORTS,
    fabricate_a_silent_round,
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
WEB_ASSIGNMENT_PAGES = {
    "complete": (fabricate_everything, "GH12-20260819-184158"),
    "fault": (fabricate_everything, "GH9-20260819-184158"),
    "silent-round": (fabricate_a_silent_round, "GH13-20260819-184158"),
    "waiting-to-start": (fabricate_everything, "GH44-20260819-184158"),
    "working": (fabricate_everything, "GH13-20260819-184158"),
}


def render_home(*, state: StateDirectory) -> str:
    """Render the home page against a pinned clock."""
    application = create_app(state=state, clock=lambda: LOOKED_AT)
    response = application.test_client().get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def render_assignment(*, state: StateDirectory, identifier: str) -> str:
    """Render one assignment page against a pinned clock."""
    application = create_app(state=state, clock=lambda: LOOKED_AT)
    response = application.test_client().get(f"/assignments/{identifier}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.mark.parametrize("name", sorted(WEB_STATUS_REPORTS))
def test_a_state_directory_renders_as_its_golden_home(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS[name](state=state)

    page = render_home(state=state)

    assert page == (FIXTURES / "web" / f"{name}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(WEB_ASSIGNMENT_PAGES))
def test_an_assignment_renders_as_its_golden_page(name, tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate, identifier = WEB_ASSIGNMENT_PAGES[name]
    fabricate(state=state)

    page = render_assignment(state=state, identifier=identifier)

    assert page == (FIXTURES / "web" / "assignments" / f"{name}.html").read_text(
        encoding="utf-8"
    )


def test_a_home_card_links_to_its_exact_assignment(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assignment_link = (
        'class="assignment-open" href="/assignments/GH13-20260819-184158" '
        'aria-label="Open assignment GH13-20260819-184158"'
    )
    assert assignment_link in page
    assert page.count('href="/assignments/GH13-20260819-184158"') == 1


def test_github_links_open_in_a_new_tab(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    pages = render_home(state=state) + render_assignment(
        state=state, identifier="GH13-20260819-184158"
    )
    links = re.findall(r'<a [^>]*href="https://github\.com/[^>]+>', pages)

    assert links
    assert all('target="_blank" rel="noopener noreferrer"' in link for link in links)


def test_an_unknown_assignment_renders_a_404_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = create_app(state=state, clock=lambda: LOOKED_AT)

    response = application.test_client().get("/assignments/GH99-20260819-184158")

    assert response.status_code == 404
    assert (
        "No agent assignment here has identifier GH99-20260819-184158."
        in response.get_data(as_text=True)
    )


def test_an_assignment_page_links_its_title_and_pull_request(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_titles_and_pull_request_states(state=state)

    page = render_assignment(state=state, identifier="GH10-20260819-184158")

    assert (
        f'href="https://github.com/{REPOSITORY}/issues/10" target="_blank" '
        'rel="noopener noreferrer">#10 '
        "<span>Draft assignment</span></a>" in page
    )
    assert (
        f'href="https://github.com/{REPOSITORY}/pull/52" target="_blank" '
        'rel="noopener noreferrer">PR #52 draft</a>' in page
    )


def test_assignment_rounds_link_to_the_feed_in_ascending_order(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH13-20260819-184158")
    round_links = re.findall(
        r'class="round-link" href="#feed-round-(\d+)"[^>]*>\s*'
        r'<span class="round-number">(\d+)</span>',
        page,
    )

    assert round_links == [("1", "01"), ("2", "02")]
    assert 'class="assignment-workspace"' in page
    assert 'class="feed-records"' in page
    assert 'src="/static/assignment.js"' in page


def test_assignment_reporting_remains_without_a_repository_record(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_titles_and_pull_request_states(state=state)
    state.repository.unlink()

    page = render_assignment(state=state, identifier="GH10-20260819-184158")

    assert '<strong class="assignment-issue">#10' in page
    assert '<span class="pr-chip">PR #52 draft</span>' in page


def test_an_assignment_page_reports_a_repository_record_that_will_not_read(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    state.repository.unlink()
    state.repository.mkdir()
    application = create_app(state=state, clock=lambda: LOOKED_AT)

    response = application.test_client().get("/assignments/GH13-20260819-184158")

    assert response.status_code == 500
    assert "cannot read" in response.get_data(as_text=True)


def test_the_assignment_page_preserves_and_escapes_an_unparseable_feed_line(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = state.assignments / "GH13-20260819-184158" / "rounds" / "2" / "feed.txt"
    append_text(text="<script>alert('no')</script>\n", path=feed)

    page = render_assignment(state=state, identifier="GH13-20260819-184158")

    assert "&lt;script&gt;alert(&#39;no&#39;)&lt;/script&gt;" in page
    assert "<script>alert('no')</script>" not in page


def test_the_same_state_renders_as_the_same_home_page(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    first_page = render_home(state=state)
    second_page = render_home(state=state)

    assert second_page == first_page


def test_every_home_page_id_is_unique(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    identifiers = re.findall(r' id="([^"]+)"', render_home(state=state))

    assert identifiers
    assert len(identifiers) == len(set(identifiers))


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
    github_attributes = 'target="_blank" rel="noopener noreferrer"'
    assert f'href="{issue_url}" {github_attributes}>#50</a>' in page
    assert (
        f'blocked by <a class="issue-number" href="{issue_url}" '
        f"{github_attributes}>#50</a>" in page
    )
    assert "blocked by GH50" not in page


def test_a_pull_request_links_to_github_before_its_state_is_observed(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    pull_request_url = f"https://github.com/{REPOSITORY}/pull/52"
    assert (
        f'href="{pull_request_url}" target="_blank" '
        'rel="noopener noreferrer">PR #52</a>' in page
    )


def test_dashboard_counts_use_four_digits_without_redundant_issue_headings(
    tmp_path, daemon
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert re.search(r"AGENT ASSIGNMENTS <span>\d{4}</span>", page)
    assert re.search(r"ISSUES <span>\d{4}</span>", page)
    assert "AVAILABLE ISSUES" not in page
    assert "BLOCKED ISSUES" not in page


def test_capacity_does_not_repeat_as_a_scheduler_hold(tmp_path, daemon):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS["at-cap"](state=state)

    page = render_home(state=state)

    assert "<dt>agent capacity</dt>" in page
    assert "<dt>scheduler hold</dt>" not in page


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
