"""Scheduling of campaigns, from a parent's label to its closure."""

import json
from collections.abc import Sequence
from datetime import timedelta
from unittest.mock import Mock

import pytest
from clocks import PINNED, Ticking
from conftest import (
    CAMPAIGN_CLAUDE,
    HEAD,
    POSTED_BY,
    REPOSITORY,
    commit,
    compose_blocker,
    compose_check_run,
    compose_comment,
    compose_page,
    compose_pull_request,
    compose_stream_line,
    configure,
    run_git,
)
from fakes import Line
from records import (
    compose_campaign_identifier,
    read_campaign,
    write_assignment,
    write_campaign,
    write_ending,
    write_round,
)
from rows import compose_request_row

from dreamcatcher.agent_assignments import ObservedPullRequest
from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundRecord,
    HarnessErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import AgentWorkEndReason, request_agent_work_retry
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
)
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import read_json
from dreamcatcher.git import _read_worktree_revision
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    IssueState,
    PullRequestMergeState,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import _CAMPAIGN_POST_INSTRUCTIONS, AGENT_POST_MARKER
from dreamcatcher.relay import IssueCommentCursor
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.models import (
    BlockingIssuesFinding,
    CampaignFinding,
    ConflictingLabelsFinding,
    IssueReference,
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
BLOCKERS_PATH = (
    f"api repos/{REPOSITORY}/issues/{PARENT}/dependencies/blocked_by?per_page=100"
)
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
                text=compose_stream_line(
                    type="system",
                    subtype="init",
                    model="claude-opus-5",
                    session_id="lead-session",
                )
                + "\n"
            ),
            Line(
                text=compose_stream_line(
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
    children: Sequence[CampaignChild] | None = (),
) -> RequestRow:
    """Return the row of a campaign request at the parent, by default childless."""
    return compose_request_row(
        issue=PARENT,
        kind=AgentWorkKind.CAMPAIGN,
        label=label,
        agent_work_identifier=agent_work_identifier,
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    ).model_copy(
        update={
            "title": f"Parent {PARENT}",
            "children": None if children is None else list(children),
        }
    )


def finish(*, scheduler: Scheduler) -> None:
    """Wait for every round the scheduler started."""
    for running in scheduler.rounds.values():
        running.wait()


def write_rounds(
    *,
    state: StateDirectory,
    endings: list,
    delivered: list[list[dict]] | None = None,
    pictures: list[list[CampaignChild]] | None = None,
):
    """Write a campaign whose rounds ended these ways, each given its comments.

    Each round's input reaches its newest comment, or carries the cursor of the
    round before it when it holds none. A round given no comments here holds
    none, and a round given no picture of the children here holds no children.
    An ending of None is a round still running.
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
                children=[] if pictures is None else pictures[number - 1],
                notifications=[],
                comments=[IssueComment.model_validate(item) for item in comments],
                cursor=cursor,
                revision="abc123",
                assignment_routes=[],
            ),
        )
    return directory


def say(*, identifier: int, body: str = "Carry on.") -> dict:
    """Return one eligible comment on the parent."""
    return compose_comment(id=identifier, body=body)


def offer_comments(*, gh, comments: list[dict]) -> None:
    """Have GitHub answer a read of the parent's comments with these."""
    gh.replies(stdout=compose_page(items=comments), to=COMMENTS_PATH)


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
            finding=CampaignFinding(new_comments=0, changed_children=0),
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
            children=[],
            notifications=[],
            comments=[],
            cursor=None,
            revision=_read_worktree_revision(worktree=campaign.worktree),
            assignment_routes=scheduler.context.config.assignment,
        )
    )
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Acknowledge GH20 with a comment on it.\n\n")
    assert f"Campaign input for parent issue GH20:\n\n  {paths.round_input}" in (
        call.prompt
    )
    assert call.prompt.endswith(_CAMPAIGN_POST_INSTRUCTIONS)
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
        CampaignFinding(new_comments=0, changed_children=0)
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
            finding=CampaignFinding(new_comments=0, changed_children=0),
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
    assert observed.rows[0].finding == CampaignFinding(
        new_comments=0, changed_children=0
    )
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
        campaign_row(finding=conflict, children=None),
        campaign_row(label="dream:steward", finding=conflict, children=None),
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None
    assert harnesses["claude"].calls == []


