"""Render the web status view and read back its goldens."""

import errno
import logging
import re
import socket
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import FIXTURES, REPOSITORY, assert_matches_view_golden, configure
from observations import observed_issue
from records import (
    release_daemon_lock,
    write_assignment,
    write_feed,
    write_round,
    write_tick,
)
from status_fabrications import (
    LOOKED_AT,
    STATUS_REPORTS,
    ended,
    fabricate_a_silent_round,
    fabricate_everything,
    fabricate_nothing,
    fabricate_titles_and_pull_request_states,
    running,
    written,
)
from werkzeug.test import TestResponse

import dreamcatcher.status.report as report_module
import dreamcatcher.web.server as web_server_module
from dreamcatcher.agent_assignments import (
    cancel_assignment,
    read_assignment,
    read_assignments_for_issue,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    AssignmentRoundPurpose,
    StoppedAgentRoundEnding,
)
from dreamcatcher.config import DREAMCATCHER_CONFIG_NAME
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler.models import (
    GlobalCooldown,
    SchedulerRecord,
    Truth,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import serve_web
from dreamcatcher.web.app import _create_app
from dreamcatcher.web.server import _WEB_BASE_PORT, WEB_HOST
from dreamcatcher.web.views import _compose_issue_row

WEB_STATUS_REPORTS = {
    **STATUS_REPORTS,
    "titles-and-pull-requests": fabricate_titles_and_pull_request_states,
}
WEB_ASSIGNMENT_PAGES = {
    "cancelled": (fabricate_everything, "GH70-20260819-184158"),
    "complete": (fabricate_everything, "GH12-20260819-184158"),
    "fault": (fabricate_everything, "GH9-20260819-184158"),
    "silent-round": (fabricate_a_silent_round, "GH13-20260819-184158"),
    "waiting-to-start": (fabricate_everything, "GH44-20260819-184158"),
    "working": (fabricate_everything, "GH13-20260819-184158"),
}

CONVERSATION_ONLY_CONFIG = """[[conversation]]
label = "dream:scout"
[conversation.claude]
prompt = "/dream:scout GH{issue}"
model = "opus"
effort = "xhigh"
"""

ADDITIONAL_AGENT_WORK_CONFIG = (
    CONVERSATION_ONLY_CONFIG
    + """
[[assignment]]
label = "dream:zebra"
[assignment.claude]
prompt = "/dream:zebra GH{issue}"
model = "opus"
effort = "xhigh"
"""
)


def render_home(*, state: StateDirectory) -> str:
    """Render the home page against a pinned clock."""
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    response = application.test_client().get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def render_assignment(*, state: StateDirectory, identifier: str) -> str:
    """Render one assignment page against a pinned clock."""
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    response = application.test_client().get(f"/assignments/{identifier}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _read_tail(*, state: StateDirectory, identifier: str, cursor: str) -> TestResponse:
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    return application.test_client().get(
        f"/assignments/{identifier}/tail",
        query_string={"cursor": cursor},
    )


def _feed_path(*, state: StateDirectory, identifier: str, number: int):
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    return assignment.compose_round_paths(number=number).feed


def _read_cursor(*, response: TestResponse) -> str:
    match = re.search(r'id="cursor"[^>]*value="([^"]+)"', response.text)
    assert match is not None
    return match[1]


@pytest.mark.parametrize("name", sorted(WEB_STATUS_REPORTS))
def test_a_state_directory_renders_as_its_golden_home(name, tmp_path, pytestconfig):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS[name](state=state)

    page = render_home(state=state)

    assert_matches_view_golden(
        rendered=page,
        path=FIXTURES / "web" / f"{name}.html",
        config=pytestconfig,
    )


def test_an_empty_home_names_every_configured_agent_work_label(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_nothing(state=state)
    configure(root=state.root, head=ADDITIONAL_AGENT_WORK_CONFIG)

    page = render_home(state=state)

    assert (
        "Label an issue with dream:smith or dream:zebra to create an assignment."
        in page
    )
    assert "Label an issue with dream:scout to start a conversation." in page


def test_an_empty_home_hides_an_unconfigured_assignment_section(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_nothing(state=state)
    write_text(
        text=CONVERSATION_ONLY_CONFIG,
        path=state.root / DREAMCATCHER_CONFIG_NAME,
    )

    page = render_home(state=state)

    assert 'id="assignments-heading"' not in page
    assert '<h1 id="conversations-heading">Issue conversations</h1>' in page
    assert "Label an issue with dream:scout to start a conversation." in page


@pytest.mark.parametrize("name", sorted(WEB_ASSIGNMENT_PAGES))
def test_an_assignment_renders_as_its_golden_page(name, tmp_path, pytestconfig):
    state = StateDirectory(root=tmp_path)
    fabricate, identifier = WEB_ASSIGNMENT_PAGES[name]
    fabricate(state=state)

    page = render_assignment(state=state, identifier=identifier)

    assert_matches_view_golden(
        rendered=page,
        path=FIXTURES / "web" / "assignments" / f"{name}.html",
        config=pytestconfig,
    )


def test_assignment_page_shows_the_common_agent_work_facts(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH13-20260819-184158")

    assert page.count("<dt>") == 3
    assert "<dt>label</dt><dd>dream:smith</dd>" in page
    assert "<dt>harness</dt><dd>claude</dd>" in page
    assert "<dt>model</dt><dd>opus[1m] · xhigh</dd>" in page
    assert "<dt>assignment</dt>" not in page
    assert "<dt>session</dt>" not in page


def test_assignment_page_asks_once_whether_the_daemon_runs(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    probe = MagicMock(wraps=report_module.is_daemon_lock_held)
    monkeypatch.setattr(report_module, "is_daemon_lock_held", probe)

    render_assignment(state=state, identifier="GH13-20260819-184158")

    probe.assert_called_once_with(path=state.lock)


def test_assignment_page_requests_a_stop_for_its_running_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    client = application.test_client()

    page = client.get(f"/assignments/{identifier}")

    assert page.status_code == 200
    assert f'action="/assignments/{identifier}/stop/2"' in page.text

    response = client.post(
        f"/assignments/{identifier}/stop/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == f"/assignments/{identifier}"
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    paths = assignment.compose_round_paths(number=2)
    assert paths.stop_request.read_text(encoding="utf-8") == ""
    assert (
        f'action="/assignments/{identifier}/stop/2"'
        not in client.get(f"/assignments/{identifier}").text
    )


def test_an_old_assignment_stop_submission_cannot_stop_the_next_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/assignments/{identifier}/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert not assignment.compose_round_paths(number=2).stop_request.exists()


@pytest.mark.parametrize("origin", [None, "https://example.com"])
def test_assignment_stop_requests_must_come_from_the_page(tmp_path, origin):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(f"/assignments/{identifier}/stop/2", headers=headers)

    assert response.status_code == 403
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert not assignment.compose_round_paths(number=2).stop_request.exists()


def test_assignment_stop_control_needs_a_daemon_and_harness_session(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH60-20260819-184158"
    directory = write_assignment(
        state=state,
        identifier=identifier,
        issue=60,
        harness_session_identifier=None,
    )
    write_round(directory=directory, number=1, record=running(minute=30))

    without_session = render_assignment(state=state, identifier=identifier)

    assert f'action="/assignments/{identifier}/stop/1"' not in without_session

    release_daemon_lock(path=state.lock)
    without_daemon = render_assignment(state=state, identifier="GH13-20260819-184158")

    assert 'action="/assignments/GH13-20260819-184158/stop/2"' not in without_daemon


def test_assignment_tail_updates_the_stop_and_cancel_controls(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    page = client.get(f"/assignments/{identifier}")

    response = client.get(
        f"/assignments/{identifier}/tail",
        query_string={"cursor": _read_cursor(response=page)},
    )

    assert response.status_code == 200
    assert (
        '<div id="agent-work-foot" class="agent-work-foot" '
        'hx-swap-oob="morph">' in response.text
    )
    assert f'action="/assignments/{identifier}/stop/2"' in response.text
    assert f'action="/assignments/{identifier}/cancel"' in response.text


def test_assignment_tail_offers_a_hand_resume_only_while_no_round_runs(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    page = client.get(f"/assignments/{identifier}")
    query = {"cursor": _read_cursor(response=page)}

    working = client.get(f"/assignments/{identifier}/tail", query_string=query)
    release_daemon_lock(path=state.lock)
    without_daemon = client.get(f"/assignments/{identifier}/tail", query_string=query)

    assert "<summary>resume by hand</summary>" not in working.text
    assert "<summary>resume by hand</summary>" in without_daemon.text
    assert "claude --resume abc-123" in without_daemon.text


def test_a_stale_assignment_stop_request_is_already_done(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH12-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/assignments/{identifier}/stop/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert not assignment.compose_round_paths(number=2).stop_request.exists()


def test_an_unknown_assignment_cannot_receive_a_stop_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        "/assignments/unknown/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_assignment_page_cancels_its_assignment(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    page = client.get(f"/assignments/{identifier}")

    assert f'action="/assignments/{identifier}/cancel"' in page.text

    response = client.post(
        f"/assignments/{identifier}/cancel",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == f"/assignments/{identifier}"
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.cancelled_at == LOOKED_AT
    assert assignment.compose_round_paths(number=2).stop_request.is_file()


@pytest.mark.parametrize("identifier", ["GH12-20260819-184158", "GH70-20260819-184158"])
def test_an_ended_assignment_offers_no_cancel_control(tmp_path, identifier):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier=identifier)

    assert "/cancel" not in page


def test_a_cancelled_assignment_still_working_offers_no_cancel_control(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    cancel_assignment(assignment=assignment, at=LOOKED_AT)

    page = render_assignment(state=state, identifier=identifier)

    assert 'class="chip status-working">working</span>' in page
    assert "/cancel" not in page


@pytest.mark.parametrize("origin", [None, "https://example.com"])
def test_assignment_cancels_must_come_from_the_page(tmp_path, origin):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(f"/assignments/{identifier}/cancel", headers=headers)

    assert response.status_code == 403
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.is_open


def test_a_stale_assignment_cancel_changes_nothing(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH70-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/assignments/{identifier}/cancel",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.cancelled_at == PINNED + timedelta(minutes=10)


def test_an_unknown_assignment_cannot_be_cancelled(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        "/assignments/unknown/cancel",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_assignment_page_requests_a_retry_for_its_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH9-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    page = client.get(f"/assignments/{identifier}")

    assert f'action="/assignments/{identifier}/retry/2"' in page.text

    response = client.post(
        f"/assignments/{identifier}/retry/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == f"/assignments/{identifier}"
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.retry_requested_at == LOOKED_AT
    assert (
        f'action="/assignments/{identifier}/retry/2"'
        not in client.get(f"/assignments/{identifier}").text
    )


def test_assignment_tail_offers_the_retry_control(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH9-20260819-184158"

    response = _read_tail(state=state, identifier=identifier, cursor="1:0")

    assert '<div id="agent-work-retry" hx-swap-oob="morph">' in response.text
    assert f'action="/assignments/{identifier}/retry/2"' in response.text


@pytest.mark.parametrize(
    ("identifier", "number"),
    [("GH9-20260819-184158", 1), ("GH12-20260819-184158", 2)],
)
def test_an_assignment_retry_needs_its_fault_at_the_submitted_round(
    tmp_path, identifier, number
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/assignments/{identifier}/retry/{number}",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.retry_requested_at is None


@pytest.mark.parametrize("origin", [None, "https://example.com"])
def test_assignment_retry_requests_must_come_from_the_page(tmp_path, origin):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH9-20260819-184158"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(f"/assignments/{identifier}/retry/2", headers=headers)

    assert response.status_code == 403
    assignment = read_assignment(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.retry_requested_at is None


def test_an_unknown_assignment_cannot_receive_a_retry_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        "/assignments/unknown/retry/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_a_stopped_round_is_shown_as_stopped(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    written(
        state=state,
        issue=61,
        records=[
            AgentRoundRecord(
                number=1,
                purpose=AssignmentRoundPurpose.IMPLEMENT,
                started=PINNED,
                pid=1,
                ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=2)),
            )
        ],
    )

    page = render_assignment(state=state, identifier="GH61-20260819-184158")

    assert 'class="round-outcome outcome-stopped">stopped</span>' in page


def test_a_home_card_links_to_its_exact_assignment(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assignment_link = (
        'class="assignment-open" href="/assignments/GH13-20260819-184158" '
        'target="_blank" rel="noopener noreferrer" '
        'aria-label="Open assignment GH13-20260819-184158 (opens in new tab)"'
    )
    assert assignment_link in page
    assert page.count('href="/assignments/GH13-20260819-184158"') == 1
    card_start = page.index('<article id="assignment-GH13-20260819-184158"')
    card = page[card_start : page.index("</article>", card_start)]
    assert card.index(assignment_link) < card.index('class="assignment-detail"')
    assert card.index('class="pr-chip"') > card.index('class="assignment-detail"')


def test_feedback_card_keeps_its_compact_actions_inside_the_heading(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    stylesheet = (
        application.test_client().get("/static/matrix.css").get_data(as_text=True)
    )
    card_start = page.index('<article id="assignment-GH20-20260819-184158"')
    card = page[card_start : page.index("</article>", card_start)]

    assert (
        '<span class="chip status-needs-user-feedback">needs user feedback</span>'
        in card
    )
    assert "[NEEDS USER FEEDBACK]" not in card
    assert re.search(
        r"\.card-heading \{[^}]*display: grid;"
        r"[^}]*grid-template-columns: minmax\(0, 1fr\) max-content;",
        stylesheet,
        re.DOTALL,
    )
    assert re.search(
        r"\.card-heading-actions \{[^}]*flex: none;", stylesheet, re.DOTALL
    )


def test_assignment_feedback_status_uses_the_status_wording(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(
        state=state,
        identifier="GH20-20260819-184158",
    )

    assert (
        '<span id="agent-work-status" '
        'class="chip status-needs-user-feedback">needs user feedback</span>'
    ) in page
    assert "[NEEDS USER FEEDBACK]" not in page


def test_assignment_page_polls_its_tail_from_the_last_complete_line(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158"
    feed_path = _feed_path(state=state, identifier=identifier, number=2)

    page = render_assignment(state=state, identifier=identifier)

    assert f'id="cursor" name="cursor" value="2:{feed_path.stat().st_size}"' in page
    assert (
        f'id="records" class="feed-records" '
        f'hx-get="/assignments/{identifier}/tail" hx-trigger="every 2s" '
        'hx-include="#cursor" hx-select=".feed-line" hx-swap="beforeend"' in page
    )


def test_assignment_page_before_its_first_round_starts_at_the_first_cursor(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(
        state=state,
        identifier="GH44-20260819-184158",
    )

    assert 'id="cursor" name="cursor" value="0:0"' in page
    assert '<p id="empty-feed" class="empty">-- no feed yet --</p>' in page


def test_assignment_page_ids_are_unique(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(
        state=state,
        identifier="GH13-20260819-184158",
    )
    identifiers = re.findall(r'\bid="([^"]+)"', page)

    assert len(identifiers) == len(set(identifiers))


def test_assignment_script_follows_only_when_the_feed_was_at_its_end(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/static/assignment.js")
    script = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'feed.addEventListener("htmx:beforeSwap"' in script
    assert 'feed.addEventListener("htmx:afterSwap"' in script
    assert re.search(
        r"shouldFollowFeed \|\|=\s+feed\.scrollHeight - feed\.scrollTop "
        r"- feed\.clientHeight <= 1;",
        script,
    )
    assert (
        "if (shouldFollowFeed && nextFeedLineRevealAt <= performance.now())" in script
    )
    assert 'assignmentSidebar.addEventListener("click"' in script
    assert 'currentRoundLink?.setAttribute("aria-current", "true")' in script
    assert "focusedRoundLink?.focus({ preventScroll: true })" in script


def test_ended_assignment_cards_have_space_between_them(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    stylesheet = (
        application.test_client().get("/static/matrix.css").get_data(as_text=True)
    )

    assert '<div class="ended-assignment-cards">' in page
    assert re.search(
        r"\.ended-assignment-cards \{[^}]*display: grid;"
        r"[^}]*gap: var\(--space-5\);",
        stylesheet,
        re.DOTALL,
    )


def test_ended_assignments_are_ordered_by_when_they_ended(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    configure(root=state.root)
    written(
        state=state,
        issue=10,
        records=[
            ended(minute=1),
            ended(minute=2, number=2, purpose=AssignmentRoundPurpose.WRAP_UP),
        ],
    )
    written(
        state=state,
        issue=20,
        records=[
            ended(minute=1),
            ended(minute=20, number=2, purpose=AssignmentRoundPurpose.WRAP_UP),
        ],
    )
    written(state=state, issue=30, records=[ended(minute=1)])
    cancel_assignment(
        assignment=read_assignments_for_issue(state=state, issue=30)[0],
        at=PINNED + timedelta(minutes=10),
    )

    page = render_home(state=state)

    assert "Label an issue with dream:smith to create an assignment." in page
    assert "+ 3 ended</summary>" in page
    assert (
        page.index("assignment-GH20-")
        < page.index("assignment-GH30-")
        < page.index("assignment-GH10-")
    )


def test_home_page_types_replaced_assignment_output(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    configure(root=state.root)
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    client = application.test_client()

    home_response = client.get("/")
    script_response = client.get("/static/home.js")
    stylesheet_response = client.get("/static/matrix.css")
    home = home_response.get_data(as_text=True)
    script = script_response.get_data(as_text=True)
    stylesheet = stylesheet_response.get_data(as_text=True)

    assert home_response.status_code == 200
    assert script_response.status_code == 200
    assert stylesheet_response.status_code == 200
    assert 'src="/static/home.js"' in home
    assert 'addEventListener("htmx:beforeSwap"' in script
    assert 'querySelector(".latest-output")' in script
    assert '"(prefers-reduced-motion: reduce)"' in script
    assert (
        "animation: type-output var(--output-typing-duration) steps(32, end);"
        in stylesheet
    )


def test_assignment_page_shares_the_home_page_top_bar(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    home = render_home(state=state)
    assignment = render_assignment(
        state=state,
        identifier="GH13-20260819-184158",
    )
    header_pattern = r'<header class="site-header">.*?</header>'
    home_headers = re.findall(header_pattern, home, re.DOTALL)
    assignment_headers = re.findall(header_pattern, assignment, re.DOTALL)

    assert len(home_headers) == 1
    assert assignment_headers == home_headers


def test_the_daemon_version_links_to_the_documentation(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert (
        '<a class="docs-link" href="https://alimanfoo.github.io/dreamcatcher/" '
        'target="_blank" rel="noopener noreferrer">dreamcatcher v3.0.0.beta1</a>'
        in page
    )
    assert ">Docs</a>" not in page


def test_every_complete_page_uses_the_dreamcatcher_mark_as_its_favicon(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    app = _create_app(state=state)

    pages = (
        render_home(state=state),
        render_assignment(state=state, identifier="GH13-20260819-184158"),
        app.test_client().get("/assignments/unknown").text,
    )

    favicon = (
        '<link rel="icon" type="image/png" href="/static/dreamcatcher-mark-ink.png">'
    )
    assert all(favicon in page for page in pages)


def test_a_theme_choice_is_validated_and_remembered(tmp_path):
    app = _create_app(state=StateDirectory(root=tmp_path))
    client = app.test_client()

    selected = client.get("/?theme=matrix")
    remembered = client.get("/")

    assert 'href="/static/nature.css"' not in selected.text
    assert 'src="/static/nature.js"' not in selected.text
    assert 'href="/static/dreamcatcher-mark-phosphor.png"' in selected.text
    assert "theme=matrix;" in selected.headers["Set-Cookie"]
    assert 'href="/static/nature.css"' not in remembered.text
    assert 'src="/static/nature.js"' not in remembered.text
    assert 'href="/static/dreamcatcher-mark-phosphor.png"' in remembered.text


def test_an_unknown_theme_uses_nature_without_being_remembered(tmp_path):
    app = _create_app(state=StateDirectory(root=tmp_path))
    client = app.test_client()

    response = client.get("/?theme=unknown")
    stylesheet = client.get("/static/nature.css").get_data(as_text=True)
    script = client.get("/static/nature.js").get_data(as_text=True)

    assert 'href="/static/nature.css"' in response.text
    assert 'src="/static/nature.js"' in response.text
    assert 'href="/static/dreamcatcher-mark-ink.png"' in response.text
    assert "Set-Cookie" not in response.headers
    assert "circle at var(--sun-x) 6%" in stylesheet
    assert "opacity: var(--sun-opacity);" in stylesheet
    assert ".status-unknown," in stylesheet
    assert "const sunrise = 6 * 60;" in script
    assert "const sunset = 18 * 60;" in script
    assert 'style.setProperty("--sun-x", `${sunPosition}%`);' in script


def test_github_links_open_in_a_new_tab(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    pages = render_home(state=state) + render_assignment(
        state=state, identifier="GH13-20260819-184158"
    )
    links = re.findall(r'<a [^>]*href="https://github\.com/[^>]+>', pages)

    assert links
    assert all('target="_blank" rel="noopener noreferrer"' in link for link in links)


def test_repository_links_are_separated(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert (
        '<span class="repository-links"><a class="repository-link" '
        'href="https://github.com/alimanfoo/dreamcatcher" '
        'target="_blank" rel="noopener noreferrer">alimanfoo/dreamcatcher</a>'
        '<span aria-hidden="true">·</span>'
        '<a class="repository-link" '
        'href="https://github.com/alimanfoo/dreamcatcher/issues" '
        'target="_blank" rel="noopener noreferrer">issues</a>'
        '<span aria-hidden="true">·</span>'
        '<a class="repository-link" '
        'href="https://github.com/alimanfoo/dreamcatcher/pulls" '
        'target="_blank" rel="noopener noreferrer">pulls</a></span>'
    ) in page


def test_an_unknown_assignment_renders_a_404_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/assignments/GH99-20260819-184158")

    assert response.status_code == 404
    assert (
        "No agent assignment here has identifier GH99-20260819-184158."
        in response.get_data(as_text=True)
    )


def test_an_unknown_assignment_tail_renders_a_404_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()

    response = _read_tail(
        state=state,
        identifier="GH99-20260819-184158",
        cursor="0:0",
    )

    assert response.status_code == 404
    assert (
        "No agent assignment here has identifier GH99-20260819-184158." in response.text
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "garbage",
        "0:1",
        "01:0",
        "-1:0",
        "99:0",
        pytest.param(f"1:{'9' * 5000}", id="oversized integer"),
    ],
)
def test_an_invalid_tail_cursor_renders_a_400_page(tmp_path, cursor):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    written(state=state, issue=60, records=[])

    response = _read_tail(
        state=state,
        identifier="GH60-20260819-184158",
        cursor=cursor,
    )

    assert response.status_code == 400
    assert "The feed cursor is invalid." in response.text


@pytest.mark.parametrize("position", [1, 99])
def test_a_tail_cursor_must_follow_a_complete_line(tmp_path, position):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = written(state=state, issue=60, records=[running(minute=1)])
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=LOOKED_AT, text="one line")],
    )

    response = _read_tail(
        state=state,
        identifier="GH60-20260819-184158",
        cursor=f"1:{position}",
    )

    assert response.status_code == 400
    assert "The feed cursor is invalid." in response.text


def test_a_tail_before_any_round_opens_the_first_round_when_it_arrives(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = written(state=state, issue=60, records=[])
    identifier = "GH60-20260819-184158"

    waiting = _read_tail(state=state, identifier=identifier, cursor="0:0")

    assert waiting.status_code == 200
    assert 'value="0:0"' in waiting.text
    assert "round 1:" not in waiting.text

    write_round(directory=directory, number=1, record=running(minute=1))
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=LOOKED_AT, text="the first line")],
    )
    started = _read_tail(state=state, identifier=identifier, cursor="0:0")

    assert started.status_code == 200
    assert started.text.count("round 1: implement") == 1
    assert "the first line" in started.text
    assert 'id="empty-feed" hx-swap-oob="delete"' in started.text
    assert _read_cursor(response=started).startswith("1:")


def test_a_tail_returns_only_complete_lines_after_its_cursor(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = written(state=state, issue=60, records=[running(minute=1)])
    identifier = "GH60-20260819-184158"
    first = FeedLine(at=LOOKED_AT, text="the first line")
    second = FeedLine(at=LOOKED_AT, text="the second line")
    write_feed(directory=directory, number=1, lines=[first])

    first_read = _read_tail(state=state, identifier=identifier, cursor="1:0")
    cursor = _read_cursor(response=first_read)
    feed_path = _feed_path(state=state, identifier=identifier, number=1)
    append_text(text=second.render().removesuffix("\n"), path=feed_path)
    incomplete_read = _read_tail(
        state=state,
        identifier=identifier,
        cursor=cursor,
    )

    assert "the first line" in first_read.text
    assert "the second line" not in first_read.text
    assert 'id="empty-feed"' not in first_read.text
    assert "the second line" not in incomplete_read.text
    assert _read_cursor(response=incomplete_read) == cursor

    append_text(text="\n", path=feed_path)
    complete_read = _read_tail(
        state=state,
        identifier=identifier,
        cursor=cursor,
    )

    assert "the first line" not in complete_read.text
    assert "the second line" in complete_read.text
    assert _read_cursor(response=complete_read) != cursor


def test_an_ended_round_moves_to_the_next_round_after_an_empty_read(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = written(
        state=state,
        issue=60,
        records=[ended(minute=1), running(minute=10, number=2)],
    )
    identifier = "GH60-20260819-184158"
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=LOOKED_AT, text="already read")],
    )
    write_feed(
        directory=directory,
        number=2,
        lines=[FeedLine(at=LOOKED_AT, text="new round output")],
    )
    first_feed = _feed_path(state=state, identifier=identifier, number=1)

    response = _read_tail(
        state=state,
        identifier=identifier,
        cursor=f"1:{first_feed.stat().st_size}",
    )

    assert response.status_code == 200
    assert "already read" not in response.text
    assert response.text.count("round 2: implement") == 1
    assert "new round output" in response.text
    assert _read_cursor(response=response).startswith("2:")


def test_a_terminal_tail_returns_late_output_before_it_stops(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH12-20260819-184158"
    feed_path = _feed_path(state=state, identifier=identifier, number=2)
    append_text(
        text=FeedLine(at=LOOKED_AT, text="late output").render(),
        path=feed_path,
    )

    output = _read_tail(state=state, identifier=identifier, cursor="2:0")
    stopped = _read_tail(
        state=state,
        identifier=identifier,
        cursor=_read_cursor(response=output),
    )

    assert output.status_code == 200
    assert "late output" in output.text
    assert stopped.status_code == 286


def test_a_faulted_tail_keeps_polling_when_it_reads_nothing_new(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = _feed_path(state=state, identifier="GH9-20260819-184158", number=2)

    response = _read_tail(
        state=state,
        identifier="GH9-20260819-184158",
        cursor=f"2:{feed.stat().st_size}",
    )

    assert response.status_code == 200


def test_a_tail_fragment_matches_its_golden(tmp_path, pytestconfig):
    state = StateDirectory(root=tmp_path)
    fabricate_a_silent_round(state=state)
    identifier = "GH13-20260819-184158"
    first_feed = _feed_path(state=state, identifier=identifier, number=1)
    response = _read_tail(
        state=state,
        identifier=identifier,
        cursor=f"1:{first_feed.stat().st_size}",
    )

    assert response.status_code == 200
    assert_matches_view_golden(
        rendered=response.text,
        path=FIXTURES / "web" / "tail.html",
        config=pytestconfig,
    )
    assert 'id="agent-work-detail"' in response.text


def test_a_quiet_tail_has_no_appendable_text_nodes(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    written(state=state, issue=60, records=[running(minute=1)])

    response = _read_tail(
        state=state,
        identifier="GH60-20260819-184158",
        cursor="1:0",
    )

    assert response.text.startswith(
        '<input type="hidden" id="cursor" name="cursor" value="1:0" '
        'hx-swap-oob="true"><span'
    )
    assert '</span><div id="agent-work-retry"' in response.text
    assert '</div><p id="agent-work-detail"' in response.text
    assert "</p><aside" in response.text
    assert '</aside><div id="agent-work-foot"' in response.text
    assert response.text.endswith("</div>")


def test_an_assignment_page_links_its_title_and_pull_request(tmp_path):
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


def test_assignment_heading_keeps_its_chips_in_the_top_right(tmp_path):
    application = _create_app(
        state=StateDirectory(root=tmp_path),
        clock=lambda: LOOKED_AT,
        zone=DISPLAY_TIME_ZONE,
    )
    stylesheet = (
        application.test_client().get("/static/matrix.css").get_data(as_text=True)
    )

    assert re.search(
        r"\.assignment-heading \{[^}]*display: grid;"
        r"[^}]*grid-template-columns: minmax\(0, 1fr\) max-content;"
        r"[^}]*align-items: start;",
        stylesheet,
        re.DOTALL,
    )
    assert re.search(
        r"\.assignment-heading h1 \{[^}]*min-width: 0;", stylesheet, re.DOTALL
    )
    assert re.search(
        r"\.assignment-heading-actions \{[^}]*flex-wrap: nowrap;",
        stylesheet,
        re.DOTALL,
    )


def test_assignment_rounds_link_to_the_feed_in_ascending_order(tmp_path):
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


def test_an_errored_rounds_style_uses_its_outcome_alone(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH35-20260819-184158")

    assert 'class="round-outcome outcome-errored">errored (exit 2)</span>' in page


def test_hand_resume_command_is_collapsed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH9-20260819-184158")
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    stylesheet = (
        application.test_client().get("/static/matrix.css").get_data(as_text=True)
    )

    assert '<details class="manual-recovery">' in page
    assert "<summary>resume by hand</summary>" in page
    assert "escape hatch" not in page
    assert 'class="panel resume-command"' not in page
    assert "font-size: 0.9em;" in stylesheet


def test_assignment_page_offers_a_control_that_jumps_to_the_feed_tail(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH13-20260819-184158")
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    response = application.test_client().get("/static/assignment.js")
    script = response.get_data(as_text=True)

    assert (
        '<button class="feed-tail" type="button" aria-controls="records">'
        "TAIL ↓</button>" in page
    )
    assert response.status_code == 200
    assert "feed.scrollTop = feed.scrollHeight" in script
    assert 'feedTail?.toggleAttribute("hidden", shouldFollowFeed)' in script
    assert "top: feed.scrollHeight" in script


def test_assignment_feed_fits_in_the_initial_viewport(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/static/matrix.css")
    stylesheet = response.get_data(as_text=True)

    assert response.status_code == 200
    assert re.search(
        r"\.feed-records \{[^}]*height: clamp\(240px, 50vh, 520px\);",
        stylesheet,
        re.DOTALL,
    )


def test_round_headings_are_separated_from_the_feed_content(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/static/matrix.css")
    stylesheet = response.get_data(as_text=True)

    assert response.status_code == 200
    assert re.search(
        r"\.feed-records \{[^}]*align-content: start;",
        stylesheet,
        re.DOTALL,
    )
    assert re.search(
        r"\.round-boundary \{[^}]*top: calc\(var\(--space-7\) \* -1\);"
        r"[^}]*border-bottom: var\(--line\) solid var\(--rule\);",
        stylesheet,
        re.DOTALL,
    )


def test_assignment_reporting_remains_without_a_repository_record(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_titles_and_pull_request_states(state=state)
    state.repository.unlink()

    page = render_assignment(state=state, identifier="GH10-20260819-184158")

    assert '<strong class="assignment-issue">#10' in page
    assert '<span class="pr-chip">PR #52 draft</span>' in page


def test_an_assignment_page_reports_a_repository_record_that_will_not_read(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    state.repository.unlink()
    state.repository.mkdir()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/assignments/GH13-20260819-184158")

    assert response.status_code == 500
    assert "cannot read" in response.get_data(as_text=True)


def test_the_assignment_page_preserves_and_escapes_an_unparseable_feed_line(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = state.assignments / "GH13-20260819-184158" / "rounds" / "2" / "feed.txt"
    append_text(text="<script>alert('no')</script>\n", path=feed)

    page = render_assignment(state=state, identifier="GH13-20260819-184158")

    assert "&lt;script&gt;alert(&#39;no&#39;)&lt;/script&gt;" in page
    assert "<script>alert('no')</script>" not in page


def test_the_same_state_renders_as_the_same_home_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    first_page = render_home(state=state)
    second_page = render_home(state=state)

    assert second_page == first_page


def test_every_home_page_id_is_unique(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    identifiers = re.findall(r' id="([^"]+)"', render_home(state=state))

    assert identifiers
    assert len(identifiers) == len(set(identifiers))


def test_the_home_page_autoescapes_feed_output(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = state.assignments / "GH13-20260819-184158" / "rounds" / "2" / "feed.txt"
    line = FeedLine(at=LOOKED_AT, text="<script>alert('no')</script>")
    append_text(text=line.render(), path=feed)

    page = render_home(state=state)

    assert "&lt;script&gt;alert(&#39;no&#39;)&lt;/script&gt;" in page
    assert "<script>alert('no')</script>" not in page


def test_issue_references_link_to_github_with_hash_notation(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    issue_url = f"https://github.com/{REPOSITORY}/issues/50"
    github_attributes = 'target="_blank" rel="noopener noreferrer"'
    assert f'href="{issue_url}" {github_attributes}>#50</a>' in page
    assert (
        '<span class="chip issue-blocked">blocked by '
        f'<a class="issue-number" href="{issue_url}" '
        f"{github_attributes}>#50</a>" in page
    )
    assert (
        '<span class="chip issue-routing-conflict">multiple '
        "assignment labels: dream:less, dream:smith; blocked by "
        f'<a class="issue-number" href="{issue_url}" '
        f"{github_attributes}>#50</a>" in page
    )
    assert "blocked by GH50" not in page


def test_an_assignment_label_that_looks_like_an_issue_reference_remains_text():
    evidence = "multiple assignment labels: dream:smith, GH123"
    observation = observed_issue(
        issue=53,
        assignment_labels=("dream:smith", "GH123"),
        values={"routing_conflict": Truth.TRUE},
        evidence={"routing_conflict": evidence},
    )

    row = _compose_issue_row(observation=observation)

    assert row.evidence == (evidence,)


def test_a_pull_request_links_to_github_before_its_state_is_observed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    pull_request_url = f"https://github.com/{REPOSITORY}/pull/52"
    assert (
        f'href="{pull_request_url}" target="_blank" '
        'rel="noopener noreferrer">PR #52</a>' in page
    )


def test_dashboard_groups_issues_with_assignments(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert page.index('id="assignments-heading"') < page.index('id="issue-50"')
    assert 'id="issues-heading"' not in page
    assert 'id="conversations-heading"' not in page


def test_a_failure_at_capacity_shows_beside_the_capacity(tmp_path):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS["at-cap"](state=state)

    page = render_home(state=state)

    assert "<dt>agent capacity</dt>" in page
    assert "<dt>scheduler failures</dt>" in page
    assert "could not list issues for dream:less: could not connect" in page


def test_next_update_is_left_out_when_no_daemon_is_running(tmp_path):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS["nothing"](state=state)

    page = render_home(state=state)

    assert "<dt>next update in</dt>" not in page


def test_an_active_cooldown_is_a_warning_fact(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            cooldown=GlobalCooldown(
                started=LOOKED_AT, ends=LOOKED_AT + timedelta(minutes=15)
            ),
        ),
    )

    page = render_home(state=state)

    assert page.count('<div class="fact warning">') == 1
    assert "<dt>global cooldown</dt>" in page
    assert "<dd>ends in 15m</dd>" in page
    assert "<dt>scheduler failures</dt>" not in page


def test_an_inactive_cooldown_is_not_shown(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert "global cooldown" not in page


def test_pull_request_state_remains_without_a_repository_record(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_titles_and_pull_request_states(state=state)
    state.repository.unlink()

    page = render_home(state=state)

    for pull_request_state in ("draft", "ready", "merged", "closed"):
        assert f'<span class="pr-chip">PR #52 {pull_request_state}</span>' in page


def test_a_record_that_will_not_read_renders_an_error_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    record = state.assignments / "GH13-20260819-184158" / "assignment.json"
    write_text(text="not json\n", path=record)
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/")

    assert response.status_code == 500
    assert "Invalid JSON" in response.get_data(as_text=True)


def test_the_home_page_rejects_a_non_loopback_host(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/", headers={"Host": "attacker.test"})

    assert response.status_code == 400


def test_one_repository_always_derives_the_same_starting_port(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_text(text=f"{REPOSITORY}\n", path=state.repository)

    assert web_server_module._derive_starting_port(state=state) == 8262


def test_an_occupied_starting_port_makes_the_scan_move_on(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    ports = []
    reverse_lookup = MagicMock()
    monkeypatch.setattr(socket, "getfqdn", reverse_lookup)

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
    reverse_lookup.assert_not_called()


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

    assert web_server_module._derive_starting_port(state=state) == _WEB_BASE_PORT


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
    monkeypatch.setattr(web_server_module, "WEB_MAX_PORT", _WEB_BASE_PORT)
    failure = web_server_module._WebServerBindError(
        error=OSError(errno.EADDRINUSE, "address already in use")
    )
    monkeypatch.setattr(
        web_server_module, "_ExclusiveWebServer", MagicMock(side_effect=failure)
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
    failure = web_server_module._WebServerBindError(
        error=OSError(errno.EACCES, "permission denied")
    )
    monkeypatch.setattr(
        web_server_module, "_ExclusiveWebServer", MagicMock(side_effect=failure)
    )

    with pytest.raises(ReportableError, match="permission denied"):
        serve_web(
            state=state,
            port=0,
            browser_opener=lambda address: None,
            server_runner=lambda *, server: None,
        )


def test_the_web_server_refuses_address_reuse():
    assert web_server_module._ExclusiveWebServer.allow_reuse_address is False


def test_the_default_server_runner_serves_forever():
    server = MagicMock()

    web_server_module.run_web_server(server=server)

    server.serve_forever.assert_called_once_with()
