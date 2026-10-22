"""Read local status for campaigns."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from records import (
    compose_campaign_identifier,
    hold_daemon_lock_for_test,
    read_campaign,
    write_campaign,
    write_daemon_run,
    write_ending,
    write_round,
    write_tick,
)
from rows import request_row

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
    _AgentRoundEnding,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWorkEndReason
from dreamcatcher.campaigns import CampaignRoundInput
from dreamcatcher.github import IssueComment
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.scheduler.models import (
    CampaignFinding,
    PauseCause,
    PausedFinding,
    RequestFinding,
    SchedulerRecord,
    StartedRound,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AgentWorkStatus,
    AgentWorkStatusValue,
    RequestReason,
    read_agent_work_status,
    read_dreamcatcher_daemon_status,
    read_status_report,
)
from dreamcatcher.status.requests import RequestStatusValue

LOOKED_AT = PINNED + timedelta(hours=2)
PARENT = 20
ERRORED = _compose_agent_round_ending(at=PINNED + timedelta(minutes=4), status=2)
SUCCESSFUL = SuccessfulAgentRoundEnding(at=PINNED + timedelta(minutes=3))
NOTHING_NEW = CampaignFinding(new_comments=0)


@pytest.fixture
def state(tmp_path):
    """Return local state written by a running daemon, holding one campaign."""
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    hold_daemon_lock_for_test(path=state.lock)
    write_campaign(state=state, issue=PARENT)
    return state


def lead_round(
    *,
    state: StateDirectory,
    number: int,
    ending: _AgentRoundEnding | None,
    revision: str | None = "abc123",
    comments: int = 0,
) -> None:
    """Write one round of the campaign, given that many comments at the revision."""
    given = [
        IssueComment(
            id=identifier,
            author="alimanfoo",
            written_at="2026-09-23T01:00:00Z",
            body="Carry on.",
        )
        for identifier in range(1, comments + 1)
    ]
    write_round(
        directory=state.work / compose_campaign_identifier(issue=PARENT),
        number=number,
        record=AgentRoundRecord(
            number=number, started=PINNED + timedelta(minutes=number), ending=ending
        ),
        round_input=(
            None
            if revision is None
            else CampaignRoundInput(
                issue=PARENT,
                children=[],
                comments=given,
                cursor=(
                    IssueCommentCursor(written_at=given[-1].written_at, id=given[-1].id)
                    if given
                    else None
                ),
                revision=revision,
                assignment_routes=[],
            )
        ),
    )


def observe(
    *,
    state: StateDirectory,
    finding: RequestFinding | None,
    ended_round: int | None = None,
    started_round: StartedRound | None = None,
) -> None:
    """Write a tick that saw the campaign with this finding."""
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=PARENT,
                    kind=AgentWorkKind.CAMPAIGN,
                    agent_work_identifier=compose_campaign_identifier(issue=PARENT),
                    ended_round=ended_round,
                    finding=finding,
                    started_round=started_round,
                )
            ],
        ),
    )


def campaign_status(*, state: StateDirectory) -> AgentWorkStatus:
    """Return the status of the campaign at the parent."""
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    return read_agent_work_status(
        state=state,
        work=campaign,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=lambda: LOOKED_AT,
    )


def test_a_labelled_parent_with_no_campaign_yet_is_available(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=PARENT, kind=AgentWorkKind.CAMPAIGN, finding=NOTHING_NEW
                )
            ],
        ),
    )

    [request] = read_status_report(
        state=state, clock=lambda: LOOKED_AT
    ).list_request_statuses(kind=AgentWorkKind.CAMPAIGN)

    assert request.value is RequestStatusValue.AVAILABLE
    assert request.reasons == (RequestReason(words="available"),)


def test_a_campaign_whose_lead_has_not_run_is_waiting(state):
    observe(state=state, finding=NOTHING_NEW)

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "no round has run yet"


def test_a_running_lead_is_working_on_its_start(state):
    lead_round(state=state, number=1, ending=None)
    observe(state=state, finding=NOTHING_NEW, started_round=StartedRound(number=1))

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WORKING
    assert status.detail.startswith("round 1, start, running ")


@pytest.mark.parametrize(
    ("ending", "detail"),
    [
        (SUCCESSFUL, "round 1, successful, ran 2m"),
        (
            StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=2)),
            "round 1, stopped, ran 1m",
        ),
    ],
)
def test_a_lead_that_took_its_turn_is_idle_with_how_its_round_ended(
    state, ending, detail
):
    lead_round(state=state, number=1, ending=ending)
    observe(state=state, finding=NOTHING_NEW, ended_round=1)

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == detail


def test_a_lead_that_finished_after_the_update_started_it_awaits_the_next(state):
    lead_round(state=state, number=1, ending=SUCCESSFUL)
    observe(state=state, finding=NOTHING_NEW, started_round=StartedRound(number=1))

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "round 1 ended, awaiting next update"


def test_a_lead_with_new_parent_comments_is_waiting_to_answer_them(state):
    lead_round(
        state=state,
        number=1,
        ending=StoppedAgentRoundEnding(at=PINNED + timedelta(minutes=2)),
    )
    observe(state=state, finding=CampaignFinding(new_comments=2), ended_round=1)

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "2 comments to answer"


def test_a_lead_whose_round_did_not_finish_waits_to_recover(state):
    lead_round(state=state, number=1, ending=InterruptedAgentRoundEnding())
    observe(state=state, finding=NOTHING_NEW, ended_round=1)

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.WAITING
    assert status.detail == "round 1 interrupted"


def test_a_paused_campaign_is_idle_and_says_why(state):
    lead_round(state=state, number=1, ending=InterruptedAgentRoundEnding())
    observe(
        state=state,
        finding=PausedFinding(cause=PauseCause.LABEL_REMOVED),
        ended_round=1,
    )

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.IDLE
    assert status.detail == "paused, label removed"


def test_two_errored_lead_rounds_are_a_fault(state):
    lead_round(state=state, number=1, ending=ERRORED)
    lead_round(state=state, number=2, ending=ERRORED)
    observe(state=state, finding=None, ended_round=2)

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.FAULT
    assert status.faulted_round_number == 2


def test_a_campaign_whose_parent_closed_has_ended(state):
    lead_round(state=state, number=1, ending=SUCCESSFUL)
    write_ending(
        directory=state.work / compose_campaign_identifier(issue=PARENT),
        reason=AgentWorkEndReason.ISSUE_CLOSED,
        at=LOOKED_AT,
    )

    status = campaign_status(state=state)

    assert status.value is AgentWorkStatusValue.ENDED
    assert status.detail == "issue closed"


def test_lead_rounds_name_their_trigger_and_the_revision_of_main_they_were_given(
    state,
):
    lead_round(state=state, number=1, ending=ERRORED, revision="abc123", comments=1)
    lead_round(state=state, number=2, ending=SUCCESSFUL, revision="def456", comments=1)
    lead_round(state=state, number=3, ending=SUCCESSFUL, revision="def456", comments=2)
    lead_round(state=state, number=4, ending=None, revision=None)

    rounds = campaign_status(state=state).round_statuses

    assert [round_status.trigger_description for round_status in rounds] == [
        "start, 1 comment",
        "recover, 1 comment",
        "2 comments",
        "comments",
    ]
    assert [
        None if round_status.revision is None else round_status.revision.description
        for round_status in rounds
    ] == [
        "code revision abc123",
        "code revision abc123 -> def456",
        "code revision def456 (unchanged)",
        None,
    ]