def offer_blockers(*, gh, blockers: list[dict]) -> None:
    """Have GitHub answer a read of what blocks the parent with these."""
    gh.replies(stdout=compose_page(items=blockers), to=BLOCKERS_PATH)


def count_blocker_reads(*, gh) -> int:
    """Return how often GitHub was asked what blocks the parent."""
    expected = BLOCKERS_PATH.split()
    return sum(call.arguments[: len(expected)] == expected for call in gh.calls)


def count_reads_past_the_blockers(*, gh) -> int:
    """Return how often GitHub was asked for the parent's sub-issues or comments."""
    return sum(
        "/sub_issues" in argument or "/comments" in argument
        for call in gh.calls
        for argument in call.arguments
    )


def test_an_open_blocker_queues_the_campaign_with_no_lead(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    offer_blockers(
        gh=gh,
        blockers=[
            compose_blocker(number=7, state="closed"),
            compose_blocker(number=18, state="open"),
            compose_blocker(number=1016, state="open", repository="alimanfoo/dream"),
        ],
    )

    observed = tick(scheduler=scheduler)

    assert observed.rows == [
        campaign_row(
            finding=BlockingIssuesFinding(
                blocking_issues=[
                    IssueReference(number=18),
                    IssueReference(number=1016, repository="alimanfoo/dream"),
                ]
            ),
            children=None,
        )
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None
    assert count_reads_past_the_blockers(gh=gh) == 0
    assert harnesses["claude"].calls == []


def test_a_queued_campaign_starts_once_its_blockers_close(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    offer_blockers(gh=gh, blockers=[compose_blocker(number=18, state="open")])
    tick(scheduler=scheduler)
    offer_blockers(gh=gh, blockers=[compose_blocker(number=18, state="closed")])
    lead(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT, at=launched.at)
    ]


def test_a_failed_read_of_the_blockers_leaves_the_request_unknown(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    gh.fails(stderr="GitHub is down", to=BLOCKERS_PATH)

    observed = tick(scheduler=scheduler)

    [row] = observed.rows
    assert isinstance(row.finding, ReadFailureFinding)
    assert "GitHub is down" in row.finding.reason
    assert row.children is None
    assert count_reads_past_the_blockers(gh=gh) == 0
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None
    assert harnesses["claude"].calls == []


def test_an_open_campaign_carries_on_whatever_blocks_its_parent(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    offer_parent(gh=gh)
    offer_blockers(gh=gh, blockers=[compose_blocker(number=18, state="open")])
    offer_comments(gh=gh, comments=[say(identifier=1)])
    lead(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert observed.rows[0].finding == CampaignFinding(
        new_comments=1, changed_children=0
    )
    assert observed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert count_blocker_reads(gh=gh) == 0


def test_a_campaign_waits_for_shared_capacity(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    observed = tick(scheduler=scheduler)

    assert observed.rows == [
        campaign_row(finding=CampaignFinding(new_comments=0, changed_children=0))
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None


def test_campaigns_are_inspected_after_the_assignments(campaign_scheduler):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    write_assignment(
        state=scheduler.context.state,
        identifier="GH30-20260923-010000-assignment",
        issue=30,
        pull_request=None,
    )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[])
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    observed = tick(scheduler=scheduler)

    assert [(row.kind, row.issue) for row in observed.rows] == [
        (AgentWorkKind.ASSIGNMENT, 30),
        (AgentWorkKind.CAMPAIGN, PARENT),
    ]


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
        stdout=compose_page(items=[compose_comment(id=1, body="Please explain.")]),
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
                text=compose_stream_line(
                    type="thread.started", thread_id="lead-codex-session"
                )
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

    assert launched.rows[0].finding == CampaignFinding(
        new_comments=2, changed_children=0
    )
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
    run_git(arguments=["push", "origin", "main"], cwd=root)
    offer_parent(gh=gh)
    question = say(identifier=1, body="How far have the stages got?")
    offer_comments(gh=gh, comments=[question])
    lead(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert launched.rows[0].finding == CampaignFinding(
        new_comments=1, changed_children=0
    )
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.comments == [IssueComment.model_validate(question)]
    assert given.cursor == position(of=question)
    assert given.revision == run_git(arguments=["rev-parse", "HEAD"], cwd=root).strip()
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
    assert observed.rows[0].finding == CampaignFinding(
        new_comments=0, changed_children=0
    )
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

    assert recovered.rows[0].finding == CampaignFinding(
        new_comments=0, changed_children=0
    )
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


def test_a_delivered_input_that_cannot_be_read_starts_no_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    round_input = campaign.compose_round_paths(number=1).round_input
    round_input.write_bytes(b"{")
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[say(identifier=1)])

    observed = tick(scheduler=scheduler)

    [row] = observed.rows
    assert isinstance(row.finding, ReadFailureFinding)
    assert round_input.name in row.finding.reason
    assert observed.launched_agent_work_identifiers == []
    assert count_comment_reads(gh=gh) == 0
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
            issue=PARENT,
            children=[],
            notifications=[],
            comments=[],
            cursor=None,
            revision="abc123",
            assignment_routes=[],
        ),
    )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[say(identifier=1)])
    harnesses["codex"].streams(
        lines=[
            Line(
                text=compose_stream_line(
                    type="thread.started", thread_id="lead-codex-session"
                )
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


FIRST_CHILD = 21
SECOND_CHILD = 22
CHILD_ASSIGNMENT = "GH21-20260923-010000-assignment"
CHILDREN_PATH = f"api repos/{REPOSITORY}/issues/{PARENT}/sub_issues?per_page=100"
SMITH = "dream:smith"
FOREIGN = "other/tools"


def sub_issue(
    *, number: int, state: str = "open", repository: str = REPOSITORY
) -> dict:
    """Return what GitHub lists of one child of the parent, by default a local one."""
    return {
        "number": number,
        "title": f"Stage {number}",
        "state": state,
        "repository_url": f"https://api.github.com/repos/{repository}",
    }


def offer_children(*, gh, children: list[dict]) -> None:
    """Have GitHub list these children of the parent."""
    gh.replies(stdout=compose_page(items=children), to=CHILDREN_PATH)


def settle_lead(
    *, state: StateDirectory, children: Sequence[CampaignChild] = ()
) -> None:
    """Write a campaign whose lead took its turn, given these children.

    No lead round is due while the children stay as the lead was given them.
    """
    write_rounds(
        state=state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
        pictures=[list(children)],
    )


def write_child_assignment(
    *,
    state: StateDirectory,
    endings: list,
    identifier: str = CHILD_ASSIGNMENT,
    pull_request: int | None = 52,
) -> None:
    """Write an assignment at the first child whose rounds ended these ways.

    An ending of None is a round still running.
    """
    directory = write_assignment(
        state=state,
        identifier=identifier,
        issue=FIRST_CHILD,
        pull_request=pull_request,
    )
    for number, ending in enumerate(endings, start=1):
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=PINNED + timedelta(minutes=number),
                pid=number,
                ending=ending,
            ),
        )


def observe_children(*, scheduler: Scheduler) -> list[CampaignChild] | None:
    """Run one tick and return the children that the campaign's row holds."""
    [row] = [
        row
        for row in tick(scheduler=scheduler).rows
        if row.kind is AgentWorkKind.CAMPAIGN
    ]
    return row.children


def child(**fields) -> CampaignChild:
    """Return the first child as observed, settled and with no assignment."""
    return CampaignChild.model_validate(
        {
            "issue": FIRST_CHILD,
            "title": f"Stage {FIRST_CHILD}",
            "state": IssueState.OPEN,
            "is_settled": True,
            "assignment": None,
        }
        | fields
    )


def child_assignment(**fields) -> CampaignChildAssignment:
    """Return the first child's assignment, open with its pull request unread."""
    return CampaignChildAssignment.model_validate(
        {
            "identifier": CHILD_ASSIGNMENT,
            "pull_request": 52,
            "observed_pull_request": None,
            "finished_turn": None,
            "ending": None,
            "is_fault": False,
        }
        | fields
    )


DRAFT_PULL_REQUEST = ObservedPullRequest(
    state=PullRequestState.OPEN,
    is_draft=True,
    merge_state=PullRequestMergeState.CLEAN,
    head=HEAD,
    check_result=CheckResult.PASSING,
    has_running_checks=False,
)


def test_a_paused_lead_still_observes_every_child_in_githubs_order(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    show_parent(gh=gh, issue=parent_issue(labels=()))
    offer_children(
        gh=gh,
        children=[
            sub_issue(number=SECOND_CHILD, state="closed"),
            sub_issue(number=FIRST_CHILD),
        ],
    )

    observed = tick(scheduler=scheduler)

    assert observed.rows == [
        campaign_row(
            finding=PausedFinding(cause=PauseCause.LABEL_REMOVED),
            agent_work_identifier=compose_campaign_identifier(issue=PARENT),
            ended_round=1,
            children=[
                child(
                    issue=SECOND_CHILD,
                    title=f"Stage {SECOND_CHILD}",
                    state=IssueState.CLOSED,
                ),
                child(),
            ],
        )
    ]


def test_a_child_whose_assignment_may_start_has_work_due(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    list_parents(
        gh=gh,
        label=SMITH,
        issues=[parent_issue(labels=(SMITH,), number=FIRST_CHILD)],
    )
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    assert observe_children(scheduler=scheduler) == [child(is_settled=False)]


def test_a_working_child_has_work_running_and_its_pull_request_observed(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), None],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        child(
            is_settled=False,
            assignment=child_assignment(
                observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=1
            ),
        )
    ]


def test_a_settled_child_names_its_last_finished_turn_and_its_checks(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(
        state=scheduler.context.state,
        endings=[
            SuccessfulAgentRoundEnding(at=PINNED),
            StoppedAgentRoundEnding(at=PINNED),
        ],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    gh.replies(
        stdout=compose_pull_request(
            state="OPEN",
            merge_state="UNKNOWN",
            checks=[compose_check_run(), compose_check_run(status="IN_PROGRESS")],
        ),
        to="pr view",
    )

    assert observe_children(scheduler=scheduler) == [
        child(
            assignment=child_assignment(
                observed_pull_request=ObservedPullRequest(
                    state=PullRequestState.OPEN,
                    is_draft=False,
                    merge_state=PullRequestMergeState.UNKNOWN,
                    head=HEAD,
                    check_result=CheckResult.RUNNING,
                    has_running_checks=True,
                ),
                finished_turn=2,
            ),
        )
    ]


def test_a_faulted_child_keeps_its_pull_request_but_has_no_fresh_read(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), ERRORED, ERRORED],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        child(assignment=child_assignment(finished_turn=1, is_fault=True))
    ]


def test_an_ended_child_assignment_stays_visible_as_ended(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
    )
    write_ending(
        directory=scheduler.context.state.work / CHILD_ASSIGNMENT,
        reason=AgentWorkEndReason.COMPLETED,
        at=PINNED,
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD, state="closed")])

    assert observe_children(scheduler=scheduler) == [
        child(
            state=IssueState.CLOSED,
            assignment=child_assignment(
                finished_turn=1, ending=AgentWorkEndReason.COMPLETED
            ),
        )
    ]


def test_a_cancelled_child_still_stopping_has_work_running(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(state=scheduler.context.state, endings=[None])
    write_ending(
        directory=scheduler.context.state.work / CHILD_ASSIGNMENT,
        reason=AgentWorkEndReason.CANCELLED,
        at=PINNED,
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        child(
            is_settled=False,
            assignment=child_assignment(ending=AgentWorkEndReason.CANCELLED),
        )
    ]


def test_a_replacement_assignment_takes_the_place_of_the_one_it_replaced(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
    )
    write_ending(
        directory=scheduler.context.state.work / CHILD_ASSIGNMENT,
        reason=AgentWorkEndReason.CANCELLED,
        at=PINNED,
    )
    replacement = "GH21-20260924-010000-assignment"
    write_child_assignment(
        state=scheduler.context.state,
        identifier=replacement,
        endings=[None],
        pull_request=None,
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        child(
            is_settled=False,
            assignment=child_assignment(identifier=replacement, pull_request=None),
        )
    ]


def test_a_lead_round_is_given_the_children_that_its_update_observed(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
    )
    offer_parent(gh=gh)
    offer_children(
        gh=gh,
        children=[sub_issue(number=FIRST_CHILD), sub_issue(number=SECOND_CHILD)],
    )
    lead(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=1)
    assert given.children == [
        child(
            assignment=child_assignment(
                observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=1
            )
        ),
        child(issue=SECOND_CHILD, title=f"Stage {SECOND_CHILD}"),
    ]
    assert given.assignment_routes == scheduler.context.config.assignment


def fail_to_list_children(*, gh) -> None:
    """Have GitHub fail to list the parent's children."""
    gh.fails(stderr="gh: could not connect to github.com", to=CHILDREN_PATH)


def fail_to_read_the_childs_pull_request(*, gh) -> None:
    """Have the first child's assignment fail to read its pull request."""
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")


def fail_to_list_assignment_requests(*, gh) -> None:
    """Have the listing under the assignment label fail."""
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    gh.fails(
        stderr="gh: could not connect to github.com",
        to=f"issue list --repo {REPOSITORY} --assignee {POSTED_BY} --label {SMITH}",
    )


def offer_a_foreign_child(*, gh) -> None:
    """List a child from another repository, numbered like the local child."""
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD, repository=FOREIGN)])


