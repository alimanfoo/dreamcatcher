"""Render the web status view and read back its goldens."""

import inspect

import psutil
import pytest
from conftest import FIXTURES
from status_fabrications import (
    DAEMON_PID,
    LOOKED_AT,
    STATUS_REPORTS,
    fabricate_everything,
)

import dreamcatcher.web as web_module
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import create_app


@pytest.fixture
def daemon(monkeypatch):
    """Answer that the fabricated daemon, and nothing else, is still running."""
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == DAEMON_PID)


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
