"""Scheduling of campaigns, from a parent's label to its closure."""

import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from clocks import PINNED, Ticking
from conftest import (
    CAMPAIGN_CLAUDE,
    POSTED_BY,
    REPOSITORY,
    comment,
    commit,
    configure,
    git,
    pages,
    streamed,
)
from fakes import Line
from records import (
    compose_campaign_identifier,
    read_campaign,
    write_assignment,
    write_campaign,
    write_round,
)
from rows import request_row

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundRecord,
    HarnessErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import AgentWorkEndReason, request_agent_work_retry
from dreamcatcher.campaigns import CampaignRoundInput
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import read_json
from dreamcatcher.git import _read_worktree_revision
from dreamcatcher.github import IssueComment
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import AGENT_POST_MARKER
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.models import (
    CampaignFinding,
    ConflictingLabelsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    RequestFinding,
    RequestRow,
    StartedRound,
)
from dreamcatcher.state import StateDirectory

PARENT = 20
LABEL = "dream:lead"
COMMENTS_PATH = f"api repos/{REPOSITORY}/issues/{PARENT}/comments?per_page=100"
SECOND_CAMPAIGN_CLAUDE = CAMPAIGN_CLAUDE.replace("dream:lead", "dream:steward")
CONVERSATION_CLAUDE = """[[conversation]]
label = "dream:conversation"
[conversation.claude]
prompt = "/dream:conversation GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""
CODEX_CAMPAIGN = """[[campaign]]
label = "dream:lead"
[campaign.codex]
prompt = "Acknowledge GH{issue} with a comment on it."
model = "gpt-5.6-sol"
effort = "xhigh"
"""


def create_scheduler(*, root, harness: AgentHarness = AgentHarness.CLAUDE):
    """Create the scheduler for the repository at root."""
    return Scheduler(
        context=SchedulingContext(
            repository=REPOSITORY,
            account=POSTED_BY,
            config=read_dreamcatcher_config(root=root),
            state=StateDirectory(root=root),
            clock=Ticking(step=300),
        ),
        preferred_harness=harness,
        rounds={},
    )


@pytest.fixture
def campaign_scheduler(cloned, gh):
    """Return a scheduler routing the campaign label, and stop what it leaves."""
    configure(root=cloned, head=CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=cloned)
    yield scheduler, gh
    for running in scheduler.rounds.values():
        running.interrupt()


def tick(*, scheduler: Scheduler):
    """Run one tick at the scheduler's clock."""
    return scheduler.tick(at=scheduler.context.clock())


def parent_issue(
    *,
    labels: tuple[str, ...] = (LABEL,),
    state: str = "OPEN",
    assignees: tuple[str, ...] = (POSTED_BY,),
    number: int = PARENT,
) -> dict:
    """Return what GitHub holds of a parent issue."""
    return {
        "number": number,
        "title": f"Parent {number}",
        "body": "Carry the stages through.",
        "createdAt": "2026-09-22T01:00:00Z",
        "state": state,
        "assignees": [{"login": login} for login in assignees],
        "labels": [{"name": name} for name in labels],
    }


def list_parents(*, gh, label: str = LABEL, issues: list[dict]) -> None:
    """Have GitHub list these issues under the label."""
    gh.replies(
        stdout=json.dumps(issues),
        to=f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} --label {label}",
    )


def show_parent(*, gh, issue: dict) -> None:
    """Have GitHub answer a read of the parent with this."""
    gh.replies(
        stdout=json.dumps(issue),
        to=(
            f"issue view {issue['number']} --repo {REPOSITORY} "
            "--json number,title,body,createdAt,state,assignees,labels"
        ),
    )


def offer_parent(*, gh, issue: dict | None = None) -> None:
    """Have GitHub list the parent under the campaign label and show it."""
    issue = parent_issue() if issue is None else issue
    list_parents(gh=gh, issues=[issue])
    show_parent(gh=gh, issue=issue)