@pytest.mark.parametrize(
    ("fail", "has_child_assignment", "reason"),
    [
        (
            offer_a_foreign_child,
            True,
            f"could not observe sub-issue {FOREIGN}#21: it is in another repository",
        ),
        (fail_to_list_children, False, f"gh {CHILDREN_PATH}: gh: could not connect"),
        (
            fail_to_read_the_childs_pull_request,
            True,
            "could not observe sub-issue 21: gh pr view 52: gh: could not connect",
        ),
        (
            fail_to_list_assignment_requests,
            False,
            "could not observe sub-issue 21: could not list issues for dream:smith",
        ),
    ],
)
def test_an_incomplete_picture_of_the_children_withholds_the_lead(
    campaign_scheduler, harnesses, fail, has_child_assignment, reason
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED])
    if has_child_assignment:
        write_child_assignment(
            state=scheduler.context.state,
            endings=[SuccessfulAgentRoundEnding(at=PINNED)],
        )
    offer_parent(gh=gh)
    offer_comments(gh=gh, comments=[say(identifier=1)])
    fail(gh=gh)

    observed = tick(scheduler=scheduler)

    [row] = [row for row in observed.rows if row.kind is AgentWorkKind.CAMPAIGN]
    assert row.children is None
    assert isinstance(row.finding, ReadFailureFinding)
    assert row.finding.reason.startswith(reason)
    assert count_comment_reads(gh=gh) == 0
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def test_a_new_campaign_waits_for_a_complete_picture_of_its_children(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    fail_to_list_children(gh=gh)

    observed = tick(scheduler=scheduler)

    assert observed.rows == [
        campaign_row(
            finding=ReadFailureFinding(
                reason=f"gh {CHILDREN_PATH}: gh: could not connect to github.com"
            ),
            children=None,
        )
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None


def test_a_paused_lead_whose_children_cannot_be_read_is_still_paused(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    show_parent(gh=gh, issue=parent_issue(labels=()))
    fail_to_list_children(gh=gh)

    observed = tick(scheduler=scheduler)

    assert observed.rows[0].finding == PausedFinding(cause=PauseCause.LABEL_REMOVED)
    assert observed.rows[0].children is None


def test_a_paused_lead_with_a_foreign_child_shows_its_children_unknown(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
    )
    show_parent(gh=gh, issue=parent_issue(labels=()))
    offer_a_foreign_child(gh=gh)

    observed = tick(scheduler=scheduler)

    [row] = [row for row in observed.rows if row.kind is AgentWorkKind.CAMPAIGN]
    assert row.finding == PausedFinding(cause=PauseCause.LABEL_REMOVED)
    assert row.children is None


WORKING = child(
    is_settled=False,
    assignment=child_assignment(
        observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=1
    ),
)
UNSTARTED = child(issue=SECOND_CHILD, title=f"Stage {SECOND_CHILD}")
BOTH_CHILDREN = [sub_issue(number=FIRST_CHILD), sub_issue(number=SECOND_CHILD)]


def lead_row(*, observed) -> RequestRow:
    """Return the campaign's row among those that the tick observed."""
    [row] = [row for row in observed.rows if row.kind is AgentWorkKind.CAMPAIGN]
    return row


def notify(*, issue: int, changes: list[CampaignChildChange]):
    """Return the notification of these changes to one child."""
    return CampaignChildNotification(issue=issue, changes=changes)


def test_a_child_that_settles_wakes_the_lead_once_with_the_whole_picture(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state, children=[WORKING, UNSTARTED])
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)] * 2,
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=BOTH_CHILDREN)
    lead(harnesses=harnesses)

    woken = tick(scheduler=scheduler)
    finish(scheduler=scheduler)
    after = tick(scheduler=scheduler)

    assert woken.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert lead_row(observed=woken).finding == CampaignFinding(
        new_comments=0, changed_children=1
    )
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.notifications == [
        notify(issue=FIRST_CHILD, changes=[CampaignChildChange.HANDBACK])
    ]
    assert given.children == [
        child(
            assignment=child_assignment(
                observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=2
            )
        ),
        UNSTARTED,
    ]
    assert after.launched_agent_work_identifiers == []
    [call] = harnesses["claude"].calls
    assert call.arguments[-2:] == ["--resume", "lead-session"]


