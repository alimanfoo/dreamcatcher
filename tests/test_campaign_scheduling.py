"""Scheduling of campaigns, from a parent's label to its closure."""

import json
from collections.abc import Sequence
from datetime import timedelta
from unittest.mock import Mock

import pytest
from clocks import LABEL_APPLIED_AT, PINNED, Ticking
from conftest import (
    CAMPAIGN_CLAUDE,
    HEAD,
    POSTED_BY,
    REPOSITORY,
    commit,
    compose_blocker,
    compose_check_run,
    compose_comment,
    compose_labelling_event,
    compose_page,
    compose_pull_request,
    compose_review,
    compose_stream_line,
    configure,
    offer_issue_parent,
    offer_labelling_events,
    offer_labels_applied_by_user,
    offer_listing,
    rename_default_branch,
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
    write_work_pull_request,
)
from rows import (
    CAMPAIGN_PULL_REQUEST,
    UNCLAIMED,
    compose_campaign_finding,
    compose_campaign_row,
)

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundRecord,
    HarnessErroredAgentRoundEnding,
    InterruptedAgentRoundEnding,
    StoppedAgentRoundEnding,
    SuccessfulAgentRoundEnding,
)
from dreamcatcher.agent_work import (
    AgentWorkEndReason,
    read_agent_work_at_issue,
    request_agent_work_retry,
)
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignChildChange,
    CampaignChildNotification,
    CampaignRoundInput,
)
from dreamcatcher.cli import main
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import read_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import add_worktree, read_worktree_revision
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    IssueState,
    PullRequestMergeState,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.prompts import _CAMPAIGN_POST_INSTRUCTIONS, AGENT_POST_MARKER
from dreamcatcher.pull_request_work import (
    ObservedPullRequest,
    compose_work_branch,
    read_work_pull_request_number,
)
from dreamcatcher.scheduler import Scheduler, SchedulingContext
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueReference,
    LabelAppliedByOtherFinding,
    PullRequestFinding,
    ReadFailureFinding,
    RequestConsumedFinding,
    RequestRow,
    StartedRound,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.web.app import _create_app

PARENT = 20
LABEL = "dream:big"
PARENT_COMMENTS_PATH = f"api repos/{REPOSITORY}/issues/{PARENT}/comments?per_page=100"
POSTS_PATH = (
    f"api repos/{REPOSITORY}/issues/{CAMPAIGN_PULL_REQUEST}/comments?per_page=100"
)
CAMPAIGN_PULL_REQUEST_URL = (
    f"https://github.com/{REPOSITORY}/pull/{CAMPAIGN_PULL_REQUEST}"
)
BLOCKERS_PATH = (
    f"api repos/{REPOSITORY}/issues/{PARENT}/dependencies/blocked_by?per_page=100"
)
SECOND_CAMPAIGN_CLAUDE = CAMPAIGN_CLAUDE.replace("dream:big", "dream:steward")
CONVERSATION_CLAUDE = """[[conversation]]
label = "dream:conversation"
[conversation.claude]
prompt = "/dream:conversation GH{issue}"
model = "opus[1m]"
effort = "xhigh"
"""
CODEX_CAMPAIGN = """[[campaign]]
label = "dream:big"
[campaign.codex]
prompt = "Acknowledge GH{issue}."
model = "gpt-6.2-sol"
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
def campaign_scheduler(cloned_repo, gh):
    """Return a scheduler routing the campaign label, and stop what it leaves."""
    configure(root=cloned_repo, head=CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=cloned_repo)
    script_campaign_opening(gh=gh)
    yield scheduler, gh
    for running in scheduler.rounds.values():
        running.interrupt()


def script_campaign_opening(*, gh) -> None:
    """Have the stand-in open and observe the campaign's pull request."""
    gh.replies(stdout=CAMPAIGN_PULL_REQUEST_URL, to="pr create")
    gh.replies(
        stdout=json.dumps({"number": CAMPAIGN_PULL_REQUEST}),
        to=f"pr view {CAMPAIGN_PULL_REQUEST_URL}",
    )
    offer_campaign_pull_request(gh=gh)


def offer_campaign_pull_request(
    *,
    gh,
    state: str = "OPEN",
    is_draft: bool = True,
    merge_state: str = "CLEAN",
    head: str = HEAD,
    checks: Sequence[dict] = (compose_check_run(),),
) -> None:
    """Have GitHub report the campaign's pull request with these facts."""
    gh.replies(
        stdout=compose_pull_request(
            number=CAMPAIGN_PULL_REQUEST,
            state=state,
            is_draft=is_draft,
            merge_state=merge_state,
            head=head,
            checks=checks,
        ),
        to=f"pr view {CAMPAIGN_PULL_REQUEST}",
    )


def check_out_campaign(*, state: StateDirectory, identifier: str) -> None:
    """Give a fabricated campaign its branch and linked worktree."""
    add_worktree(
        root=state.root,
        path=state.worktrees / identifier,
        branch=compose_work_branch(identifier=identifier),
        base_ref="HEAD",
    )


def tick(*, scheduler: Scheduler):
    """Run one tick at the scheduler's clock."""
    return scheduler.tick(at=scheduler.context.clock())


def compose_parent_issue(
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


def show_parent(*, gh, issue: dict) -> None:
    """Have GitHub answer a read of the parent with this, labelled by the user."""
    gh.replies(
        stdout=json.dumps(issue),
        to=(
            f"issue view {issue['number']} --repo {REPOSITORY} "
            "--json number,title,body,createdAt,state,assignees,labels"
        ),
    )
    offer_labels_applied_by_user(gh=gh, issue=issue)


def offer_parent(*, gh, issue: dict | None = None) -> None:
    """Have GitHub list the parent and show it."""
    issue = compose_parent_issue() if issue is None else issue
    offer_listing(gh=gh, issues=[issue])
    show_parent(gh=gh, issue=issue)


def script_lead_turn(*, harnesses, status: int = 0, delay: float = 0) -> None:
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
    """Write a campaign on its branch, with the inputs each round received."""
    directory = write_campaign(state=state, issue=PARENT)
    write_work_pull_request(directory=directory, number=CAMPAIGN_PULL_REQUEST)
    check_out_campaign(state=state, identifier=directory.name)
    for number, ending in enumerate(endings, start=1):
        posts = [] if delivered is None else delivered[number - 1]
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
                pull_request=CAMPAIGN_PULL_REQUEST,
                pull_request_state=PullRequestState.OPEN,
                pull_request_head=HEAD,
                signals=[],
                children=[] if pictures is None else pictures[number - 1],
                notifications=[],
                user_posts=[IssueComment.model_validate(item) for item in posts],
                assignment_routes=[],
            ),
        )
    return directory


