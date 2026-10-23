"""Render the web status view and read back its goldens."""

import errno
import logging
import re
import socket
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from enum import StrEnum
from threading import Event
from unittest.mock import MagicMock

import pytest
from clocks import DISPLAY_TIME_ZONE, PINNED
from conftest import DAEMON_PID, FIXTURES, REPOSITORY, assert_matches_view_golden
from records import (
    MERGED_INPUT,
    SCOUT_ROUTES,
    SMITH_ROUTES,
    release_daemon_lock,
    write_assignment,
    write_daemon_run,
    write_feed,
    write_round,
    write_tick,
)
from rows import UNCLAIMED, compose_request_row
from status_fabrications import (
    CAMPAIGN_CHILDREN,
    LOOKED_AT,
    STATUS_REPORTS,
    compose_conversation_row,
    compose_ended_round,
    compose_running_round,
    fabricate_a_dead_daemon,
    fabricate_a_silent_round,
    fabricate_campaign_report,
    fabricate_campaigns,
    fabricate_conversation,
    fabricate_everything,
    fabricate_nothing,
    fabricate_titles_and_pull_request_states,
    write_assignment_with_rounds,
    write_running_daemon,
)
from werkzeug.serving import make_server
from werkzeug.test import TestResponse

import dreamcatcher.status.report as report_module
import dreamcatcher.web.app as web_app_module
import dreamcatcher.web.server as web_server_module
from dreamcatcher.agent_assignments import (
    cancel_assignment,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    StoppedAgentRoundEnding,
)
from dreamcatcher.agent_work import (
    AgentWorkEnding,
    AgentWorkEndReason,
    find_agent_work,
    read_agent_work_at_issue,
)
from dreamcatcher.campaigns import (
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
)
from dreamcatcher.daemon_runs import RecordedRoute
from dreamcatcher.documents import append_text, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    GlobalCooldown,
    IssueCommentsFinding,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import AgentWorkStatusValue
from dreamcatcher.web import serve_web, serve_web_in_background
from dreamcatcher.web.app import _create_app
from dreamcatcher.web.server import (
    _WEB_BASE_PORT,
    WEB_HOST,
    run_web_server_in_background,
)