def test_a_working_child_wakes_no_lead_round(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    settle_lead(
        state=scheduler.context.state,
        children=[
            child(
                assignment=child_assignment(
                    observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=1
                )
            )
        ],
    )
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), None],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD, state="closed")])
    gh.replies(stdout=compose_pull_request(state="MERGED", head="f00d"), to="pr view")

    observed = tick(scheduler=scheduler)

    assert lead_row(observed=observed).finding == CampaignFinding(
        new_comments=0, changed_children=0
    )
    assert observed.launched_agent_work_identifiers == []


def test_a_failed_check_that_makes_a_repair_due_wakes_no_lead_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    reviewed = DRAFT_PULL_REQUEST.model_copy(update={"is_draft": False})
    settle_lead(
        state=scheduler.context.state,
        children=[
            child(
                assignment=child_assignment(
                    observed_pull_request=reviewed, finished_turn=1
                )
            )
        ],
    )
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    gh.replies(
        stdout=compose_pull_request(
            state="OPEN", checks=[compose_check_run(conclusion="FAILURE")]
        ),
        to="pr view",
    )

    observed = tick(scheduler=scheduler)

    [child_seen] = lead_row(observed=observed).children or []
    assert child_seen.is_settled is False
    assert lead_row(observed=observed).finding == CampaignFinding(
        new_comments=0, changed_children=0
    )
    assert compose_campaign_identifier(issue=PARENT) not in (
        observed.launched_agent_work_identifiers
    )