def compose_pull_request_post(*, identifier: int, body: str = "Carry on.") -> dict:
    """Return one eligible post on the pull request."""
    return compose_comment(
        id=identifier, body=body, created_at=f"2026-09-23T01:00:{identifier:02d}Z"
    )


def offer_posts(*, gh, posts: list[dict]) -> None:
    """Have GitHub answer a read of the pull request's posts with these."""
    gh.replies(stdout=compose_page(items=posts), to=POSTS_PATH)


def count_post_reads(*, gh) -> int:
    """Return how often GitHub was asked for the pull request's posts."""
    expected = POSTS_PATH.split()
    return sum(call.arguments[: len(expected)] == expected for call in gh.calls)


def read_lead_input(*, scheduler: Scheduler, number: int) -> CampaignRoundInput:
    """Return the input that one round of the campaign at the parent was given."""
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    return read_json(
        model=CampaignRoundInput,
        path=campaign.compose_round_paths(number=number).round_input,
    )


ERRORED = HarnessErroredAgentRoundEnding(at=PINNED + timedelta(hours=1), status=1)


def test_a_labelled_parent_starts_a_lead_that_reads_its_input_and_posts_nothing(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    script_lead_turn(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    identifier = compose_campaign_identifier(issue=PARENT, at=launched.at)
    assert launched.launched_agent_work_identifiers == [identifier]
    assert launched.rows == [
        compose_campaign_row(
            issue=PARENT,
            finding=UNCLAIMED,
            agent_work_identifier=identifier,
            started_round=StartedRound(number=1),
            children=(),
        ).model_copy(update={"issue_state": IssueState.OPEN})
    ]
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.record.label_applied_at == LABEL_APPLIED_AT
    assert campaign.harness_session_identifier == "lead-session"
    assert campaign.rounds[0].outcome is AgentRoundOutcome.SUCCESSFUL
    paths = campaign.compose_round_paths(number=1)
    assert read_json(model=CampaignRoundInput, path=paths.round_input) == (
        CampaignRoundInput(
            pull_request=CAMPAIGN_PULL_REQUEST,
            pull_request_state=PullRequestState.OPEN,
            pull_request_head=read_worktree_revision(worktree=campaign.worktree),
            signals=[],
            user_posts=[],
            children=[],
            notifications=[],
            assignment_routes=scheduler.context.config.assignment,
        )
    )
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Acknowledge GH20.\n\n")
    assert f"Campaign input for parent issue GH20:\n\n  {paths.round_input}" in (
        call.prompt
    )
    assert call.prompt.endswith(_CAMPAIGN_POST_INSTRUCTIONS)
    assert "assignment label if present, then add the label" in " ".join(
        call.prompt.split()
    )
    assert "--resume" not in call.arguments
    assert all("POST" not in call.arguments for call in gh.calls)


def test_a_lead_that_took_its_turn_waits_through_further_updates(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    script_lead_turn(harnesses=harnesses)
    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    later = [tick(scheduler=scheduler) for _ in range(2)]

    assert [record.launched_agent_work_identifiers for record in later] == [[], []]
    assert [record.rows[0].finding for record in later] == [
        compose_campaign_finding(new_posts=0, changed_children=0)
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
        compose_campaign_row(
            issue=PARENT,
            finding=compose_campaign_finding(new_posts=0, changed_children=0),
            agent_work_identifier=compose_campaign_identifier(issue=PARENT),
            ended_round=1,
            children=(),
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
    script_lead_turn(harnesses=harnesses)

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
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    [call] = harnesses["claude"].calls
    assert "--resume" not in call.arguments
    assert call.prompt.startswith("Acknowledge GH20.\n\n")
    assert "Your previous round did not finish." in call.prompt


def test_two_errored_rounds_put_a_campaign_in_fault(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    offer_parent(gh=gh)

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows == [
        compose_campaign_row(
            issue=PARENT,
            finding=None,
            agent_work_identifier=compose_campaign_identifier(issue=PARENT),
            ended_round=2,
            children=(),
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
    show_parent(gh=gh, issue=compose_parent_issue())
    show_parent(gh=gh, issue=compose_parent_issue(number=21))

    observed = tick(scheduler=scheduler)

    assert observed.cooldown is not None


def test_a_closed_campaign_pull_request_needs_a_new_label_application_to_start_again(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    directory = write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    offer_campaign_pull_request(gh=gh, state="CLOSED")
    script_lead_turn(harnesses=harnesses)
    wrap_up = tick(scheduler=scheduler)
    finish(scheduler=scheduler)
    assert wrap_up.launched_agent_work_identifiers == [directory.name]
    assert (
        read_lead_input(scheduler=scheduler, number=2).pull_request_state
        is PullRequestState.CLOSED
    )

    offer_parent(gh=gh)
    reopened = tick(scheduler=scheduler)
    assert reopened.launched_agent_work_identifiers == []
    [held] = reopened.rows
    assert held.finding == RequestConsumedFinding()
    assert len(harnesses["claude"].calls) == 1

    reapplied_at = LABEL_APPLIED_AT + timedelta(seconds=1)
    offer_labelling_events(
        gh=gh,
        issue=PARENT,
        events=[
            compose_labelling_event(label=LABEL),
            compose_labelling_event(label=LABEL, applied_at=reapplied_at),
        ],
    )
    script_lead_turn(harnesses=harnesses)
    restarted = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    [identifier] = restarted.launched_agent_work_identifiers
    assert identifier != directory.name
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    assert campaign.identifier == identifier
    assert campaign.record.label_applied_at == reapplied_at


def test_a_campaign_pull_request_that_cannot_be_read_starts_no_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[InterruptedAgentRoundEnding()])
    gh.fails(stderr="GitHub is down", to=f"pr view {CAMPAIGN_PULL_REQUEST}")

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
    script_lead_turn(harnesses=harnesses, delay=10)
    tick(scheduler=scheduler)

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows[0].finding == compose_campaign_finding(
        new_posts=0, changed_children=0
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
    both = compose_parent_issue(labels=(LABEL, "dream:steward"))
    offer_listing(gh=gh, issues=[both])

    observed = tick(scheduler=scheduler)

    conflict = ConflictingLabelsFinding(labels=[LABEL, "dream:steward"])
    assert observed.rows == [
        compose_campaign_row(issue=PARENT, finding=conflict, children=None),
        compose_campaign_row(
            issue=PARENT, label="dream:steward", finding=conflict, children=None
        ),
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
        compose_campaign_row(
            issue=PARENT,
            finding=StartTimeFinding(
                linked_pull_requests=[],
                blocking_issues=[
                    IssueReference(number=18),
                    IssueReference(number=1016, repository="alimanfoo/dream"),
                ],
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
    script_lead_turn(harnesses=harnesses)

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
    offer_posts(gh=gh, posts=[compose_pull_request_post(identifier=1)])
    script_lead_turn(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert observed.rows[0].finding == compose_campaign_finding(
        new_posts=1, changed_children=0
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
        compose_campaign_row(
            issue=PARENT,
            finding=UNCLAIMED,
            children=(),
        )
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
    offer_posts(gh=gh, posts=[])
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    observed = tick(scheduler=scheduler)

    assert [(row.kind, row.issue) for row in observed.rows] == [
        (AgentWorkKind.ASSIGNMENT, 30),
        (AgentWorkKind.CAMPAIGN, PARENT),
    ]


def test_the_three_kinds_take_turns_for_free_slots(cloned_repo, gh, harnesses):
    configure(root=cloned_repo, head=CONVERSATION_CLAUDE + CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=cloned_repo)
    scheduler.max_agents = 4
    for issue in (13, 14):
        write_assignment(
            state=scheduler.context.state,
            identifier=f"GH{issue}-20260923-010000-assignment",
            issue=issue,
            pull_request=None,
        )
    offer_parent(gh=gh)
    conversation = compose_parent_issue(labels=("dream:conversation",), number=8)
    offer_listing(gh=gh, issues=[compose_parent_issue(), conversation])
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
        "GH20",
        "GH8",
        "GH14",
    ]
    assert len(observed.launched_agent_work_identifiers) == 4


def test_one_listing_finds_the_requests_of_every_kind(cloned_repo, gh):
    configure(root=cloned_repo, head=CONVERSATION_CLAUDE + CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=cloned_repo)
    scheduler.max_agents = 0
    offer_listing(
        gh=gh,
        issues=[
            compose_parent_issue(labels=(SMITH,), number=13),
            compose_parent_issue(labels=("dream:conversation",), number=8),
            compose_parent_issue(),
        ],
    )

    observed = tick(scheduler=scheduler)

    assert [(row.kind, row.issue) for row in observed.rows] == [
        (AgentWorkKind.CONVERSATION, 8),
        (AgentWorkKind.ASSIGNMENT, 13),
        (AgentWorkKind.CAMPAIGN, PARENT),
    ]
    listings = [call for call in gh.calls if call.arguments[:2] == ["issue", "list"]]
    assert len(listings) == 1


def test_a_failed_listing_starts_no_request_of_any_kind(cloned_repo, gh, harnesses):
    configure(root=cloned_repo, head=CONVERSATION_CLAUDE + CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=cloned_repo)
    offer_listing(
        gh=gh,
        issues=[
            compose_parent_issue(labels=(SMITH,), number=13),
            compose_parent_issue(labels=("dream:conversation",), number=8),
            compose_parent_issue(),
        ],
    )
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")

    observed = tick(scheduler=scheduler)

    assert observed.failures == [
        "could not list issues: gh issue list: gh: could not connect to github.com"
    ]
    assert observed.rows == []
    assert harnesses["claude"].calls == []


def test_a_codex_lead_works_under_codexs_reviewer_without_a_final_file(
    cloned_repo, gh, harnesses
):
    configure(root=cloned_repo, head=CODEX_CAMPAIGN)
    scheduler = create_scheduler(root=cloned_repo, harness=AgentHarness.CODEX)
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


def test_a_pull_request_post_wakes_the_lead_without_resetting_its_worktree(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    root = scheduler.context.state.root
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    campaign_readme = campaign.worktree / "README.md"
    local_edit = b"an uncommitted edit on the campaign branch\n"
    campaign_readme.write_bytes(local_edit)
    rename_default_branch(checkout=root, branch="trunk")
    (root / "README.md").write_bytes(b"what the default branch holds now\n")
    commit(path=root, message="change the default branch")
    run_git(arguments=["push", "origin", "trunk"], cwd=root)
    offer_parent(gh=gh)
    question = compose_pull_request_post(
        identifier=1, body="How far have the stages got?"
    )
    offer_posts(gh=gh, posts=[question])
    script_lead_turn(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert launched.rows[0].finding == compose_campaign_finding(
        new_posts=1, changed_children=0
    )
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.user_posts == [IssueComment.model_validate(question)]
    assert given.pull_request_head == HEAD
    assert campaign_readme.read_bytes() == local_edit
    assert run_git(
        arguments=["branch", "--show-current"], cwd=campaign.worktree
    ).strip() == (compose_work_branch(identifier=campaign.identifier))
    [call] = harnesses["claude"].calls
    assert call.arguments[-2:] == ["--resume", "lead-session"]
    assert call.prompt.startswith("Campaign input for parent issue GH20:")


def test_a_conflict_wakes_the_finishing_lead_and_a_draft_returns_to_coordinating(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    script_lead_turn(harnesses=harnesses)
    offer_campaign_pull_request(gh=gh, is_draft=False, merge_state="DIRTY")

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    branch = compose_work_branch(identifier=campaign.identifier)
    [conflict] = harnesses["claude"].calls
    assert conflict.prompt.startswith("Your pull request is behind its base branch")
    assert f"campaign branch `{branch}` and pull it" in conflict.prompt
    assert read_lead_input(scheduler=scheduler, number=2).signals == [
        PullRequestSignal.OUT_OF_DATE
    ]

    ready_post = compose_pull_request_post(identifier=1, body="Please update the docs.")
    offer_campaign_pull_request(gh=gh, is_draft=False)
    offer_posts(gh=gh, posts=[ready_post])
    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    _, feedback = harnesses["claude"].calls
    assert f"campaign branch `{branch}` and pull it" in feedback.prompt
    given = read_lead_input(scheduler=scheduler, number=3)
    assert given.signals == []
    assert given.user_posts == [IssueComment.model_validate(ready_post)]

    offer_campaign_pull_request(
        gh=gh,
        is_draft=True,
        merge_state="DIRTY",
        head="f" * 40,
        checks=[compose_check_run(conclusion="FAILURE")],
    )
    assert tick(scheduler=scheduler).launched_agent_work_identifiers == []

    draft_post = compose_pull_request_post(identifier=2, body="Dispatch the new issue.")
    offer_posts(gh=gh, posts=[ready_post, draft_post])
    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    _, _, coordinating = harnesses["claude"].calls
    assert "Wait until you judge every sub-issue done" in coordinating.prompt
    given = read_lead_input(scheduler=scheduler, number=4)
    assert given.signals == []
    assert given.user_posts == [IssueComment.model_validate(draft_post)]


def test_a_finishing_lead_gets_two_attempts_at_a_red_build(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    script_lead_turn(harnesses=harnesses)
    failing_checks = [compose_check_run(conclusion="FAILURE")]

    for number in (2, 3):
        head = str(number) * 40
        offer_campaign_pull_request(
            gh=gh, is_draft=False, head=head, checks=failing_checks
        )
        tick(scheduler=scheduler)
        finish(scheduler=scheduler)

        given = read_lead_input(scheduler=scheduler, number=number)
        assert given.pull_request_head == head
        assert given.signals == [PullRequestSignal.CHECK_FAILURE]
        assert tick(scheduler=scheduler).launched_agent_work_identifiers == []

    offer_campaign_pull_request(
        gh=gh, is_draft=False, head="4" * 40, checks=failing_checks
    )
    withheld = tick(scheduler=scheduler)

    assert withheld.launched_agent_work_identifiers == []
    finding = find_campaign_row(observed=withheld).finding
    assert isinstance(finding, PullRequestFinding)
    assert finding.is_check_failure_withheld
    first, second = harnesses["claude"].calls
    for call in (first, second):
        assert call.prompt.startswith("Checks failed on your pull request's latest")
        assert "Carry the campaign's pull request to merge." in call.prompt


def test_the_leads_own_marked_replies_wake_nothing(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    offer_parent(gh=gh)
    offer_posts(
        gh=gh,
        posts=[
            compose_pull_request_post(
                identifier=1, body=f"Stage 1 is done.\n\n{AGENT_POST_MARKER}"
            )
        ],
    )

    observed = tick(scheduler=scheduler)

    assert observed.launched_agent_work_identifiers == []
    assert observed.rows[0].finding == compose_campaign_finding(
        new_posts=0, changed_children=0
    )
    assert harnesses["claude"].calls == []


def test_a_stopped_lead_waits_for_fresh_direction_and_is_told_it_was_stopped(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    first = compose_pull_request_post(identifier=1, body="Review stage 1.")
    write_rounds(
        state=scheduler.context.state,
        endings=[StoppedAgentRoundEnding(at=PINNED)],
        delivered=[[first]],
    )
    offer_parent(gh=gh)
    offer_posts(gh=gh, posts=[first])
    waiting = tick(scheduler=scheduler)
    redirect = compose_pull_request_post(identifier=2, body="Review stage 2 instead.")
    offer_posts(gh=gh, posts=[first, redirect])
    script_lead_turn(harnesses=harnesses)

    redirected = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert waiting.launched_agent_work_identifiers == []
    assert redirected.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).user_posts == [
        IssueComment.model_validate(redirect)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("The user stopped your previous round")


@pytest.mark.parametrize("ending", [InterruptedAgentRoundEnding(), ERRORED])
def test_an_unfinished_rounds_posts_are_given_again_with_any_since(
    campaign_scheduler, harnesses, ending
):
    scheduler, gh = campaign_scheduler
    first, second, third = (
        compose_pull_request_post(identifier=identifier) for identifier in (1, 2, 3)
    )
    write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), ending],
        delivered=[[first], [second]],
    )
    offer_parent(gh=gh)
    offer_posts(gh=gh, posts=[first, second, third])
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=3)
    assert given.user_posts == [
        IssueComment.model_validate(item) for item in (second, third)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Your previous round did not finish.")


def test_a_recovery_with_no_new_post_keeps_posts_behind_the_cursor(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    first = compose_pull_request_post(identifier=1)
    write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED), InterruptedAgentRoundEnding()],
        delivered=[[first], []],
    )
    offer_parent(gh=gh)
    offer_posts(gh=gh, posts=[first])
    script_lead_turn(harnesses=harnesses)

    recovered = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert recovered.rows[0].finding == compose_campaign_finding(
        new_posts=0, changed_children=0
    )
    given = read_lead_input(scheduler=scheduler, number=3)
    assert given.user_posts == []


def test_pull_request_posts_that_cannot_be_read_start_no_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[InterruptedAgentRoundEnding()])
    offer_parent(gh=gh)
    gh.fails(stderr="GitHub is down", to=POSTS_PATH)

    observed = tick(scheduler=scheduler)

    assert isinstance(observed.rows[0].finding, ReadFailureFinding)
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def test_a_delivered_input_that_cannot_be_read_fails_the_update(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    round_input = campaign.compose_round_paths(number=1).round_input
    round_input.write_bytes(b"{")
    offer_parent(gh=gh)
    offer_posts(gh=gh, posts=[compose_pull_request_post(identifier=1)])

    with pytest.raises(ReportableError, match=r"round-input\.json is not valid"):
        tick(scheduler=scheduler)

    assert count_post_reads(gh=gh) == 0
    assert harnesses["claude"].calls == []


def test_an_open_campaign_with_no_round_yet_starts_its_lead(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_campaign(
        state=scheduler.context.state, issue=PARENT, harness_session_identifier=None
    )
    offer_parent(gh=gh)
    script_lead_turn(harnesses=harnesses)

    launched = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert launched.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Acknowledge GH20.\n\n")


def test_a_retry_clears_the_fault_and_the_lead_recovers(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    campaign = read_campaign(state=scheduler.context.state, issue=PARENT)
    assert campaign is not None
    request_agent_work_retry(work=campaign, at=ERRORED.at + timedelta(minutes=1))
    offer_parent(gh=gh)
    script_lead_turn(harnesses=harnesses)

    retried = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert retried.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    [call] = harnesses["claude"].calls
    assert call.prompt.startswith("Your previous round did not finish.")


def test_a_codex_lead_resumes_its_session_for_a_pull_request_post(
    cloned_repo, gh, harnesses
):
    configure(root=cloned_repo, head=CODEX_CAMPAIGN)
    scheduler = create_scheduler(root=cloned_repo, harness=AgentHarness.CODEX)
    state = scheduler.context.state
    script_campaign_opening(gh=gh)
    directory = write_campaign(
        state=state,
        issue=PARENT,
        harness=AgentHarness.CODEX,
        harness_session_identifier="lead-codex-session",
    )
    write_work_pull_request(directory=directory, number=CAMPAIGN_PULL_REQUEST)
    check_out_campaign(state=state, identifier=directory.name)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, ending=SuccessfulAgentRoundEnding(at=PINNED)
        ),
        round_input=CampaignRoundInput(
            pull_request=CAMPAIGN_PULL_REQUEST,
            pull_request_state=PullRequestState.OPEN,
            pull_request_head=HEAD,
            signals=[],
            children=[],
            notifications=[],
            user_posts=[],
            assignment_routes=[],
        ),
    )
    offer_parent(gh=gh)
    offer_posts(gh=gh, posts=[compose_pull_request_post(identifier=1)])
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
    assert read_lead_input(scheduler=scheduler, number=2).pull_request_head == HEAD


FIRST_CHILD = 21
SECOND_CHILD = 22
CHILD_ASSIGNMENT = "GH21-20260923-010000-assignment"
CHILDREN_PATH = f"api repos/{REPOSITORY}/issues/{PARENT}/sub_issues?per_page=100"
SMITH = "dream:smith"
FOREIGN = "other/tools"


def compose_sub_issue(
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
    """Write a campaign whose lead consumed its input, given these children.

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


def compose_child(**fields) -> CampaignChild:
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


def compose_child_assignment(**fields) -> CampaignChildAssignment:
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


def test_a_faulted_lead_still_observes_every_child_in_githubs_order(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(state=scheduler.context.state, endings=[ERRORED, ERRORED])
    offer_children(
        gh=gh,
        children=[
            compose_sub_issue(number=SECOND_CHILD, state="closed"),
            compose_sub_issue(number=FIRST_CHILD),
        ],
    )

    observed = tick(scheduler=scheduler)

    assert observed.rows == [
        compose_campaign_row(
            issue=PARENT,
            finding=None,
            agent_work_identifier=compose_campaign_identifier(issue=PARENT),
            ended_round=2,
            children=[
                compose_child(
                    issue=SECOND_CHILD,
                    title=f"Stage {SECOND_CHILD}",
                    state=IssueState.CLOSED,
                ),
                compose_child(),
            ],
        )
    ]


def test_a_child_whose_assignment_may_start_has_work_due(campaign_scheduler, harnesses):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    offer_listing(
        gh=gh,
        issues=[
            compose_parent_issue(),
            compose_parent_issue(labels=(SMITH,), number=FIRST_CHILD),
        ],
    )
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)

    assert observe_children(scheduler=scheduler) == [compose_child(is_settled=False)]


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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        compose_child(
            is_settled=False,
            assignment=compose_child_assignment(
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    gh.replies(
        stdout=compose_pull_request(
            state="OPEN",
            merge_state="UNKNOWN",
            checks=[compose_check_run(), compose_check_run(status="IN_PROGRESS")],
        ),
        to="pr view",
    )

    assert observe_children(scheduler=scheduler) == [
        compose_child(
            assignment=compose_child_assignment(
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        compose_child(
            assignment=compose_child_assignment(finished_turn=1, is_fault=True)
        )
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
    offer_children(
        gh=gh, children=[compose_sub_issue(number=FIRST_CHILD, state="closed")]
    )

    assert observe_children(scheduler=scheduler) == [
        compose_child(
            state=IssueState.CLOSED,
            assignment=compose_child_assignment(
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        compose_child(
            is_settled=False,
            assignment=compose_child_assignment(ending=AgentWorkEndReason.CANCELLED),
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])

    assert observe_children(scheduler=scheduler) == [
        compose_child(
            is_settled=False,
            assignment=compose_child_assignment(
                identifier=replacement, pull_request=None
            ),
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
        children=[
            compose_sub_issue(number=FIRST_CHILD),
            compose_sub_issue(number=SECOND_CHILD),
        ],
    )
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=1)
    assert given.children == [
        compose_child(
            assignment=compose_child_assignment(
                observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=1
            )
        ),
        compose_child(issue=SECOND_CHILD, title=f"Stage {SECOND_CHILD}"),
    ]
    assert given.assignment_routes == scheduler.context.config.assignment


def fail_to_list_children(*, gh) -> None:
    """Have GitHub fail to list the parent's children."""
    gh.fails(stderr="gh: could not connect to github.com", to=CHILDREN_PATH)


def fail_to_read_the_childs_pull_request(*, gh) -> None:
    """Have the first child's assignment fail to read its pull request."""
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    gh.fails(stderr="gh: could not connect to github.com", to="pr view")


def fail_to_list_issues(*, gh) -> None:
    """Have the listing of the open issues assigned to the account fail."""
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    gh.fails(stderr="gh: could not connect to github.com", to="issue list")


def offer_a_foreign_child(*, gh) -> None:
    """List a child from another repository, numbered like the local child."""
    offer_children(
        gh=gh, children=[compose_sub_issue(number=FIRST_CHILD, repository=FOREIGN)]
    )


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
            fail_to_list_issues,
            False,
            "could not observe sub-issue 21: could not list issues: gh issue list: ",
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
    offer_posts(gh=gh, posts=[compose_pull_request_post(identifier=1)])
    fail(gh=gh)

    observed = tick(scheduler=scheduler)

    [row] = [row for row in observed.rows if row.kind is AgentWorkKind.CAMPAIGN]
    assert row.children is None
    assert isinstance(row.finding, ReadFailureFinding)
    assert row.finding.reason.startswith(reason)
    assert count_post_reads(gh=gh) == 0
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
        compose_campaign_row(
            issue=PARENT,
            finding=ReadFailureFinding(
                reason=f"gh {CHILDREN_PATH}: gh: could not connect to github.com"
            ),
            children=None,
        )
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None


WORKING = compose_child(
    is_settled=False,
    assignment=compose_child_assignment(
        observed_pull_request=DRAFT_PULL_REQUEST, finished_turn=1
    ),
)
UNSTARTED = compose_child(issue=SECOND_CHILD, title=f"Stage {SECOND_CHILD}")
BOTH_CHILDREN = [
    compose_sub_issue(number=FIRST_CHILD),
    compose_sub_issue(number=SECOND_CHILD),
]


def find_campaign_row(*, observed) -> RequestRow:
    """Return the campaign's row among those that the tick observed."""
    [row] = [row for row in observed.rows if row.kind is AgentWorkKind.CAMPAIGN]
    return row


def compose_notification(*, issue: int, changes: list[CampaignChildChange]):
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
    script_lead_turn(harnesses=harnesses)

    woken = tick(scheduler=scheduler)
    finish(scheduler=scheduler)
    after = tick(scheduler=scheduler)

    assert woken.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert find_campaign_row(observed=woken).finding == compose_campaign_finding(
        new_posts=0, changed_children=1
    )
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.notifications == [
        compose_notification(issue=FIRST_CHILD, changes=[CampaignChildChange.HANDBACK])
    ]
    assert given.children == [
        compose_child(
            assignment=compose_child_assignment(
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
            compose_child(
                assignment=compose_child_assignment(
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
    offer_children(
        gh=gh, children=[compose_sub_issue(number=FIRST_CHILD, state="closed")]
    )
    gh.replies(stdout=compose_pull_request(state="MERGED", head="f00d"), to="pr view")

    observed = tick(scheduler=scheduler)

    assert find_campaign_row(observed=observed).finding == compose_campaign_finding(
        new_posts=0, changed_children=0
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
            compose_child(
                assignment=compose_child_assignment(
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    gh.replies(
        stdout=compose_pull_request(
            state="OPEN", checks=[compose_check_run(conclusion="FAILURE")]
        ),
        to="pr view",
    )

    observed = tick(scheduler=scheduler)

    [child_seen] = find_campaign_row(observed=observed).children or []
    assert child_seen.is_settled is False
    assert find_campaign_row(observed=observed).finding == compose_campaign_finding(
        new_posts=0, changed_children=0
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
            compose_child(
                assignment=compose_child_assignment(
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    gh.replies(
        stdout=compose_pull_request(state="OPEN", merge_state=seen), to="pr view"
    )
    script_lead_turn(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    expected = (
        [compose_notification(issue=FIRST_CHILD, changes=changes)] if changes else []
    )
    assert find_campaign_row(observed=observed).finding == compose_campaign_finding(
        new_posts=0, changed_children=len(expected)
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
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.notifications == [
        compose_notification(issue=SECOND_CHILD, changes=[CampaignChildChange.ADDED])
    ]
    assert given.children == [WORKING, UNSTARTED]


def test_posts_and_changes_among_the_children_share_one_round(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state, children=[UNSTARTED])
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    question = compose_pull_request_post(identifier=1, body="Which stage is next?")
    offer_posts(gh=gh, posts=[question])
    script_lead_turn(harnesses=harnesses)

    woken = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert find_campaign_row(observed=woken).finding == compose_campaign_finding(
        new_posts=1, changed_children=2
    )
    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.user_posts == [IssueComment.model_validate(question)]
    assert given.notifications == [
        compose_notification(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED]),
        compose_notification(issue=SECOND_CHILD, changes=[CampaignChildChange.REMOVED]),
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
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
    script_lead_turn(harnesses=harnesses)

    after = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert during.launched_agent_work_identifiers == []
    assert find_campaign_row(observed=during).finding == compose_campaign_finding(
        new_posts=0, changed_children=1
    )
    assert after.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=3).notifications == [
        compose_notification(issue=FIRST_CHILD, changes=[CampaignChildChange.HANDBACK])
    ]


def test_a_lead_at_capacity_is_given_the_changes_once_a_slot_frees(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    settle_lead(state=scheduler.context.state)
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    scheduler.rounds["busy-assignment"] = Mock(is_alive=True)
    delayed = tick(scheduler=scheduler)
    del scheduler.rounds["busy-assignment"]
    offer_children(gh=gh, children=BOTH_CHILDREN)
    script_lead_turn(harnesses=harnesses)

    freed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert delayed.launched_agent_work_identifiers == []
    assert find_campaign_row(observed=delayed).finding == compose_campaign_finding(
        new_posts=0, changed_children=1
    )
    assert freed.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).notifications == [
        compose_notification(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED]),
        compose_notification(issue=SECOND_CHILD, changes=[CampaignChildChange.ADDED]),
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
    offer_children(gh=gh, children=[compose_sub_issue(number=SECOND_CHILD)])

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
        pictures=[[], [compose_child()]],
    )
    offer_parent(gh=gh)
    offer_children(gh=gh, children=BOTH_CHILDREN)
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert read_lead_input(scheduler=scheduler, number=3).notifications == [
        compose_notification(issue=FIRST_CHILD, changes=[CampaignChildChange.ADDED]),
        compose_notification(issue=SECOND_CHILD, changes=[CampaignChildChange.ADDED]),
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert read_lead_input(scheduler=scheduler, number=2).notifications == [
        compose_notification(
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
        children=[
            compose_child(is_settled=False, assignment=compose_child_assignment())
        ],
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
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    script_lead_turn(harnesses=harnesses)

    observed = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    if is_stopping:
        assert observed.launched_agent_work_identifiers == []
    else:
        assert read_lead_input(scheduler=scheduler, number=2).notifications == [
            compose_notification(
                issue=FIRST_CHILD,
                changes=[CampaignChildChange.HANDBACK, CampaignChildChange.ENDING],
            )
        ]


def test_a_campaign_label_that_someone_else_applied_starts_no_lead(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    offer_labelling_events(
        gh=gh,
        issue=PARENT,
        events=[compose_labelling_event(label=LABEL, applier="colleague")],
    )

    held = tick(scheduler=scheduler)

    assert held.rows == [
        compose_campaign_row(
            issue=PARENT,
            finding=LabelAppliedByOtherFinding(applier="colleague"),
        )
    ]
    assert read_campaign(state=scheduler.context.state, issue=PARENT) is None
    assert harnesses["claude"].calls == []


def open_campaign_and_assignment(*, scheduler, gh, harnesses):
    """Start the campaign and its sub-issue's assignment on their branches."""
    state = scheduler.context.state
    root = state.root
    child = compose_parent_issue(labels=(SMITH,), number=FIRST_CHILD)
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    script_lead_turn(harnesses=harnesses)

    opened = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    [identifier] = opened.launched_agent_work_identifiers
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    assert campaign.identifier == identifier
    campaign_branch = compose_work_branch(identifier=identifier)
    opening_input = read_lead_input(scheduler=scheduler, number=1)
    assert opening_input.pull_request == CAMPAIGN_PULL_REQUEST
    assert opening_input.pull_request_head == read_worktree_revision(
        worktree=campaign.worktree
    )
    assert opening_input.children == [compose_child()]
    assert run_git(arguments=["rev-parse", "HEAD^"], cwd=campaign.worktree) == (
        run_git(arguments=["rev-parse", "main"], cwd=root)
    )

    child_pull_request = offer_child_assignment(
        gh=gh, child=child, campaign_head=opening_input.pull_request_head
    )

    assigned = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    [assignment] = read_agent_work_at_issue(state=state, issue=FIRST_CHILD)
    assert assigned.launched_agent_work_identifiers == [assignment.identifier]
    assert assignment.record.base_branch == campaign_branch
    assert read_work_pull_request_number(work=assignment) == child_pull_request
    assert run_git(
        arguments=["rev-parse", "HEAD^"], cwd=assignment.worktree
    ).strip() == (opening_input.pull_request_head)
    campaign_pr, child_pr = [
        call.arguments for call in gh.calls if call.arguments[:2] == ["pr", "create"]
    ]
    assert campaign_pr[4:] == [
        "--base",
        "main",
        "--head",
        campaign_branch,
        "--draft",
        "--title",
        f"Parent {PARENT}",
        "--body",
        f"Closes #{PARENT}",
    ]
    assert child_pr[child_pr.index("--base") + 1] == campaign_branch

    return campaign, assignment, child


def offer_child_assignment(*, gh, child: dict, campaign_head: str) -> int:
    """List the labelled sub-issue and let its assignment open a pull request."""
    offer_listing(gh=gh, issues=[compose_parent_issue(), child])
    offer_issue_parent(gh=gh, issue=child["number"], parent=PARENT)
    offer_campaign_pull_request(gh=gh, head=campaign_head)
    number = 52
    url = f"https://github.com/{REPOSITORY}/pull/{number}"
    gh.replies(stdout=url, to="pr create")
    gh.replies(stdout=json.dumps({"number": number}), to=f"pr view {url}")
    return number


def merge_sub_issue(*, scheduler, gh, campaign, assignment, child) -> str:
    """Merge the assignment and verify its wrap-up closes the sub-issue."""
    root = scheduler.context.state.root
    campaign_branch = compose_work_branch(identifier=campaign.identifier)
    child_pull_request = read_work_pull_request_number(work=assignment)
    assert child_pull_request is not None
    child_branch = compose_work_branch(identifier=assignment.identifier)
    run_git(arguments=["merge", "--ff-only", child_branch], cwd=campaign.worktree)
    run_git(arguments=["push", "origin", campaign_branch], cwd=root)
    campaign_head = read_worktree_revision(worktree=campaign.worktree)
    gh.replies(
        stdout=compose_pull_request(state="MERGED", number=child_pull_request),
        to=f"pr view {child_pull_request}",
    )
    show_parent(gh=gh, issue=child)
    closing_comment = f"repos/{REPOSITORY}/issues/{FIRST_CHILD}/comments"
    gh.replies(stdout='{"id": 91}', to=f"api {closing_comment} --method POST")
    gh.replies(stdout="", to=f"issue close {FIRST_CHILD}")
    offer_campaign_pull_request(gh=gh, head=campaign_head)

    child_wrap_up = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert child_wrap_up.launched_agent_work_identifiers == [assignment.identifier]
    [closed] = [call for call in gh.calls if call.arguments[:2] == ["issue", "close"]]
    assert closed.arguments[2:] == [
        str(FIRST_CHILD),
        "--repo",
        REPOSITORY,
        "--reason",
        "completed",
    ]
    [comment] = [
        call
        for call in gh.calls
        if call.arguments[:4] == ["api", closing_comment, "--method", "POST"]
    ]
    assert json.loads(comment.prompt) == {
        "body": f"Merged in #{child_pull_request}.\n\n{AGENT_POST_MARKER}"
    }

    return campaign_head


def test_a_campaign_delivers_its_sub_issue_through_the_campaign_branch(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    state = scheduler.context.state
    root = state.root
    campaign, assignment, child = open_campaign_and_assignment(
        scheduler=scheduler, gh=gh, harnesses=harnesses
    )
    identifier = campaign.identifier
    campaign_branch = compose_work_branch(identifier=identifier)
    campaign_head = merge_sub_issue(
        scheduler=scheduler,
        gh=gh,
        campaign=campaign,
        assignment=assignment,
        child=child,
    )

    offer_listing(gh=gh, issues=[compose_parent_issue()])
    offer_children(
        gh=gh, children=[compose_sub_issue(number=FIRST_CHILD, state="closed")]
    )
    notified = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert notified.launched_agent_work_identifiers == [identifier]
    assert not assignment.worktree.exists()
    delivered = read_lead_input(scheduler=scheduler, number=2)
    assert delivered.pull_request_head == campaign_head
    [closed_child] = delivered.children
    assert closed_child.is_closed
    assert closed_child.assignment is not None
    assert closed_child.assignment.ending is AgentWorkEndReason.COMPLETED
    [notification] = delivered.notifications
    assert notification.issue == FIRST_CHILD
    assert CampaignChildChange.ISSUE_STATE in notification.changes
    assert CampaignChildChange.ENDING in notification.changes

    run_git(arguments=["merge", "--ff-only", campaign_branch], cwd=root)
    run_git(arguments=["push", "origin", "main"], cwd=root)
    offer_listing(gh=gh, issues=[])
    offer_campaign_pull_request(gh=gh, state="MERGED", head=campaign_head)
    wrap_up = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert wrap_up.launched_agent_work_identifiers == [identifier]
    assert read_lead_input(scheduler=scheduler, number=3).pull_request_state is (
        PullRequestState.MERGED
    )
    ended = read_campaign(state=state, issue=PARENT)
    assert ended is not None
    assert ended.ending is not None
    assert ended.ending.reason is AgentWorkEndReason.COMPLETED
    assert campaign.worktree.is_dir()

    cleaned = tick(scheduler=scheduler)

    assert cleaned.launched_agent_work_identifiers == []
    assert cleaned.failures == []
    assert not campaign.worktree.exists()
    local_branches = run_git(
        arguments=["branch", "--format=%(refname:short)"], cwd=root
    )
    assert campaign_branch not in local_branches.splitlines()


def test_a_campaign_keeps_its_pr_channel_after_its_parent_changes(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    parent = compose_parent_issue(state="CLOSED", labels=(), assignees=())
    offer_listing(gh=gh, issues=[])
    show_parent(gh=gh, issue=parent)
    gh.replies(
        stdout=compose_page(items=[compose_comment(body="A parent comment.")]),
        to=PARENT_COMMENTS_PATH,
    )

    quiet = tick(scheduler=scheduler)

    assert quiet.launched_agent_work_identifiers == []
    assert quiet.rows[0].finding == compose_campaign_finding()
    assert not any(
        call.arguments[:3] == ["issue", "view", str(PARENT)]
        or call.arguments[:2] == PARENT_COMMENTS_PATH.split()[:2]
        for call in gh.calls
    )
    post = compose_pull_request_post(identifier=1)
    offer_posts(gh=gh, posts=[post])
    script_lead_turn(harnesses=harnesses)

    woken = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    assert woken.launched_agent_work_identifiers == [
        compose_campaign_identifier(issue=PARENT)
    ]
    assert read_lead_input(scheduler=scheduler, number=2).user_posts == [
        IssueComment.model_validate(post)
    ]


def test_an_open_campaign_answers_every_campaign_label(campaign_scheduler):
    scheduler, gh = campaign_scheduler
    root = scheduler.context.state.root
    configure(root=root, head=CAMPAIGN_CLAUDE + SECOND_CAMPAIGN_CLAUDE)
    scheduler = create_scheduler(root=root)
    directory = write_rounds(
        state=scheduler.context.state, endings=[SuccessfulAgentRoundEnding(at=PINNED)]
    )
    offer_parent(gh=gh, issue=compose_parent_issue(labels=(LABEL, "dream:steward")))

    observed = tick(scheduler=scheduler)

    [row] = observed.rows
    assert row.agent_work_identifier == directory.name
    assert row.finding == compose_campaign_finding()
    assert observed.launched_agent_work_identifiers == []


def offer_campaign_claim(*, gh) -> None:
    """Have GitHub report that the open campaign pull request claims the parent."""
    gh.replies(
        stdout=json.dumps(
            {
                "number": PARENT,
                "closedByPullRequestsReferences": [{"number": CAMPAIGN_PULL_REQUEST}],
            }
        ),
        to=(
            f"issue view {PARENT} --repo {REPOSITORY} "
            "--json number,closedByPullRequestsReferences"
        ),
    )


def test_an_open_pull_request_claiming_the_parent_holds_a_new_campaign(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    offer_parent(gh=gh)
    offer_campaign_claim(gh=gh)

    observed = tick(scheduler=scheduler)

    [row] = observed.rows
    assert row.finding == StartTimeFinding(
        linked_pull_requests=[CAMPAIGN_PULL_REQUEST], blocking_issues=[]
    )
    assert row.children is None
    assert observed.launched_agent_work_identifiers == []
    assert harnesses["claude"].calls == []


def cancel_campaign_from_page(*, state: StateDirectory, identifier: str) -> None:
    """Check the campaign's cancel control and submit it."""
    path = f"/work/{identifier}"
    client = _create_app(state=state).test_client()
    page = client.get(path)
    assert page.status_code == 200
    assert f'action="{path}/cancel"' in page.text
    response = client.post(f"{path}/cancel", headers={"Origin": "http://localhost"})
    assert response.status_code == 303
    assert response.location == path
    assert f'action="{path}/cancel"' not in client.get(path).text


@pytest.mark.parametrize("surface", ["cli", "web"])
@pytest.mark.parametrize("is_running", [False, True], ids=["between-rounds", "working"])
def test_the_user_can_cancel_a_campaign_and_carry_on_its_branch(
    campaign_scheduler, harnesses, monkeypatch, surface, is_running
):
    scheduler, gh = campaign_scheduler
    state = scheduler.context.state
    offer_parent(gh=gh)
    offer_children(gh=gh, children=[compose_sub_issue(number=FIRST_CHILD)])
    script_lead_turn(harnesses=harnesses, delay=30 if is_running else 0)
    opened = tick(scheduler=scheduler)
    [identifier] = opened.launched_agent_work_identifiers
    if not is_running:
        finish(scheduler=scheduler)
    campaign = read_campaign(state=state, issue=PARENT)
    assert campaign is not None
    assert campaign.ending is None
    assert (campaign.rounds[0].outcome is AgentRoundOutcome.RUNNING) is is_running
    assert read_work_pull_request_number(work=campaign) == CAMPAIGN_PULL_REQUEST
    campaign_head = read_worktree_revision(worktree=campaign.worktree)
    campaign_branch = compose_work_branch(identifier=identifier)

    if surface == "cli":
        monkeypatch.chdir(state.root)
        assert main(argv=["cancel", identifier]) == 0
    else:
        cancel_campaign_from_page(state=state, identifier=identifier)

    paths = campaign.compose_round_paths(number=1)
    assert paths.stop_request.exists() is is_running
    finish(scheduler=scheduler)

    child = compose_parent_issue(labels=(SMITH,), number=FIRST_CHILD)
    child_pull_request = offer_child_assignment(
        gh=gh, child=child, campaign_head=campaign_head
    )
    offer_campaign_claim(gh=gh)
    offer_labelling_events(
        gh=gh,
        issue=PARENT,
        events=[
            compose_labelling_event(
                label=LABEL, applied_at=LABEL_APPLIED_AT + timedelta(seconds=1)
            )
        ],
    )
    script_lead_turn(harnesses=harnesses)
    continued = tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    ended = read_campaign(state=state, issue=PARENT)
    assert ended is not None
    assert ended.identifier == identifier
    assert ended.ending is not None
    assert ended.ending.reason is AgentWorkEndReason.CANCELLED
    [lead_round] = ended.rounds
    assert lead_round.outcome is (
        AgentRoundOutcome.STOPPED if is_running else AgentRoundOutcome.SUCCESSFUL
    )
    assert read_work_pull_request_number(work=ended) == CAMPAIGN_PULL_REQUEST
    assert read_worktree_revision(worktree=ended.worktree) == campaign_head
    assert (
        run_git(arguments=["rev-parse", campaign_branch], cwd=state.root).strip()
        == campaign_head
    )
    assert find_campaign_row(observed=continued).finding == StartTimeFinding(
        linked_pull_requests=[CAMPAIGN_PULL_REQUEST], blocking_issues=[]
    )
    [assignment] = read_agent_work_at_issue(state=state, issue=FIRST_CHILD)
    assert continued.failures == []
    assert continued.launched_agent_work_identifiers == [assignment.identifier]
    assert read_work_pull_request_number(work=assignment) == child_pull_request
    _, child_pr = [
        call.arguments for call in gh.calls if call.arguments[:2] == ["pr", "create"]
    ]
    assert child_pr[child_pr.index("--base") + 1] == campaign_branch


def test_campaign_posts_seen_in_the_same_github_second_are_relayed_once(
    campaign_scheduler, harnesses
):
    scheduler, gh = campaign_scheduler
    first = compose_pull_request_post(identifier=1)
    second = compose_comment(id=2, created_at=first["created_at"])
    write_rounds(
        state=scheduler.context.state,
        endings=[SuccessfulAgentRoundEnding(at=PINNED)],
        delivered=[[first]],
    )
    offer_posts(gh=gh, posts=[first, second])
    script_lead_turn(harnesses=harnesses)

    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=2)
    assert given.user_posts == [IssueComment.model_validate(second)]

    review = compose_review(id=1, body="Review note.", submitted_at=first["created_at"])
    gh.replies(
        stdout=compose_page(items=[review]),
        to=f"api repos/{REPOSITORY}/pulls/{CAMPAIGN_PULL_REQUEST}/reviews?per_page=100",
    )
    tick(scheduler=scheduler)
    finish(scheduler=scheduler)

    given = read_lead_input(scheduler=scheduler, number=3)
    [new] = given.user_posts
    assert (new.kind, new.id) == ("review", 1)
    assert tick(scheduler=scheduler).launched_agent_work_identifiers == []