WEB_STATUS_REPORTS = {
    **STATUS_REPORTS,
    "titles-and-pull-requests": fabricate_titles_and_pull_request_states,
}
WEB_ASSIGNMENT_PAGES = {
    "cancelled": (fabricate_everything, "GH70-20260819-184158-assignment"),
    "complete": (fabricate_everything, "GH12-20260819-184158-assignment"),
    "fault": (fabricate_everything, "GH9-20260819-184158-assignment"),
    "silent-round": (fabricate_a_silent_round, "GH13-20260819-184158-assignment"),
    "waiting-to-start": (fabricate_everything, "GH44-20260819-184158-assignment"),
    "working": (fabricate_everything, "GH13-20260819-184158-assignment"),
}


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
    response = application.test_client().get(f"/work/{identifier}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def render_conversation(*, state: StateDirectory, issue: int) -> str:
    """Render one conversation page against a pinned clock."""
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    response = application.test_client().get(
        f"/work/GH{issue}-20260819-184158-conversation"
    )
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _read_tail(
    *, state: StateDirectory, identifier: str, position: str
) -> TestResponse:
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    return application.test_client().get(
        f"/work/{identifier}/tail",
        query_string={"position": position},
    )


def _find_feed_path(*, state: StateDirectory, identifier: str, number: int):
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    return assignment.compose_round_paths(number=number).feed


def _read_position(*, response: TestResponse) -> str:
    match = re.search(r'id="position"[^>]*value="([^"]+)"', response.text)
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


def test_an_empty_home_names_every_routed_label(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_nothing(state=state)
    write_daemon_run(
        state=state,
        pid=DAEMON_PID,
        routes=[
            *SMITH_ROUTES,
            *SCOUT_ROUTES,
            RecordedRoute(label="dream:zebra", kind=AgentWorkKind.ASSIGNMENT),
        ],
    )

    page = render_home(state=state)

    assert (
        "Assign an issue to yourself and label it with "
        "dream:smith or dream:zebra to create an assignment." in page
    )
    assert (
        "Assign an issue to yourself, label it with dream:scout and post a comment "
        "to start a conversation." in page
    )


def test_an_empty_home_hides_an_unrouted_assignment_section(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_nothing(state=state)
    write_daemon_run(state=state, pid=DAEMON_PID, routes=SCOUT_ROUTES)

    page = render_home(state=state)

    assert 'id="assignment-tab"' not in page
    assert 'id="conversation-tab"' in page
    assert (
        "Assign an issue to yourself, label it with dream:scout and post a comment "
        "to start a conversation." in page
    )


@pytest.mark.parametrize("issue", [60, 61])
def test_a_campaign_renders_as_its_golden_page(issue, tmp_path, pytestconfig):
    state = StateDirectory(root=tmp_path)
    fabricate_campaign_report(state=state)

    page = render_assignment(
        state=state, identifier=f"GH{issue}-20260819-184158-campaign"
    )

    assert_matches_view_golden(
        rendered=page,
        path=FIXTURES / "web" / "campaigns" / f"GH{issue}.html",
        config=pytestconfig,
    )


def test_a_lead_rounds_trigger_links_each_sub_issue_it_names(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_campaign_report(state=state)
    identifier = "GH60-20260819-184158-campaign"
    write_round(
        directory=state.work / identifier,
        number=2,
        record=compose_ended_round(minute=5, number=2),
        round_input=CampaignRoundInput(
            issue=60,
            children=CAMPAIGN_CHILDREN,
            notifications=[
                CampaignChildNotification(
                    issue=63,
                    changes=[
                        CampaignChildChange.ISSUE_STATE,
                        CampaignChildChange.ENDING,
                    ],
                ),
                CampaignChildNotification(
                    issue=68, changes=[CampaignChildChange.REMOVED]
                ),
            ],
            comments=[],
            cursor=None,
            revision="abc123",
            assignment_routes=[],
        ),
    )
    link = (
        '<a class="issue-number" href="https://github.com/{repository}/issues/{issue}"'
        ' target="_blank" rel="noopener noreferrer">#{issue}</a>'
    )
    trigger = (
        f"{link.format(repository=REPOSITORY, issue=63)}: closed, ended; "
        f"{link.format(repository=REPOSITORY, issue=68)}: removed"
    )

    page = render_assignment(state=state, identifier=identifier)
    tail = _read_tail(state=state, identifier=identifier, position="2:0")

    assert f'<span class="round-trigger">{trigger}</span>' in page
    assert f'<span class="round-trigger">{trigger}</span>' in tail.text
    assert "round 2: #63: closed, ended; #68: removed" in page


@pytest.mark.parametrize(
    ("identifier", "kind"),
    [
        ("GH13-20260819-184158-assignment", "assignment"),
        ("GH8-20260819-184158-conversation", "conversation"),
        ("GH60-20260819-184158-campaign", "campaign"),
    ],
)
def test_a_work_page_names_its_kind_and_links_home_to_its_tab(
    identifier, kind, tmp_path
):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    fabricate_everything(state=state, other_rows=fabricate_campaigns(state=state))

    page = render_assignment(state=state, identifier=identifier)

    assert f'<p class="agent-work-kind">{kind}</p>' in page
    assert f'<a class="agent-work-navigation" href="/#{kind}">&lt; home</a>' in page
    assert f'id="{kind}-tab" class="work-tab" href="#{kind}"' in render_home(
        state=state
    )


@pytest.mark.parametrize(
    ("children", "summary"), [(None, "sub-issues unknown"), ([], "no sub-issues")]
)
def test_a_campaign_with_no_children_to_show_says_why_and_shows_no_cards(
    children, summary, tmp_path
):
    state = StateDirectory(root=tmp_path)
    write_running_daemon(state=state)
    campaign_row, *other_rows = fabricate_campaigns(state=state)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            finished=LOOKED_AT,
            rows=[campaign_row.model_copy(update={"children": children}), *other_rows],
        ),
    )

    page = render_home(state=state)
    children_block = page[
        page.index('<details id="GH60-20260819-184158-campaign-children"') :
    ]
    children_block = children_block[: children_block.index("</details>")]

    assert f"<summary>+ {summary}</summary>" in children_block
    assert "<article" not in children_block


def test_a_card_that_appears_within_a_campaign_too_has_an_identifier_for_each(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state, other_rows=fabricate_campaigns(state=state))

    page = render_home(state=state)
    identifiers = re.findall(r'\bid="([^"]+)"', page)

    assert "GH64-20260819-184158-assignment" in identifiers
    assert (
        "GH60-20260819-184158-campaign-GH64-20260819-184158-assignment" in identifiers
    )
    assert len(identifiers) == len(set(identifiers))


def test_requests_whose_labels_differ_only_in_spacing_have_their_own_identifiers(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    write_running_daemon(state=state)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=LOOKED_AT,
            finished=LOOKED_AT,
            rows=[
                *fabricate_campaigns(state=state),
                *(
                    compose_request_row(issue=65, label=label, finding=UNCLAIMED)
                    for label in ("test:cards one", "test:cards-one")
                ),
            ],
        ),
    )

    page = render_home(state=state)
    identifiers = re.findall(r'\bid="([^"]+)"', page)

    assert {
        f"{prefix}request-65-{label}"
        for prefix in ("", "GH60-20260819-184158-campaign-")
        for label in ("test%3Acards%20one", "test%3Acards-one")
    } <= set(identifiers)
    assert len(identifiers) == len(set(identifiers))


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

    page = render_assignment(state=state, identifier="GH13-20260819-184158-assignment")

    assert page.count("<dt>") == 3
    assert "<dt>label</dt><dd>dream:smith</dd>" in page
    assert "<dt>harness</dt><dd>claude</dd>" in page
    assert "<dt>model · effort</dt><dd>opus[1m] · xhigh</dd>" in page
    assert "<dt>assignment</dt>" not in page
    assert "<dt>session</dt>" not in page


def test_an_assignment_with_no_pull_request_yet_says_so_on_its_card_and_page(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_daemon_run(state=state, pid=DAEMON_PID)
    identifier = "GH13-20260819-184158-assignment"
    write_assignment(state=state, identifier=identifier, issue=13, pull_request=None)

    home = render_home(state=state)
    page = render_assignment(state=state, identifier=identifier)

    assert '<span class="pr-chip">no pull request yet</span>' in home
    assert '<span class="pr-chip">no pull request yet</span>' in page
    assert "/pull/" not in page


def test_assignment_page_asks_once_whether_the_daemon_runs(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    probe = MagicMock(wraps=report_module.is_daemon_lock_held)
    monkeypatch.setattr(report_module, "is_daemon_lock_held", probe)

    render_assignment(state=state, identifier="GH13-20260819-184158-assignment")

    probe.assert_called_once_with(path=state.lock)


def test_assignment_page_requests_a_stop_for_its_running_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    client = application.test_client()

    page = client.get(f"/work/{identifier}")

    assert page.status_code == 200
    assert f'action="/work/{identifier}/stop/2"' in page.text

    response = client.post(
        f"/work/{identifier}/stop/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == f"/work/{identifier}"
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    paths = assignment.compose_round_paths(number=2)
    assert paths.stop_request.read_text(encoding="utf-8") == ""
    assert (
        f'action="/work/{identifier}/stop/2"'
        not in client.get(f"/work/{identifier}").text
    )


def test_an_old_assignment_stop_submission_cannot_stop_the_next_round(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/work/{identifier}/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert not assignment.compose_round_paths(number=2).stop_request.exists()


@pytest.mark.parametrize("origin", [None, "https://example.com"])
def test_assignment_stop_requests_must_come_from_the_page(tmp_path, origin):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(f"/work/{identifier}/stop/2", headers=headers)

    assert response.status_code == 403
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert not assignment.compose_round_paths(number=2).stop_request.exists()


def test_assignment_stop_control_needs_a_daemon_and_harness_session(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH60-20260819-184158-assignment"
    directory = write_assignment(
        state=state,
        identifier=identifier,
        issue=60,
        harness_session_identifier=None,
    )
    write_round(directory=directory, number=1, record=compose_running_round(minute=30))

    without_session = render_assignment(state=state, identifier=identifier)

    assert f'action="/work/{identifier}/stop/1"' not in without_session

    release_daemon_lock(path=state.lock)
    without_daemon = render_assignment(
        state=state, identifier="GH13-20260819-184158-assignment"
    )

    assert 'action="/work/GH13-20260819-184158-assignment/stop/2"' not in without_daemon


def test_assignment_tail_updates_the_stop_and_cancel_controls(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    page = client.get(f"/work/{identifier}")

    response = client.get(
        f"/work/{identifier}/tail",
        query_string={"position": _read_position(response=page)},
    )

    assert response.status_code == 200
    assert (
        '<div id="agent-work-foot" class="agent-work-foot" '
        'hx-swap-oob="morph">' in response.text
    )
    assert f'action="/work/{identifier}/stop/2"' in response.text
    assert f'action="/work/{identifier}/cancel"' in response.text


def test_assignment_tail_offers_a_hand_resume_only_while_no_round_runs(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    page = client.get(f"/work/{identifier}")
    query = {"position": _read_position(response=page)}

    working = client.get(f"/work/{identifier}/tail", query_string=query)
    release_daemon_lock(path=state.lock)
    without_daemon = client.get(f"/work/{identifier}/tail", query_string=query)

    assert "<summary>resume by hand</summary>" not in working.text
    assert "<summary>resume by hand</summary>" in without_daemon.text
    assert "claude --resume abc-123" in without_daemon.text


def test_a_stale_assignment_stop_request_is_already_done(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH12-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/work/{identifier}/stop/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert not assignment.compose_round_paths(number=2).stop_request.exists()


def test_an_unknown_assignment_cannot_receive_a_stop_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        "/work/unknown/stop/1",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_assignment_page_cancels_its_assignment(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    page = client.get(f"/work/{identifier}")

    assert f'action="/work/{identifier}/cancel"' in page.text

    response = client.post(
        f"/work/{identifier}/cancel",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == f"/work/{identifier}"
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.ending == AgentWorkEnding(
        at=LOOKED_AT, reason=AgentWorkEndReason.CANCELLED
    )
    assert assignment.compose_round_paths(number=2).stop_request.is_file()


@pytest.mark.parametrize(
    "identifier", ["GH12-20260819-184158-assignment", "GH70-20260819-184158-assignment"]
)
def test_an_ended_assignment_offers_no_cancel_control(tmp_path, identifier):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier=identifier)

    assert "/cancel" not in page


def test_a_cancelled_assignment_still_working_offers_no_cancel_control(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    cancel_assignment(assignment=assignment, at=LOOKED_AT)

    page = render_assignment(state=state, identifier=identifier)

    assert 'class="chip status-working">working</span>' in page
    assert "/cancel" not in page


@pytest.mark.parametrize("origin", [None, "https://example.com"])
def test_assignment_cancels_must_come_from_the_page(tmp_path, origin):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(f"/work/{identifier}/cancel", headers=headers)

    assert response.status_code == 403
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.is_open


def test_a_stale_assignment_cancel_changes_nothing(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH70-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/work/{identifier}/cancel",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.ending == AgentWorkEnding(
        at=PINNED + timedelta(minutes=10), reason=AgentWorkEndReason.CANCELLED
    )


def test_an_unknown_assignment_cannot_be_cancelled(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        "/work/unknown/cancel",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_assignment_page_requests_a_retry_for_its_fault(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH9-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    page = client.get(f"/work/{identifier}")

    assert f'action="/work/{identifier}/retry/2"' in page.text

    response = client.post(
        f"/work/{identifier}/retry/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assert response.location == f"/work/{identifier}"
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.retry_requested_at == LOOKED_AT
    assert (
        f'action="/work/{identifier}/retry/2"'
        not in client.get(f"/work/{identifier}").text
    )


def test_assignment_tail_offers_the_retry_control(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH9-20260819-184158-assignment"

    response = _read_tail(state=state, identifier=identifier, position="1:0")

    assert '<div id="agent-work-retry" hx-swap-oob="morph">' in response.text
    assert f'action="/work/{identifier}/retry/2"' in response.text


@pytest.mark.parametrize(
    ("identifier", "number"),
    [("GH9-20260819-184158-assignment", 1), ("GH12-20260819-184158-assignment", 2)],
)
def test_an_assignment_retry_needs_its_fault_at_the_submitted_round(
    tmp_path, identifier, number
):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        f"/work/{identifier}/retry/{number}",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 303
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.retry_requested_at is None


@pytest.mark.parametrize("origin", [None, "https://example.com"])
def test_assignment_retry_requests_must_come_from_the_page(tmp_path, origin):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH9-20260819-184158-assignment"
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()
    headers = {} if origin is None else {"Origin": origin}

    response = client.post(f"/work/{identifier}/retry/2", headers=headers)

    assert response.status_code == 403
    assignment = find_agent_work(state=state, identifier=identifier)
    assert assignment is not None
    assert assignment.retry_requested_at is None


def test_an_unknown_assignment_cannot_receive_a_retry_request(tmp_path):
    state = StateDirectory(root=tmp_path)
    client = _create_app(state=state, clock=lambda: LOOKED_AT).test_client()

    response = client.post(
        "/work/unknown/retry/2",
        headers={"Origin": "http://localhost"},
    )

    assert response.status_code == 404


def test_a_stopped_round_is_shown_as_stopped(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_assignment_with_rounds(
        state=state,
        issue=61,
        records=[
            AgentRoundRecord(
                number=1,
                started=PINNED,
                pid=1,
                ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=2)),
            )
        ],
    )

    page = render_assignment(state=state, identifier="GH61-20260819-184158-assignment")

    assert 'class="round-outcome outcome-stopped">stopped</span>' in page


def test_a_round_its_gone_daemon_left_unended_is_shown_as_interrupted(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_a_dead_daemon(state=state)
    write_assignment_with_rounds(
        state=state,
        issue=61,
        records=[AgentRoundRecord(number=1, started=PINNED, pid=1)],
    )

    page = render_assignment(state=state, identifier="GH61-20260819-184158-assignment")

    assert 'class="round-outcome outcome-interrupted">interrupted</span>' in page


def test_a_home_card_links_to_its_exact_assignment(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assignment_link = (
        'class="agent-work-open" href="/work/GH13-20260819-184158-assignment" '
        'aria-label="Open assignment GH13-20260819-184158-assignment"'
    )
    assert assignment_link in page
    assert page.count('href="/work/GH13-20260819-184158-assignment"') == 1
    card_start = page.index('<article id="GH13-20260819-184158-assignment"')
    card = page[card_start : page.index("</article>", card_start)]
    assert card.index(assignment_link) < card.index('class="agent-work-detail"')
    assert card.index('class="pr-chip"') > card.index('class="agent-work-detail"')


def test_status_classes_do_not_depend_on_status_wording(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    fabricate_conversation(state=state)
    fabricate_everything(
        state=state,
        other_rows=[
            compose_conversation_row(finding=IssueCommentsFinding(new_comments=0))
        ],
    )

    # A real rewording changes each member's string value, which patching
    # __str__ alone would leave in place, so swap in members that share the
    # names and change the wording.

    reworded = StrEnum(
        "reworded",
        {status.name: f"reworded {status}" for status in AgentWorkStatusValue},
    )

    compose_home_view = web_app_module.compose_home_view
    compose_agent_live_state = web_app_module.compose_agent_live_state

    def reword_home_view(**kwargs):
        view = compose_home_view(**kwargs)
        return replace(
            view,
            sections=tuple(
                replace(
                    section,
                    active=tuple(
                        replace(card, status=reworded[card.status.name])
                        for card in section.active
                    ),
                )
                for section in view.sections
            ),
        )

    def reword_agent_live_state(**kwargs):
        live = compose_agent_live_state(**kwargs)
        return replace(live, status=reworded[live.status.name])

    monkeypatch.setattr(web_app_module, "compose_home_view", reword_home_view)
    monkeypatch.setattr(
        web_app_module, "compose_agent_live_state", reword_agent_live_state
    )

    home = render_home(state=state)
    assignment_page = render_assignment(
        state=state, identifier="GH20-20260819-184158-assignment"
    )
    conversation_page = render_conversation(state=state, issue=8)
    card_start = home.index('<article id="GH20-20260819-184158-assignment"')
    card = home[card_start : home.index("</article>", card_start)]
    conversation_start = home.index('<article id="GH8-20260819-184158-conversation"')
    conversation_card = home[
        conversation_start : home.index("</article>", conversation_start)
    ]

    assert '<span class="chip status-idle">reworded idle</span>' in card
    assert '<span class="chip status-idle">reworded idle</span>' in conversation_card
    assert (
        '<span id="agent-work-status" class="chip status-idle">reworded idle</span>'
    ) in assignment_page
    assert (
        '<span id="agent-work-status" class="chip status-idle">reworded idle</span>'
    ) in conversation_page


def test_an_idle_assignment_status_uses_the_status_wording(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(
        state=state,
        identifier="GH20-20260819-184158-assignment",
    )

    assert ('<span id="agent-work-status" class="chip status-idle">idle</span>') in page
    assert "[IDLE]" not in page


def test_assignment_page_polls_its_tail_from_the_last_complete_line(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH13-20260819-184158-assignment"
    feed_path = _find_feed_path(state=state, identifier=identifier, number=2)

    page = render_assignment(state=state, identifier=identifier)

    assert f'id="position" name="position" value="2:{feed_path.stat().st_size}"' in page
    assert (
        f'id="records" class="feed-records" '
        f'hx-get="/work/{identifier}/tail" hx-trigger="every 2s" '
        'hx-include="#position" hx-select=".feed-round" hx-swap="beforeend"' in page
    )


def test_assignment_page_before_its_first_round_starts_at_the_first_position(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(
        state=state,
        identifier="GH44-20260819-184158-assignment",
    )

    assert 'id="position" name="position" value="0:0"' in page
    assert '<p id="empty-feed" class="empty">-- no feed yet --</p>' in page


def test_assignment_page_ids_are_unique(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(
        state=state,
        identifier="GH13-20260819-184158-assignment",
    )
    identifiers = re.findall(r'\bid="([^"]+)"', page)

    assert len(identifiers) == len(set(identifiers))


def test_agent_work_script_follows_only_when_the_feed_was_at_its_end(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/static/agent-work.js")
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
    assert 'agentWorkSidebar.addEventListener("click"' in script
    assert 'currentRoundLink?.setAttribute("aria-current", "true")' in script
    assert "focusedRoundLink?.focus({ preventScroll: true })" in script


def test_ended_assignment_cards_are_separated_by_rules(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    stylesheet = (
        application.test_client().get("/static/matrix.css").get_data(as_text=True)
    )

    ended = page[page.index('<details class="ended-work">') :]
    assert 'class="agent-work-card"' in ended
    assert re.search(
        r"\.agent-work-card,[^{]*\{[^}]*border-bottom: var\(--line\) solid",
        stylesheet,
        re.DOTALL,
    )


def test_ended_assignments_are_ordered_by_when_they_ended(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_daemon_run(state=state, pid=DAEMON_PID)
    write_assignment_with_rounds(
        state=state,
        issue=10,
        records=[
            compose_ended_round(minute=1),
            compose_ended_round(minute=2, number=2),
        ],
        round_inputs={2: MERGED_INPUT},
    )
    write_assignment_with_rounds(
        state=state,
        issue=20,
        records=[
            compose_ended_round(minute=1),
            compose_ended_round(minute=20, number=2),
        ],
        round_inputs={2: MERGED_INPUT},
    )
    write_assignment_with_rounds(
        state=state, issue=30, records=[compose_ended_round(minute=1)]
    )
    cancel_assignment(
        assignment=read_agent_work_at_issue(state=state, issue=30)[0],
        at=PINNED + timedelta(minutes=10),
    )

    page = render_home(state=state)

    assert (
        "Assign an issue to yourself and label it with "
        "dream:smith to create an assignment." in page
    )
    assert "+ 3 ended</summary>" in page
    assert page.index('id="GH20-') < page.index('id="GH30-') < page.index('id="GH10-')


def test_home_page_types_replaced_assignment_output(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
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
        identifier="GH13-20260819-184158-assignment",
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
        'target="_blank" rel="noopener noreferrer">dreamcatcher '
        "v3.0.0.beta1</a>" in page
    )
    assert ">Docs</a>" not in page


def test_a_stopped_daemon_does_not_link_its_status_to_the_documentation(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_a_dead_daemon(state=state)

    page = render_home(state=state)

    assert 'class="docs-link"' not in page


def test_every_complete_page_uses_the_dreamcatcher_mark_as_its_favicon(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    app = _create_app(state=state)

    pages = (
        render_home(state=state),
        render_assignment(state=state, identifier="GH13-20260819-184158-assignment"),
        app.test_client().get("/work/unknown").text,
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
    assert 'data-web-theme="matrix"' in selected.text
    assert "theme=matrix;" in selected.headers["Set-Cookie"]
    assert 'href="/static/nature.css"' not in remembered.text
    assert 'src="/static/nature.js"' not in remembered.text
    assert 'href="/static/dreamcatcher-mark-phosphor.png"' in remembered.text
    assert 'data-web-theme="matrix"' in remembered.text


def test_an_unknown_theme_uses_nature_without_being_remembered(tmp_path):
    app = _create_app(state=StateDirectory(root=tmp_path))
    client = app.test_client()

    response = client.get("/?theme=unknown")
    stylesheet = client.get("/static/nature.css").get_data(as_text=True)

    assert 'href="/static/nature.css"' in response.text
    assert 'src="/static/nature.js"' in response.text
    assert 'href="/static/dreamcatcher-mark-ink.png"' in response.text
    assert 'data-web-theme="nature"' in response.text
    assert "Set-Cookie" not in response.headers
    assert "circle at var(--sun-x) 6%" in stylesheet
    assert "opacity: var(--sun-opacity);" in stylesheet
    assert ".status-unknown," in stylesheet


def test_github_links_open_in_a_new_tab(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    pages = render_home(state=state) + render_assignment(
        state=state, identifier="GH13-20260819-184158-assignment"
    )
    links = re.findall(r'<a [^>]*href="https://github\.com/[^>]+>', pages)

    assert links
    assert all('target="_blank" rel="noopener noreferrer"' in link for link in links)


def test_links_to_dreamcatcher_pages_stay_in_the_same_tab(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    pages = render_home(state=state) + render_assignment(
        state=state, identifier="GH13-20260819-184158-assignment"
    )
    links = re.findall(r'<a [^>]*href="[/?#][^>]*>', pages)

    assert any('href="/work/' in link for link in links)
    assert not any("target=" in link for link in links)


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

    response = application.test_client().get("/work/GH99-20260819-184158-assignment")

    assert response.status_code == 404
    assert (
        "No agent work here has identifier GH99-20260819-184158-assignment."
        in response.get_data(as_text=True)
    )


def test_an_unknown_assignment_tail_renders_a_404_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()

    response = _read_tail(
        state=state,
        identifier="GH99-20260819-184158-assignment",
        position="0:0",
    )

    assert response.status_code == 404
    assert (
        "No agent work here has identifier GH99-20260819-184158-assignment."
        in response.text
    )


@pytest.mark.parametrize(
    "position",
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
def test_an_invalid_tail_position_renders_a_400_page(tmp_path, position):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_assignment_with_rounds(state=state, issue=60, records=[])

    response = _read_tail(
        state=state,
        identifier="GH60-20260819-184158-assignment",
        position=position,
    )

    assert response.status_code == 400
    assert "The feed position is invalid." in response.text


@pytest.mark.parametrize("position", [1, 99])
def test_a_tail_position_must_follow_a_complete_line(tmp_path, position):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = write_assignment_with_rounds(
        state=state, issue=60, records=[compose_running_round(minute=1)]
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=LOOKED_AT, text="one line")],
    )

    response = _read_tail(
        state=state,
        identifier="GH60-20260819-184158-assignment",
        position=f"1:{position}",
    )

    assert response.status_code == 400
    assert "The feed position is invalid." in response.text


def test_a_tail_before_any_round_opens_the_first_round_when_it_arrives(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = write_assignment_with_rounds(state=state, issue=60, records=[])
    identifier = "GH60-20260819-184158-assignment"

    waiting = _read_tail(state=state, identifier=identifier, position="0:0")

    assert waiting.status_code == 200
    assert 'value="0:0"' in waiting.text
    assert "round 1:" not in waiting.text

    write_round(directory=directory, number=1, record=compose_running_round(minute=1))
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=LOOKED_AT, text="the first line")],
    )
    started = _read_tail(state=state, identifier=identifier, position="0:0")

    assert started.status_code == 200
    assert started.text.count("round 1: start") == 1
    assert "the first line" in started.text
    assert 'id="empty-feed" hx-swap-oob="delete"' in started.text
    assert _read_position(response=started).startswith("1:")


def test_a_tail_returns_only_complete_lines_after_its_position(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = write_assignment_with_rounds(
        state=state, issue=60, records=[compose_running_round(minute=1)]
    )
    identifier = "GH60-20260819-184158-assignment"
    first = FeedLine(at=LOOKED_AT, text="the first line")
    second = FeedLine(at=LOOKED_AT, text="the second line")
    write_feed(directory=directory, number=1, lines=[first])

    first_read = _read_tail(state=state, identifier=identifier, position="1:0")
    position = _read_position(response=first_read)
    feed_path = _find_feed_path(state=state, identifier=identifier, number=1)
    append_text(text=second.render().removesuffix("\n"), path=feed_path)
    incomplete_read = _read_tail(
        state=state,
        identifier=identifier,
        position=position,
    )

    assert "the first line" in first_read.text
    assert "the second line" not in first_read.text
    assert 'id="empty-feed"' not in first_read.text
    assert "the second line" not in incomplete_read.text
    assert _read_position(response=incomplete_read) == position

    append_text(text="\n", path=feed_path)
    complete_read = _read_tail(
        state=state,
        identifier=identifier,
        position=position,
    )

    assert "the first line" not in complete_read.text
    assert "the second line" in complete_read.text
    assert '<div hx-swap-oob="beforeend:#feed-round-1">' in complete_read.text
    assert _read_position(response=complete_read) != position


def test_an_ended_round_moves_to_the_next_round_after_an_empty_read(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = write_assignment_with_rounds(
        state=state,
        issue=60,
        records=[
            compose_ended_round(minute=1),
            compose_running_round(minute=10, number=2),
        ],
    )
    identifier = "GH60-20260819-184158-assignment"
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
    first_feed = _find_feed_path(state=state, identifier=identifier, number=1)

    response = _read_tail(
        state=state,
        identifier=identifier,
        position=f"1:{first_feed.stat().st_size}",
    )

    assert response.status_code == 200
    assert "already read" not in response.text
    assert response.text.count("round 2: start") == 1
    assert "new round output" in response.text
    assert _read_position(response=response).startswith("2:")


def test_a_terminal_tail_returns_late_output_before_it_stops(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    identifier = "GH12-20260819-184158-assignment"
    feed_path = _find_feed_path(state=state, identifier=identifier, number=2)
    append_text(
        text=FeedLine(at=LOOKED_AT, text="late output").render(),
        path=feed_path,
    )

    output = _read_tail(state=state, identifier=identifier, position="2:0")
    stopped = _read_tail(
        state=state,
        identifier=identifier,
        position=_read_position(response=output),
    )

    assert output.status_code == 200
    assert "late output" in output.text
    assert stopped.status_code == 286


def test_a_faulted_tail_keeps_polling_when_it_reads_nothing_new(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = _find_feed_path(
        state=state, identifier="GH9-20260819-184158-assignment", number=2
    )

    response = _read_tail(
        state=state,
        identifier="GH9-20260819-184158-assignment",
        position=f"2:{feed.stat().st_size}",
    )

    assert response.status_code == 200


def test_a_tail_fragment_matches_its_golden(tmp_path, pytestconfig):
    state = StateDirectory(root=tmp_path)
    fabricate_a_silent_round(state=state)
    identifier = "GH13-20260819-184158-assignment"
    first_feed = _find_feed_path(state=state, identifier=identifier, number=1)
    response = _read_tail(
        state=state,
        identifier=identifier,
        position=f"1:{first_feed.stat().st_size}",
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
    write_assignment_with_rounds(
        state=state, issue=60, records=[compose_running_round(minute=1)]
    )

    response = _read_tail(
        state=state,
        identifier="GH60-20260819-184158-assignment",
        position="1:0",
    )

    assert response.text.startswith(
        '<input type="hidden" id="position" name="position" value="1:0" '
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

    page = render_assignment(state=state, identifier="GH10-20260819-184158-assignment")

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
        r"\.agent-work-heading \{[^}]*display: grid;"
        r"[^}]*grid-template-columns: minmax\(0, 1fr\) max-content;"
        r"[^}]*align-items: start;",
        stylesheet,
        re.DOTALL,
    )
    assert re.search(
        r"\.agent-work-heading h1 \{[^}]*min-width: 0;", stylesheet, re.DOTALL
    )
    assert re.search(
        r"\.agent-work-heading-actions \{[^}]*flex-wrap: nowrap;",
        stylesheet,
        re.DOTALL,
    )


def test_assignment_rounds_link_to_the_feed_in_ascending_order(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH13-20260819-184158-assignment")
    round_links = re.findall(
        r'class="round-link" href="#feed-round-(\d+)"[^>]*>\s*'
        r'<span class="round-number">(\d+)</span>',
        page,
    )

    assert round_links == [("1", "01"), ("2", "02")]
    assert 'class="agent-work-workspace"' in page
    assert 'class="feed-records"' in page
    assert 'src="/static/agent-work.js"' in page


def test_an_errored_rounds_style_uses_its_outcome_alone(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH35-20260819-184158-assignment")

    assert 'class="round-outcome outcome-errored">errored (exit 2)</span>' in page


def test_hand_resume_command_is_collapsed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH9-20260819-184158-assignment")
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    stylesheet = (
        application.test_client().get("/static/matrix.css").get_data(as_text=True)
    )

    assert '<details class="hand-resume">' in page
    assert "<summary>resume by hand</summary>" in page
    assert "escape hatch" not in page
    assert 'class="panel resume-command"' not in page
    assert "font-size: 0.9em;" in stylesheet


def test_assignment_page_offers_a_control_that_jumps_to_the_feed_tail(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment(state=state, identifier="GH13-20260819-184158-assignment")
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    response = application.test_client().get("/static/agent-work.js")
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

    page = render_assignment(state=state, identifier="GH10-20260819-184158-assignment")

    assert '<strong class="agent-work-issue">#10' in page
    assert '<span class="pr-chip">PR #52 draft</span>' in page


def test_an_assignment_page_reports_a_repository_record_that_will_not_read(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    state.repository.unlink()
    state.repository.mkdir()
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )

    response = application.test_client().get("/work/GH13-20260819-184158-assignment")

    assert response.status_code == 500
    assert "cannot read" in response.get_data(as_text=True)


def test_the_assignment_page_preserves_and_escapes_an_unparseable_feed_line(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = state.work / "GH13-20260819-184158-assignment" / "rounds" / "2" / "feed.txt"
    append_text(text="<script>alert('no')</script>\n", path=feed)

    page = render_assignment(state=state, identifier="GH13-20260819-184158-assignment")

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
    feed = state.work / "GH13-20260819-184158-assignment" / "rounds" / "2" / "feed.txt"
    line = FeedLine(at=LOOKED_AT, text="<script>alert('no')</script>")
    append_text(text=line.render(), path=feed)

    page = render_home(state=state)

    assert "&lt;script&gt;alert(&#39;no&#39;)&lt;/script&gt;" in page
    assert "<script>alert('no')</script>" not in page


def test_the_home_page_displays_a_worktree_marker_literally(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    feed = state.work / "GH13-20260819-184158-assignment" / "rounds" / "2" / "feed.txt"
    line = FeedLine(at=LOOKED_AT, text="[Bash] cd <worktree>/src")
    append_text(text=line.render(), path=feed)

    page = render_home(state=state)

    assert "cd &lt;worktree&gt;/src" in page


def test_issue_and_pull_request_numbers_link_to_github_with_hash_notation(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    issue_url = f"https://github.com/{REPOSITORY}/issues/50"
    pull_request_url = f"https://github.com/{REPOSITORY}/pull/61"
    github_attributes = 'target="_blank" rel="noopener noreferrer"'
    assert f'href="{issue_url}" {github_attributes}>#50</a>' in page
    assert (
        '<span class="chip status-blocked"><span>blocked by '
        f'<a class="issue-number" href="{issue_url}" '
        f"{github_attributes}>#50</a></span></span>" in page
    )
    assert (
        '<span class="chip status-blocked"><span>claimed by '
        f'<a class="issue-number" href="{pull_request_url}" '
        f"{github_attributes}>#61</a>; blocked by" in page
    )
    assert (
        f'{github_attributes}>#50</a>, <a class="issue-number" '
        'href="https://github.com/alimanfoo/dream/issues/1016" '
        f"{github_attributes}>alimanfoo/dream#1016</a></span></span>" in page
    )
    assert (
        '<span class="chip status-routing-conflict"><span>multiple assignment '
        "labels: dream:less, dream:smith</span></span>" in page
    )


def test_a_pull_request_links_to_github_before_its_state_is_observed(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    pull_request_url = f"https://github.com/{REPOSITORY}/pull/52"
    assert (
        f'href="{pull_request_url}" target="_blank" '
        'rel="noopener noreferrer">PR #52</a>' in page
    )


def test_dashboard_groups_assignment_requests_with_assignments(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert page.index('id="assignment-panel"') < page.index(
        'id="request-50-dream%3Asmith"'
    )
    assert 'id="issue-tab"' not in page
    assert 'id="conversation-tab"' not in page


def test_a_scheduler_failure_is_listed_apart_from_the_facts(tmp_path):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS["at-cap"](state=state)

    page = render_home(state=state)

    facts = page[page.index('<dl class="facts">') : page.index("</dl>")]
    failures = page[page.index('<section class="scheduler-failures"') :]
    assert "<dt>agent capacity</dt>" in facts
    assert "scheduler failures" not in facts
    assert failures.count("<li>") == 1
    assert "<li>could not list issues: " in failures


def test_next_update_is_left_out_when_no_daemon_is_running(tmp_path):
    state = StateDirectory(root=tmp_path)
    WEB_STATUS_REPORTS["nothing"](state=state)

    page = render_home(state=state)

    assert "<dt>next update</dt>" not in page


def test_a_running_update_pulses_and_a_countdown_does_not(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    counting_down = render_home(state=state)
    write_tick(state=state, tick=SchedulerRecord(at=PINNED, finished=PINNED))
    updating = render_home(state=state)

    assert "in-progress" not in counting_down
    assert '<div class="fact in-progress">' in updating
    assert "<dd>updating</dd>" in updating


def test_an_active_cooldown_is_a_warning_fact(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            finished=PINNED,
            cooldown=GlobalCooldown(
                started=LOOKED_AT, ends=LOOKED_AT + timedelta(minutes=15)
            ),
        ),
    )

    page = render_home(state=state)

    assert page.count('<div class="fact warning">') == 1
    assert "<dt>global cooldown</dt>" in page
    assert "<dd>ends in 15m</dd>" in page
    assert "scheduler-failures" not in page


def test_an_inactive_cooldown_is_not_shown(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_home(state=state)

    assert "global cooldown" not in page


def test_pull_request_summary_remains_without_a_repository_record(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_titles_and_pull_request_states(state=state)
    state.repository.unlink()

    page = render_home(state=state)

    for pull_request_summary in (
        "draft",
        "ready",
        "merged",
        "closed",
        "ready, behind main, checks running",
        "ready, checks failing",
    ):
        assert f'<span class="pr-chip">PR #52 {pull_request_summary}</span>' in page


def test_a_record_that_will_not_read_renders_an_error_page(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)
    record = state.work / "GH13-20260819-184158-assignment" / "work.json"
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


def test_the_background_web_server_opens_for_its_context(tmp_path, capsys):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    opened = []

    with serve_web_in_background(state=state, browser_opener=opened.append):
        address = opened[0]
        assert capsys.readouterr().out == f"{address}\n"

    assert opened == [address]


def test_a_web_address_that_cannot_be_written_is_reportable(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    monkeypatch.setattr("builtins.print", MagicMock(side_effect=OSError("closed")))

    with pytest.raises(ReportableError, match="Could not write the web address"):
        serve_web(
            state=state,
            port=0,
            browser_opener=lambda address: None,
            server_runner=lambda *, server: None,
        )


def test_a_browser_that_cannot_open_is_reportable(tmp_path):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()

    def refuse(address, /):
        raise OSError("no browser")

    with pytest.raises(ReportableError, match="Could not open the web interface"):
        serve_web(
            state=state,
            port=0,
            browser_opener=refuse,
            server_runner=lambda *, server: None,
        )


def test_the_background_server_starts_before_the_browser_opens(tmp_path, monkeypatch):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    events = []

    @contextmanager
    def run_in_background(*, server):
        events.append("serving")
        try:
            yield
        finally:
            events.append("stopped")

    def open_browser(address, /):
        assert events == ["serving"]
        events.append("opened")

    monkeypatch.setattr(
        web_app_module,
        "run_web_server_in_background",
        run_in_background,
    )

    with serve_web_in_background(state=state, browser_opener=open_browser):
        assert events == ["serving", "opened"]

    assert events == ["serving", "opened", "stopped"]


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
    assert web_server_module._ExclusiveWebServer.daemon_threads is True
    assert web_server_module._ExclusiveWebServer.multithread is True


def test_the_default_server_runner_serves_forever():
    server = MagicMock()

    web_server_module.run_web_server(server=server)

    server.serve_forever.assert_called_once_with()


def test_a_background_server_runs_until_its_context_ends():
    server_started = Event()
    server_stopped = Event()
    server_finished = Event()
    server = MagicMock()

    def serve_forever():
        server_started.set()
        server_stopped.wait(timeout=1)
        server_finished.set()

    server.serve_forever.side_effect = serve_forever
    server.shutdown.side_effect = server_stopped.set

    with run_web_server_in_background(server=server):
        assert server_started.wait(timeout=1)

    assert server_stopped.is_set()
    assert server_finished.is_set()
    server.shutdown.assert_called_once_with()
    server.server_close.assert_called_once_with()


def test_a_background_server_stops_when_its_action_fails():
    server_started = Event()
    server_stopped = Event()
    server_finished = Event()
    server = MagicMock()

    def serve_forever():
        server_started.set()
        server_stopped.wait(timeout=1)
        server_finished.set()

    def fail():
        assert server_started.wait(timeout=1)
        raise ReportableError("the daemon failed")

    server.serve_forever.side_effect = serve_forever
    server.shutdown.side_effect = server_stopped.set

    with (
        pytest.raises(ReportableError, match="the daemon failed"),
        run_web_server_in_background(server=server),
    ):
        fail()

    assert server_stopped.is_set()
    assert server_finished.is_set()
    server.shutdown.assert_called_once_with()
    server.server_close.assert_called_once_with()


def test_a_background_server_failure_reaches_its_caller(monkeypatch):
    notified = Event()
    server = MagicMock()
    server.serve_forever.side_effect = OSError("socket failed")
    monkeypatch.setattr(web_server_module, "interrupt_main", notified.set)

    with (
        pytest.raises(ReportableError, match="web server failed"),
        run_web_server_in_background(server=server),
    ):
        assert notified.wait(timeout=1)

    server.server_close.assert_called_once_with()


def test_a_background_server_that_returns_is_a_failure(monkeypatch):
    notified = Event()
    server = MagicMock()
    monkeypatch.setattr(web_server_module, "interrupt_main", notified.set)

    with (
        pytest.raises(ReportableError, match="stopped unexpectedly"),
        run_web_server_in_background(server=server),
    ):
        assert notified.wait(timeout=1)

    server.server_close.assert_called_once_with()


def test_a_background_server_that_already_ended_stops_at_once(monkeypatch):
    notified = Event()
    server = make_server(web_server_module.WEB_HOST, 0, lambda environ, start: [])
    monkeypatch.setattr(web_server_module, "interrupt_main", notified.set)

    def end_serving():
        server.shutdown()
        assert notified.wait(timeout=1)

    with (
        pytest.raises(ReportableError, match="stopped unexpectedly"),
        run_web_server_in_background(server=server),
    ):
        end_serving()


def test_a_background_thread_that_cannot_start_still_closes_the_server(monkeypatch):
    thread = MagicMock()
    thread.start.side_effect = RuntimeError("cannot start")
    thread.ident = None
    server = MagicMock()
    monkeypatch.setattr(
        web_server_module,
        "Thread",
        lambda *, target: thread,
    )

    with (
        pytest.raises(RuntimeError, match="cannot start"),
        run_web_server_in_background(server=server),
    ):
        raise AssertionError("unreachable")

    server.shutdown.assert_not_called()
    server.server_close.assert_called_once_with()