@pytest.mark.parametrize(
    ("given", "seen", "changes"),
    [
        ("UNKNOWN", "CLEAN", [CampaignChildChange.MERGEABLE]),
        ("CLEAN", "HAS_HOOKS", []),
    ],
    ids=["became mergeable", "mergeable still"],
)
def test_a_settled_childs_merge_state_wakes_the_lead_only_into_mergeable(
    campaign_scheduler, harnesses, given, seen, changes
):
    scheduler, gh = campaign_scheduler
    observed_given = ObservedPullRequest(
        state=PullRequestState.OPEN,
        is_draft=False,
        merge_state=PullRequestMergeState(given),
        head=HEAD,
        check_result=CheckResult.PASSING,
        has_running_checks=False,
    )
    settle_lead(
        state=scheduler.context.state,
        children=[
            child(
                assignment=child_assignment(
                    observed_pull_request=observed_given, finished_turn=1
                )
            )
        ],
    )
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    gh.replies(
        stdout=compose_pull_request(state="OPEN", merge_state=seen), to="pr view"
    )
    lead(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    expected = [notify(issue=FIRST_CHILD, changes=changes)] if changes else []
    assert lead_row(observed=observed).finding == CampaignFinding(
        new_comments=0, changed_children=len(expected)
    )
    if expected:
        assert read_lead_input(scheduler=scheduler, number=2).notifications == (
            expected
        )
    else:
        assert observed.launched_agent_work_identifiers == []


def test_a_child_added_while_another_works_wakes_the_lead(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state, children=[WORKING])
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), None],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=BOTH_CHILDREN)
    lead(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.notifications == [
        notify(issue=SECOND_CHILD, changes=[CampaignChildChange.ADDED])
    ]
    assert given.children == [WORKING, UNSTARTED]


def test_comments_and_changes_among_the_children_share_one_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state, children=[UNSTARTED])
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    question = say(identifier=1, body="Which stage is next?")
    offer_comments(gh=gh, comments=[question])
    lead(harnesses=harnesses)

    woken = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert lead_row(observed=woken).finding == CampaignFinding(
        new_comments=1, changed_children=2
    )
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.comments == [IssueComment.model_validate(question)]
    assert given.notifications == [
        notify(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED]),
        notify(issue=SECOND_CHILD, changes=[CampaignChildChange.REMOVED]),
    ]
    assert len(harnesses["claude"].calls) == 1