def lead(*, harnesses, status: int = 0, delay: float = 0) -> None:
    """Have Claude identify the lead's session and finish its turn."""
    harnesses["claude"].streams(
        lines=[
            Line(
                text=streamed(
                    type="system",
                    subtype="init",
                    model="claude-opus-5",
                    session_id="lead-session",
                )
                + "\n"
            ),
            Line(
                text=streamed(
                    type="result",
                    subtype="success",
                    is_error=False,
                    result="Acknowledged the parent.",
                    total_cost_usd=0.0,
                    usage={
                        "output_tokens": 1,
                        "input_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                )
                + "\n"
            ),
        ],
        status=status,
        delay=delay,
    )


def campaign_row(
    *,
    finding: RequestFinding | None,
    label: str = LABEL,
    agent_work_identifier: str | None = None,
    ended_round: int | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of a campaign request at the parent."""
    return request_row(
        issue=PARENT,
        kind=AgentWorkKind.CAMPAIGN,
        label=label,
        agent_work_identifier=agent_work_identifier,
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    ).model_copy(update={"title": f"Parent {PARENT}"})


def finish(*, scheduler: Scheduler) -> None:
    """Wait for every round the scheduler started."""
    for running in scheduler.rounds.values():
        running.wait()


def write_rounds(
    *,
    state: StateDirectory,
    endings: list,
    delivered: list[list[dict]] | None = None,
):
    """Write a campaign whose rounds ended these ways, each given its comments.

    Each round's input reaches its newest comment, or carries the cursor of the
    round before it when it holds none. A round given no comments here holds
    none.
    """
    directory = write_campaign(state=state, issue=PARENT)
    cursor = None
    for number, ending in enumerate(endings, start=1):
        comments = [] if delivered is None else delivered[number - 1]
        if comments:
            cursor = IssueCommentCursor(
                written_at=comments[-1]["created_at"], id=comments[-1]["id"]
            )
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=PINNED + timedelta(minutes=number),
                pid=number,
                ending=ending,
            ),
            round_input=CampaignRoundInput(
                issue=PARENT,
                comments=[IssueComment.model_validate(item) for item in comments],
                cursor=cursor,
                revision="abc123",
            ),
        )
    return directory


def say(*, identifier: int, body: str = "Carry on.") -> dict:
    """Return one eligible comment on the parent."""
    return comment(id=identifier, body=body)


def offer_comments(*, gh, comments: list[dict]) -> None:
    """Have GitHub answer a read of the parent's comments with these."""
    gh.replies(stdout=pages(items=comments), to=COMMENTS_PATH)


def count_comment_reads(*, gh) -> int:
    """Return how often GitHub was asked for the parent's comments."""
    expected = COMMENTS_PATH.split()
    return sum(call.arguments[: len(expected)] == expected for call in gh.calls)


def read_lead_input(*, scheduler: Scheduler, number: int) -> CampaignRoundInput:
    """Return the input that one round of the campaign at the parent was given."""
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    return read_json(
        model=CampaignRoundInput,
        path=campaign.compose_round_paths(number=number).round_input,
    )


def position(*, of: dict) -> IssueCommentCursor:
    """Return the cursor that reaches this comment."""
    return IssueCommentCursor(written_at=of["created_at"], id=of["id"])


ERRORED = HarnessErroredAgentRoundEnding(at=PINNED + timedelta(hours=1), status=1)


def test_a_labelled_parent_starts_a_lead_that_reads_its_input_and_posts_nothing(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    identifier = compose_campaign_identifier(issue=PARENT, at=launched.at)
    assert launched.launched_agent_work_identifiers == [identifier]
    assert launched.rows == [
        campaign_row(
            finding=CampaignFinding(new_comments=0),
            agent_work_identifier=identifier,
            started_round=StartedRound(number=1),
        )
    ]
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.harness_session_identifier == "lead-session"
    assert campaign.rounds[0].outcome is AgentRoundOutcome.SUCCESSFUL
    paths = campaign.compose_round_paths(number=1)
    assert read_json(model=CampaignRoundInput, path=paths.round_input) == (
        CampaignRoundInput(
            issue=PARENT,
            comments=[],
            cursor=None,
            revision=_read_worktree_revision(worktree=campaign.worktree),
        )
    )
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Acknowledge GH20 with a comment on it.\n\n")
    assert f"Campaign input for parent issue GH20:\n\n  {paths.round_input}" in (
        call.prompt
    )
    assert "--resume" not in call.arguments
    assert not any(
        call.arguments[:1] in (["pr"], ["api"]) and "POST" in call.arguments
        for call in gh.calls
    )


def test_a_lead_that_took_its_turn_waits_through_further_updates(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    lead(harnesses=harnesses)
    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    later = [tick(scheduler=scheduler) for _ in range(2)]

    assert [record.launched_agent_work_identifiers for record in later] == [[], []]
    assert [record.rows[0].finding for record in later] == [
        CampaignFinding(new_comments=0)
    ] * 2
    assert len(harnesses["claude"].calls) == 1


@pytest.mark.parametrize(
    "ending",
    [SuccessfulAgentRoundEnding(at=PINNED), StoppedAgentRoundEnding(at=PINNED)],
)
def test_a_lead_given_its_input_has_no_round_due(campaign_scheduler, harnesses, ending):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ending])
    offer_parent(gh=gh)

    observed = tick(scheduler=scheduler)

    assert observed.rows == [
        campaign_row(
            finding=CampaignFinding(new_comments=0),
            agent_work_identifier=compose_campaign_identifier(issue=PARENT),
            ended_round=1,
        )
    ]
    assert harnesses["claude"].calls == []


@pytest.mark.parametrize(
    "ending",
    [InterruptedAgentRoundEnding(), ERRORED],
)
def test_an_unfinished_first_round_is_given_again_in_its_session(
    campaign_scheduler, harnesses, ending
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ending])
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    [call] = harnesses["claude"].calls
    assert call.arguments[-2:] == ["--resume", "lead-session"]
    assert call.prompt.startswith("Your previous round did not finish.")
    assert "Acknowledge GH20" not in call.prompt


def test_a_first_round_with_no_session_to_resume_is_given_its_instructions_again(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    directory = write_campaign(
        state=scheduler.context.state, issue=PARENT, harness_session_identifier=None
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, ending=InterruptedAgentRoundEnding()
        ),
    )
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    [call] = harnesses["claude"].calls
    assert "--resume" not in call.arguments
    assert call.prompt.startswith("Acknowledge GH20 with a comment on it.\n\n")
    assert "Your previous round did not finish." in call.prompt


def test_two_errored_rounds_put_a_campaign_in_fault(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    offer_parent(gh=gh)

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows == [
        campaign_row(
            finding=None,
            agent_work_identifier=compose_campaign_identifier(issue=PARENT),
            ended_round=2,
        )
    ]
    assert harnesses["claude"].calls == []


def test_two_faulted_campaigns_start_the_global_cooldown(campaign_scheduler):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    other = write_campaign(state=scheduler.context.state, issue=21)
    for number in (1, 2):
        write_round(
            directory=other,
            number=number,
            record=AgentRoundRecord(number=number, started=PINNED, ending=ERRORED),
        )
    show_parent(gh=gh, issue=parent_issue())
    show_parent(gh=gh, issue=parent_issue(number=21))

    observed = tick(scheduler=scheduler)

    assert observed.cooldown is not None


@pytest.mark.parametrize(
    ("issue", "pause"),
    [
        (parent_issue(labels=()), PausedFinding(cause=PauseCause.LABEL_REMOVED)),
        (
            parent_issue(assignees=()),
            PausedFinding(cause=PauseCause.ISSUE_UNASSIGNED),
        ),
        (
            parent_issue(labels=(LABEL, "dream:steward")),
            ConflictingLabelsFinding(labels=[LABEL, "dream:steward"]),
        ),
    ],
)
def test_a_paused_campaign_recovers_nothing_and_its_fault_does_not_count(
    campaign_scheduler, harnesses, issue, pause
):
    scheduler, gh = campaign_scheduler
    configure(
        root=scheduler.context.state.root, head=CAMPAIGN_CLAUDE + SECOND_CAMPAIGN_CLAUDE
    )
    scheduler = create_scheduler(root=scheduler.context.state.root)
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    show_parent(gh=gh, issue=issue)

    observed = tick(scheduler=scheduler)

    assert observed.rows[0] == campaign_row(
        finding=pause,
        agent_work_identifier=compose_campaign_identifier(issue=PARENT),
        ended_round=2,
    )
    assert observed.cooldown is None
    assert harnesses["claude"].calls == []


def test_a_campaign_paused_mid_recovery_resumes_when_its_label_returns(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[InterruptedAgentRoundEnding()])
    show_parent(gh=gh, issue=parent_issue(labels=()))
    paused = tick(scheduler=scheduler)
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    resumed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert paused.launched_agent_work_identifiers == []
    assert resumed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]


def test_a_closed_parent_ends_the_campaign_once_its_round_finishes(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    lead(harnesses=harnesses, delay=10)
    tick(scheduler=scheduler)
    closed = parent_issue(state="CLOSED")
    list_parents(gh=gh, issues=[])
    show_parent(gh=gh, issue=closed)

    while_running = tick(scheduler=scheduler)
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.ending is None
    finish(scheduler=scheduler)
    after = tick(scheduler=scheduler)

    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.ending is not None
    assert campaign.ending.reason is AgentWorkEndReason.ISSUE_CLOSED
    assert while_running.rows[0].finding is None
    assert after.launched_agent_work_identifiers == []
    assert len(harnesses["claude"].calls) == 1


def test_a_closed_parent_ends_a_campaign_in_fault_without_a_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    show_parent(gh=gh, issue=parent_issue(state="CLOSED"))

    observed = tick(scheduler=scheduler)

    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.ending is not None
    assert observed.cooldown is None
    assert harnesses["claude"].calls == []


def test_a_reopened_parent_with_its_label_starts_a_new_campaign(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    directory = write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    show_parent(gh=gh, issue=parent_issue(state="CLOSED"))
    tick(scheduler=scheduler)
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    reopened = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    [identifier] = reopened.launched_agent_work_identifiers
    assert identifier != directory.name
    assert identifier.endswith("-campaign")


def test_a_parent_that_cannot_be_read_starts_nothing(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[InterruptedAgentRoundEnding()])
    gh.fails(stderr="GitHub is down", to=f"issue view {PARENT} --repo {REPOSITORY}")

    observed = tick(scheduler=scheduler)

    assert isinstance(observed.rows[0].finding, ReadFailureFinding)
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def test_a_running_lead_is_observed_without_starting_another_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    scheduler.max_agents = 2
    offer_parent(gh=gh)
    lead(harnesses=harnesses, delay=10)
    tick(scheduler=scheduler)

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows[0].finding == CampaignFinding(new_comments=0)
    assert len(harnesses["claude"].calls) == 1


def test_two_campaign_labels_on_a_parent_are_a_routing_conflict(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    configure(
        root=scheduler.context.state.root, head=CAMPAIGN_CLAUDE + SECOND_CAMPAIGN_CLAUDE
    )
    scheduler = create_scheduler(root=scheduler.context.state.root)
    both = parent_issue(labels=(LABEL, "dream:steward"))
    for label in (LABEL, "dream:steward"):
        list_parents(gh=gh, label=label, issues=[both])

    observed = tick(scheduler=scheduler)

    conflict = ConflictingLabelsFinding(labels=[LABEL, "dream:steward"])
    assert observed.rows == [
        campaign_row(finding=conflict),
        campaign_row(label="dream:steward", finding=conflict),
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None
    assert harnesses["claude"].calls == []


def test_a_campaign_waits_for_shared_capacity(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    observed = tick(scheduler=scheduler)

    assert observed.rows == [campaign_row(finding=CampaignFinding(new_comments=0))]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None


def test_the_three_kinds_take_turns_for_free_slots(cloned, gh, harnesses):
    configure(root=cloned, head=CONVERSATION_CLAUDE + CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=cloned)
    scheduler.max_agents = 4
    for issue in (13, 14):
        write_assignment(
            state=scheduler.context.state,
            identifier=f"GH{issue}-20260923-010000-assignment",
            issue=issue,
            pull_request=None,
        )
    offer_parent(gh=gh)
    conversation = parent_issue(labels=("dream:conversation",), number=8)
    list_parents(gh=gh, label="dream:conversation", issues=[conversation])
    gh.replies(
        stdout=pages(items=[comment(id=1, body="Please explain.")]),
        to=f"api repos/{REPOSITORY}/issues/8/comments?per_page=100",
    )
    harnesses["claude"].replies(stdout="")

    try:
        observed = tick(scheduler=scheduler)
    finally:
        for running in scheduler.rounds.values():
            running.interrupt()

    assert [identifier.split("-")[0] for identifier in scheduler.rounds] == [
        "GH13",
        "GH8",
        "GH20",
        "GH14",
    ]
    assert len(observed.launched_agent_work_identifiers) == 4


def test_a_codex_lead_works_under_codexs_reviewer_without_a_final_file(
    cloned, gh, harnesses
):
    configure(root=cloned, head=CODEX_CAMPAIGN)
    scheduler = create_scheduler(root=cloned, harness=AgentHarness.CODEX)
    offer_parent(gh=gh)
    harnesses["codex"].streams(
        lines=[
            Line(
                text=streamed(type="thread.started", thread_id="lead-codex-session")
                + "\n"
            )
        ],
        status=0,
    )

    try:
        tick(scheduler=scheduler)
        finish(scheduler=scheduler)
    finally:
        for running in scheduler.rounds.values():
            running.interrupt()

    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.rounds[0].outcome is AgentRoundOutcome.SUCCESSFUL
    [call] = harnesses["codex"].calls
    assert "--approve-for-me" in call.arguments
    assert "--output-last-message" not in call.arguments


def test_the_first_round_is_given_the_comments_already_on_the_parent(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    first, second = say(identifier=1), say(identifier=2, body="Mind the order.")
    offer_comments(gh=gh, comments=[first, second])
    lead(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.rows[0].finding == CampaignFinding(new_comments=2)
    given = read_lead_input(scheduler=scheduler, number=1)
    assert given.comments == [
        IssueComment.model_validate(item) for item in (first, second)
    ]
    assert given.cursor == position(of=second)


def test_a_parent_comment_wakes_the_lead_in_its_session_on_refreshed_main(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    root = scheduler.context.state.root
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    (root / "README.md").write_bytes(b"what main holds now\n")
    commit(path=root, message="change main")
    git(arguments=["push", "origin", "main"], cwd=root)
    offer_parent(gh=gh)
    question = say(identifier=1, body="How far have the stages got?")
    offer_comments(gh=gh, comments=[question])
    lead(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert launched.rows[0].finding == CampaignFinding(new_comments=1)
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.comments == [IssueComment.model_validate(question)]
    assert given.cursor == position(of=question)
    assert given.revision == git(arguments=["rev-parse", "HEAD"], cwd=root).strip()
    [call] = harnesses["claude"].calls
    assert call.arguments[-2:] == ["--resume", "lead-session"]
    assert call.prompt.startswith("Campaign input for parent issue GH20:")


def test_the_leads_own_marked_replies_wake_nothing(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    offer_parent(gh=gh)
    offer_comments(
        gh=gh,
        comments=[say(identifier=1, body=f"Stage 1 is done.\n\n{AGENT_POST_MARKER}")],
    )

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows[0].finding == CampaignFinding(new_comments=0)
    assert harnesses["claude"].calls == []


@pytest.mark.parametrize(
    "paused",
    [
        parent_issue(labels=()),
        parent_issue(assignees=()),
        parent_issue(labels=(LABEL, "dream:steward")),
    ],
)
def test_comments_posted_while_paused_reach_the_lead_when_it_resumes(
    campaign_scheduler, harnesses, paused
):
    scheduler, gh = campaign_scheduler
    configure(
        root=scheduler.context.state.root, head=CAMPAIGN_CLAUDE + SECOND_CAMPAIGN_CLAUDE
    )
    scheduler = create_scheduler(root=scheduler.context.state.root)
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    show_parent(gh=gh, issue=paused)
    waiting = say(identifier=1, body="Wait for the release first.")
    offer_comments(gh=gh, comments=[waiting])
    while_paused = tick(scheduler=scheduler)
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    resumed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert while_paused.launched_agent_work_identifiers == []
    assert count_comment_reads(gh=gh) == 1
    assert resumed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).comments == [
        IssueComment.model_validate(waiting)
    ]
    [call] = harnesses["claude"].calls
    assert call.arguments[-2:] == ["--resume", "lead-session"]


def test_a_stopped_lead_waits_for_fresh_direction_and_is_told_it_was_stopped(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    first = say(identifier=1, body="Review stage 1.")
    write_rounds(
        state=scheduler.context.state,
        endings=[StoppedAgentRoundEnding(at=PINNED)],
        delivered=[[first]],
    )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[first])
    waiting = tick(scheduler=scheduler)
    redirect = say(identifier=2, body="Review stage 2 instead.")
    offer_comments(gh=gh, comments=[first, redirect])
    lead(harnesses=harnesses)

    redirected = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert waiting.launched_agent_work_identifiers == []
    assert redirected.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).comments == [
        IssueComment.model_validate(redirect)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("The user stopped your previous round")


def test_a_lead_stopped_before_its_first_input_waits_for_a_comment(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    directory = write_campaign(state=scheduler.context.state, issue=PARENT)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, ending=StoppedAgentRoundEnding(at=PINNED)
        ),
    )
    offer_parent(gh=gh)
    waiting = tick(scheduler=scheduler)
    earlier = say(identifier=1, body="The plan is on the parent.")
    offer_comments(gh=gh, comments=[earlier])
    lead(harnesses=harnesses)

    woken = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert waiting.launched_agent_work_identifiers == []
    assert woken.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).comments == [
        IssueComment.model_validate(earlier)
    ]


@pytest.mark.parametrize("ending", [InterruptedAgentRoundEnding(), ERRORED])
def test_an_unfinished_rounds_comments_are_given_again_with_any_since(
    campaign_scheduler, harnesses, ending
):
    scheduler, gh = campaign_scheduler
    first, second, third = (say(identifier=identifier) for identifier in (1, 2, 3))
    write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), ending],
        delivered=[[first], [second]],
    )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[first, second, third])
    lead(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=3)
    assert given.comments == [
        IssueComment.model_validate(item) for item in (second, third)
    ]
    assert given.cursor == position(of=third)
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Your previous round did not finish.")


def test_a_recovery_with_no_new_comment_carries_the_cursor_forward(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    first = say(identifier=1)
    write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), InterruptedAgentRoundEnding()],
        delivered=[[first], []],
    )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[first])
    lead(harnesses=harnesses)

    recovered = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert recovered.rows[0].finding == CampaignFinding(new_comments=0)
    given = read_lead_input(scheduler=scheduler, number=3)
    assert given.comments == []
    assert given.cursor == position(of=first)


@pytest.mark.parametrize("is_open", [True, False])
def test_parent_comments_that_cannot_be_read_start_no_round(
    campaign_scheduler, harnesses, is_open
):
    scheduler, gh = campaign_scheduler
    if is_open:
        write_rounds(
            state=scheduler.context.state, endings=[InterruptedAgentRoundEnding()]
        )
    offer_parent(gh=gh)
    gh.fails(stderr="GitHub is down", to=COMMENTS_PATH)

    observed = tick(scheduler=scheduler)

    assert isinstance(observed.rows[0].finding, ReadFailureFinding)
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def test_an_open_campaign_with_no_round_yet_starts_its_lead(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_campaign(
        state=scheduler.context.state, issue=PARENT, harness_session_identifier=None
    )
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Acknowledge GH20 with a comment on it.\n\n")


def test_a_retry_clears_the_fault_and_the_lead_recovers(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    request_agent_work_retry(work=campaign, at=ERRORED.at + timedelta(minutes=1))
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    retried = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert retried.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Your previous round did not finish.")


def test_a_codex_lead_resumes_its_session_for_a_parent_comment(cloned, gh, harnesses):
    configure(root=cloned, head=CODEX_CAMPAIGN)
    scheduler = create_scheduler(root=cloned, harness=AgentHarness.CODEX)
    state = scheduler.context.state
    directory = write_campaign(
        state=state,
        issue=PARENT,
        harness=AgentHarness.CODEX,
        harness_session_identifier="lead-codex-session",
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, ending=SuccessfulAgentRoundEnding(at=PINNED)
        ),
        round_input=CampaignRoundInput(
            issue=PARENT, comments=[], cursor=None, revision="abc123"
        ),
    )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[say(identifier=1)])
    harnesses["codex"].streams(
        lines=[
            Line(
                text=streamed(type="thread.started", thread_id="lead-codex-session")
                + "\n"
            )
        ],
        status=0,
    )

    try:
        tick(scheduler=scheduler)
        finish(scheduler=scheduler)
    finally:
        for running in scheduler.rounds.values():
            running.interrupt()

    [call] = harnesses["codex"].calls
    assert call.arguments[:2] == ["exec", "resume"]
    assert "lead-codex-session" in call.arguments
    assert call.prompt.startswith("Campaign input for parent issue GH20:")
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    assert read_lead_input(scheduler=scheduler, number=2).revision == (
        _read_worktree_revision(worktree=campaign.worktree)
    )