def test_changes_during_a_lead_round_wake_the_lead_after_it(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    directory = write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), None],
        pictures=[[], [WORKING]],
    )
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)] * 2,
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    during = tick(scheduler=scheduler)
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED,
            pid=2,
            ending=SuccessfulAgentRoundEnding(at=PINNED),
        ),
    )
    lead(harnesses=harnesses)

    after = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert during.launched_agent_work_identifiers == []
    assert lead_row(observed=during).finding == CampaignFinding(
        new_comments=0, changed_children=1
    )
    assert after.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=3).notifications == [
        notify(issue=FIRST_CHILD, changes=[CampaignChildChange.HANDBACK])
    ]


def test_a_lead_at_capacity_is_given_the_changes_once_a_slot_frees(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)
    delayed = tick(scheduler=scheduler)
    del scheduler.rounds["busy-assignment"]
    offer_children(gh=gh, children=BOTH_CHILDREN)
    lead(harnesses=harnesses)

    freed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert delayed.launched_agent_work_identifiers == []
    assert lead_row(observed=delayed).finding == CampaignFinding(
        new_comments=0, changed_children=1
    )
    assert freed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).notifications == [
        notify(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED]),
        notify(issue=SECOND_CHILD, changes=[CampaignChildChange.ADDED]),
    ]


def test_changes_while_the_lead_is_paused_reach_it_when_it_resumes(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state, children=[UNSTARTED])
    show_parent(gh=gh, issue=parent_issue(labels=()))
    offer_children(gh=gh, children=BOTH_CHILDREN)
    while_paused = tick(scheduler=scheduler)
    offer_parent(gh=gh)
    lead(harnesses=harnesses)

    resumed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert while_paused.launched_agent_work_identifiers == []
    assert lead_row(observed=while_paused).children == [child(), UNSTARTED]
    assert resumed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).notifications == [
        notify(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED])
    ]


def test_a_stopped_lead_input_is_what_later_pictures_compare_with(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state,
        endings=[
            SuccessfulAgentRoundEnding(at=PINNED),
            StoppedAgentRoundEnding(at=PINNED),
        ],
        pictures=[[], [UNSTARTED]],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=SECOND_CHILD)])

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


@pytest.mark.parametrize("ending", [InterruptedAgentRoundEnding(), ERRORED])
def test_a_recovery_compares_with_the_input_before_the_unfinished_one(
    campaign_scheduler, harnesses, ending
):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), ending],
        pictures=[[], [child()]],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=BOTH_CHILDREN)
    lead(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert read_lead_input(scheduler=scheduler, number=3).notifications == [
        notify(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED]),
        notify(issue=SECOND_CHILD, changes=[CampaignChildChange.ADDED]),
    ]
    [call] = harnesses["claude"].calls
    assert call.arguments[-2:] == ["--resume", "lead-session"]
    assert call.prompt.startswith("Your previous round did not finish.")


def test_a_child_in_fault_wakes_the_lead_once_no_round_runs(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state, children=[WORKING])
    write_child_assignment(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), ERRORED, ERRORED],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    lead(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert read_lead_input(scheduler=scheduler, number=2).notifications == [
        notify(
            issue=FIRST_CHILD,
            changes=[CampaignChildChange.HANDBACK, CampaignChildChange.FAULT],
        )
    ]


@pytest.mark.parametrize("is_stopping", [True, False])
def test_a_cancelled_child_wakes_the_lead_once_its_round_stops(
    campaign_scheduler, harnesses, is_stopping
):
    scheduler, gh = campaign_scheduler
    settle_lead(
        state=scheduler.context.state,
        children=[child(is_settled=False, assignment=child_assignment())],
    )
    write_child_assignment(
        state=scheduler.context.state,
        endings=[None if is_stopping else StoppedAgentRoundEnding(at=PINNED)],
    )
    write_ending(
        directory=scheduler.context.state.work / CHILD_ASSIGNMENT,
        reason=AgentWorkEndReason.CANCELLED,
        at=PINNED,
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[sub_issue(number=FIRST_CHILD)])
    lead(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    if is_stopping:
        assert observed.launched_agent_work_identifiers == []
    else:
        assert read_lead_input(scheduler=scheduler, number=2).notifications == [
            notify(
                issue=FIRST_CHILD,
                changes=[CampaignChildChange.HANDBACK, CampaignChildChange.ENDING],
            )
        ]
