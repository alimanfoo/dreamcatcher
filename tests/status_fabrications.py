"""Fabricate local status-report states shared by presentation tests."""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType

from clocks import PINNED
from conftest import ASSIGNMENT_LABEL, DAEMON_PID, REPOSITORY, compose_comment
from records import (
    HEAD,
    MERGED_INPUT,
    compose_campaign_identifier,
    compose_conversation_identifier,
    hold_daemon_lock_for_test,
    release_daemon_lock,
    write_assignment,
    write_campaign,
    write_conversation,
    write_daemon_run,
    write_ending,
    write_feed,
    write_final_output,
    write_round,
    write_tick,
)
from rows import UNCLAIMED, compose_request_row

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    cancel_assignment,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWorkEndReason, read_agent_work_at_issue
from dreamcatcher.campaigns import (
    CampaignChild,
    CampaignChildAssignment,
    CampaignRoundInput,
)
from dreamcatcher.documents import write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    IssueState,
    PullRequestMergeState,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind, HarnessSessionIdentifier
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    InitialConversationIssue,
)
from dreamcatcher.scheduler.models import (
    BlockingIssuesFinding,
    CampaignFinding,
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    IssueReference,
    PauseCause,
    PausedFinding,
    PullRequestFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    StartedRound,
    StartTimeFinding,
)
from dreamcatcher.state import StateDirectory

LOOKED_AT = PINNED + timedelta(hours=2)
ASSIGNMENT_TIMESTAMP = "20260819-184158"
HARNESS_SESSION_IDENTIFIER = "abc-123"


def _compose_assignment_row(
    *,
    issue: int,
    ended_round: int | None = None,
    finding: RequestFinding | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of the assignment that the fabrications write at the issue."""
    return compose_request_row(
        issue=issue,
        agent_work_identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}-assignment",
        ended_round=ended_round,
        finding=finding,
        started_round=started_round,
    )


def _compose_draft_pull_request(*, new_posts: int = 0) -> PullRequestFinding:
    """Return what the tick reads of the draft that the fabrications open."""
    return PullRequestFinding(
        number=52,
        state=PullRequestState.OPEN,
        is_draft=True,
        merge_state=PullRequestMergeState.CLEAN,
        head=HEAD,
        check_result=CheckResult.PASSING,
        has_running_checks=False,
        new_posts=new_posts,
        new_pull_request_signals=[],
        is_check_failure_withheld=False,
        is_wrap_up_due=False,
    )


def compose_conversation_row(
    *, finding: RequestFinding, issue: int = 8, ended_round: int | None = None
) -> RequestRow:
    """Return the row of the conversation that the tests write at the issue."""
    return compose_request_row(
        issue=issue,
        kind=AgentWorkKind.CONVERSATION,
        agent_work_identifier=compose_conversation_identifier(issue=issue),
        ended_round=ended_round,
        finding=finding,
    )


SAID = (
    FeedLine(
        at=PINNED + timedelta(minutes=1),
        text="[harness session] model opus[1m], id 7f3c9a",
    ),
    FeedLine(at=PINNED + timedelta(minutes=2), text="I will read the issue first."),
    FeedLine(
        at=PINNED + timedelta(minutes=2),
        text="[Read] specs/2026-08-17-skeleton/plan.md",
    ),
    FeedLine(at=PINNED + timedelta(minutes=3), text="[Bash] ls"),
    FeedLine(
        at=PINNED + timedelta(minutes=3), text="[failed] no such file or directory"
    ),
    FeedLine(
        at=PINNED + timedelta(minutes=5),
        text=(
            "[usage] $0.1772, 455 output, 8 input, 123529 cache read, 8606 cache write"
        ),
    ),
    FeedLine(at=PINNED + timedelta(minutes=5), text="[result] success"),
)

DOUBLE_LABELLED = ConflictingLabelsFinding(labels=["dream:less", ASSIGNMENT_LABEL])


def fabricate_conversation(
    *,
    state: StateDirectory,
    has_round: bool = True,
    status: int = 0,
    is_paused: bool = True,
    harness_session_identifier: HarnessSessionIdentifier
    | None = "conversation-session",
) -> None:
    """Write one initial conversation exchange.

    The tick after a round that errored still finds its comment to answer.
    """
    directory = write_conversation(
        state=state,
        issue=8,
        harness_session_identifier=harness_session_identifier,
    )
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(minutes=5),
            finished=PINNED + timedelta(minutes=5),
            rows=[
                compose_conversation_row(
                    ended_round=1 if has_round else None,
                    finding=(
                        PausedFinding(cause=PauseCause.LABEL_REMOVED)
                        if is_paused
                        else IssueCommentsFinding(new_comments=int(status != 0))
                    ),
                )
            ],
        ),
    )
    if not has_round:
        return
    record = AgentRoundRecord(
        number=1,
        started=PINNED,
        pid=1,
        ending=_compose_agent_round_ending(
            at=PINNED + timedelta(minutes=4), status=status
        ),
    )
    write_round(
        directory=directory,
        number=1,
        record=record,
        round_input=ConversationRoundInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
            comments=[
                {
                    "id": 1,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123",
        ),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[compose_feed_line(record=record, text="I found the answer.", minutes=0)],
    )
    write_final_output(directory=directory, number=1, text="The answer.")


def compose_campaign_row(
    *, finding: RequestFinding | None, issue: int = 60, ended_round: int | None = None
) -> RequestRow:
    """Return the row of the campaign that the tests write at the parent."""
    return compose_request_row(
        issue=issue,
        kind=AgentWorkKind.CAMPAIGN,
        agent_work_identifier=compose_campaign_identifier(issue=issue),
        ended_round=ended_round,
        finding=finding,
    )


def _compose_campaign_child(
    *,
    issue: int,
    state: IssueState,
    is_settled: bool,
    finished_turn: int | None = None,
    ending: AgentWorkEndReason | None = None,
) -> CampaignChild:
    """Return one child of the idle campaign's parent, with the issue's assignment.

    A child that took no turn and has no ending has no assignment.
    """
    return CampaignChild(
        issue=issue,
        title=f"Issue {issue}",
        state=state,
        is_settled=is_settled,
        assignment=(
            None
            if finished_turn is None and ending is None
            else CampaignChildAssignment(
                identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}-assignment",
                pull_request=52,
                observed_pull_request=None,
                finished_turn=finished_turn,
                ending=ending,
                is_in_fault=False,
            )
        ),
    )


# The children of the idle campaign's parent: one closed, whose assignment
# completed, one whose assignment is working, one whose request waits for an
# agent slot, and one that nothing has asked to be implemented.
CAMPAIGN_CHILDREN = [
    _compose_campaign_child(
        issue=63,
        state=IssueState.CLOSED,
        is_settled=True,
        finished_turn=2,
        ending=AgentWorkEndReason.COMPLETED,
    ),
    _compose_campaign_child(
        issue=64, state=IssueState.OPEN, is_settled=False, finished_turn=1
    ),
    _compose_campaign_child(issue=65, state=IssueState.OPEN, is_settled=False),
    _compose_campaign_child(issue=66, state=IssueState.OPEN, is_settled=True),
]


def _fabricate_campaign_children(*, state: StateDirectory) -> list[RequestRow]:
    """Write the assignments of the idle campaign's children, and return their rows.

    The rows are those of the working assignment and of the waiting request.
    """
    write_assignment_with_rounds(
        state=state,
        issue=63,
        records=[
            compose_ended_round(minute=1),
            compose_ended_round(minute=2, number=2),
        ],
        round_inputs={2: MERGED_INPUT},
    )
    current = compose_running_round(minute=40, number=2)
    write_feed(
        directory=write_assignment_with_rounds(
            state=state, issue=64, records=[compose_ended_round(minute=1), current]
        ),
        number=2,
        lines=[compose_feed_line(record=current, text="[Bash] pytest -q")],
    )
    return [
        _compose_assignment_row(
            issue=64, ended_round=1, started_round=StartedRound(number=2)
        ),
        compose_request_row(issue=65, finding=UNCLAIMED),
    ]


def fabricate_campaigns(*, state: StateDirectory) -> list[RequestRow]:
    """Write an idle campaign and an ended one, and return their requests' rows.

    The idle campaign's row holds its children, whose assignments and request
    the rows also hold. The rows also hold a labelled parent whose campaign has
    not started, and one queued behind open blockers, one of them in another
    repository.
    """
    for issue in (60, 61):
        directory = write_campaign(state=state, issue=issue)
        record = compose_ended_round(minute=1)
        write_round(
            directory=directory,
            number=1,
            record=record,
            round_input=CampaignRoundInput(
                issue=issue,
                children=[],
                notifications=[],
                comments=[],
                cursor=None,
                revision="abc123",
                assignment_routes=[],
            ),
        )
        write_feed(
            directory=directory,
            number=1,
            lines=[
                compose_feed_line(
                    record=record, text="I acknowledged the plan on the parent."
                )
            ],
        )
    write_ending(
        directory=state.work / compose_campaign_identifier(issue=61),
        reason=AgentWorkEndReason.ISSUE_CLOSED,
        at=PINNED + timedelta(minutes=30),
    )
    return [
        compose_campaign_row(
            finding=CampaignFinding(new_comments=0, changed_children=0), ended_round=1
        ).model_copy(update={"children": CAMPAIGN_CHILDREN}),
        compose_request_row(
            issue=62,
            kind=AgentWorkKind.CAMPAIGN,
            finding=CampaignFinding(new_comments=0, changed_children=0),
        ),
        compose_request_row(
            issue=67,
            kind=AgentWorkKind.CAMPAIGN,
            finding=BlockingIssuesFinding(
                blocking_issues=[
                    IssueReference(number=62),
                    IssueReference(number=1016, repository="alimanfoo/dream"),
                ]
            ),
        ),
        *_fabricate_campaign_children(state=state),
    ]


# What an assignment round woken by one post from the user was given.
ONE_POST_INPUT = AssignmentRoundInput(
    pull_request_state=PullRequestState.OPEN,
    pull_request_head=HEAD,
    signals=[],
    user_posts=[IssueComment.model_validate(compose_comment())],
)

# What an assignment round given the input of one that did not finish was given,
# when that input held no posts.
CARRY_ON_INPUT = AssignmentRoundInput(
    pull_request_state=PullRequestState.OPEN,
    pull_request_head=HEAD,
    signals=[],
    user_posts=[],
)


def write_assignment_with_rounds(
    *,
    state,
    issue: int,
    records: Sequence[AgentRoundRecord],
    round_inputs: Mapping[int, AssignmentRoundInput] = MappingProxyType({}),
):
    """Write an assignment for the issue, with these rounds and their inputs."""
    directory = write_assignment(
        state=state,
        identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}-assignment",
        issue=issue,
        harness_session_identifier=(HARNESS_SESSION_IDENTIFIER if records else None),
    )
    for number, record in enumerate(records, start=1):
        write_round(
            directory=directory,
            number=number,
            record=record,
            round_input=round_inputs.get(number),
        )
    return directory


def compose_ended_round(
    *,
    minute: int = 0,
    number: int = 1,
    status: int = 0,
):
    """Return a round that started that minute and ran for four minutes."""
    started = PINNED + timedelta(minutes=minute)
    return AgentRoundRecord(
        number=number,
        started=started,
        pid=1,
        ending=_compose_agent_round_ending(
            at=started + timedelta(minutes=4), status=status
        ),
    )


def compose_running_round(
    *,
    minute: int = 0,
    number: int = 1,
):
    """Return a round that started that minute and is still running."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
    )


def compose_feed_line(
    *,
    record: AgentRoundRecord,
    text: str,
    minutes: int = 1,
) -> FeedLine:
    """Return a line that the round wrote that many minutes after it started."""
    return FeedLine(at=record.started + timedelta(minutes=minutes), text=text)


def write_running_daemon(*, state, max_agents: int = 1):
    """Record the instance and hold the lock as its running daemon."""
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_daemon_run(state=state, pid=DAEMON_PID, max_agents=max_agents)
    hold_daemon_lock_for_test(path=state.lock)


def fabricate_nothing(*, state):
    """Write a state directory that a daemon has only bootstrapped."""
    state.bootstrap()
    write_daemon_run(state=state, pid=DAEMON_PID)


def fabricate_everything(
    *,
    state,
    other_rows: Sequence[RequestRow] = (),
    latest_output: str = "[Bash] pytest",
):
    """Write a running daemon with varied issue and assignment statuses."""
    write_running_daemon(state=state, max_agents=2)
    current = compose_running_round(minute=30, number=2)
    directory = write_assignment_with_rounds(
        state=state,
        issue=13,
        records=[compose_ended_round(minute=1), current],
        round_inputs={2: ONE_POST_INPUT},
    )
    write_feed(directory=directory, number=1, lines=SAID)
    write_feed(
        directory=directory,
        number=2,
        lines=[compose_feed_line(record=current, text=latest_output)],
    )
    pushed = compose_ended_round(minute=115)
    write_feed(
        directory=write_assignment_with_rounds(state=state, issue=20, records=[pushed]),
        number=1,
        lines=[compose_feed_line(record=pushed, text="[Bash] git push")],
    )
    write_assignment_with_rounds(
        state=state, issue=31, records=[compose_ended_round(minute=1)]
    )
    write_assignment_with_rounds(
        state=state, issue=35, records=[compose_ended_round(minute=1, status=2)]
    )
    write_assignment_with_rounds(
        state=state, issue=40, records=[compose_ended_round(minute=1)]
    )
    capped = compose_ended_round(minute=2, number=2, status=2)
    faulted_directory = write_assignment_with_rounds(
        state=state,
        issue=9,
        records=[compose_ended_round(minute=1, status=1), capped],
        round_inputs={2: CARRY_ON_INPUT},
    )
    write_feed(
        directory=faulted_directory,
        number=2,
        lines=[
            compose_feed_line(record=capped, text="[failed] You hit your spend cap.")
        ],
    )
    write_assignment_with_rounds(
        state=state,
        issue=12,
        records=[
            compose_ended_round(minute=1),
            compose_ended_round(minute=2, number=2),
        ],
        round_inputs={2: MERGED_INPUT},
    )
    write_assignment_with_rounds(state=state, issue=44, records=[])
    write_assignment_with_rounds(
        state=state, issue=70, records=[compose_ended_round(minute=1)]
    )
    cancel_assignment(
        assignment=read_agent_work_at_issue(state=state, issue=70)[0],
        at=PINNED + timedelta(minutes=10),
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            finished=PINNED + timedelta(hours=1, minutes=58, seconds=45),
            rows=[
                compose_request_row(issue=50, finding=UNCLAIMED),
                compose_request_row(issue=51, finding=UNCLAIMED),
                compose_request_row(
                    issue=52,
                    finding=StartTimeFinding(
                        linked_pull_requests=[],
                        blocking_issues=[IssueReference(number=50)],
                    ),
                ),
                compose_request_row(
                    issue=53, label="dream:less", finding=DOUBLE_LABELLED
                ),
                compose_request_row(issue=53, finding=DOUBLE_LABELLED),
                compose_request_row(
                    issue=55,
                    finding=StartTimeFinding(
                        linked_pull_requests=[61],
                        blocking_issues=[
                            IssueReference(number=50),
                            IssueReference(number=1016, repository="alimanfoo/dream"),
                        ],
                    ),
                ),
                _compose_assignment_row(
                    issue=13, ended_round=1, started_round=StartedRound(number=2)
                ),
                _compose_assignment_row(
                    issue=31,
                    ended_round=1,
                    finding=_compose_draft_pull_request(new_posts=1),
                ),
                _compose_assignment_row(
                    issue=20, finding=_compose_draft_pull_request()
                ),
                _compose_assignment_row(
                    issue=35,
                    ended_round=1,
                    finding=_compose_draft_pull_request().model_copy(
                        update={
                            "merge_state": PullRequestMergeState.DIRTY,
                            "check_result": CheckResult.FAILING,
                        }
                    ),
                ),
                _compose_assignment_row(issue=9, ended_round=2),
                _compose_assignment_row(issue=44),
                *other_rows,
            ],
        ),
    )


def fabricate_status_everything(*, state):
    """Write the combined report, including output wider than its console."""
    fabricate_everything(
        state=state,
        latest_output="The agent is explaining a long change that would otherwise "
        "wrap onto another line and move every assignment below it.",
    )


def fabricate_a_dead_daemon(*, state):
    """Write the same assignments with their former daemon gone."""
    fabricate_everything(state=state)
    release_daemon_lock(path=state.lock)


def fabricate_the_cap(*, state):
    """Write a daemon at its cap whose latest tick also failed to list issues."""
    write_running_daemon(state=state)
    current = compose_running_round(minute=30)
    directory = write_assignment_with_rounds(state=state, issue=13, records=[current])
    write_feed(
        directory=directory,
        number=1,
        lines=[compose_feed_line(record=current, text="[Bash] pytest")],
    )
    write_assignment_with_rounds(
        state=state, issue=20, records=[compose_ended_round(minute=1)]
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            finished=PINNED + timedelta(hours=1, minutes=58),
            failures=[
                "could not list issues: gh issue list: "
                'Post "https://api.github.com/graphql": unexpected EOF',
            ],
            rows=[
                _compose_assignment_row(
                    issue=20,
                    ended_round=1,
                    finding=_compose_draft_pull_request(new_posts=1),
                )
            ],
        ),
    )


def fabricate_repeat_assignments(*, state):
    """Write three assignments at one issue to show repeat assignment dispatches."""
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_daemon_run(state=state, pid=DAEMON_PID)
    for stamp, rounds, round_inputs in (
        (
            "20260817-090000",
            (compose_ended_round(minute=1), compose_ended_round(minute=2, number=2)),
            (None, MERGED_INPUT),
        ),
        (
            "20260818-090000",
            (compose_ended_round(minute=1), compose_ended_round(minute=2, number=2)),
            (None, MERGED_INPUT),
        ),
        ("20260819-184158", (compose_ended_round(minute=1),), (None,)),
    ):
        directory = write_assignment(
            state=state, identifier=f"GH13-{stamp}-assignment", issue=13
        )
        for number, (record, round_input) in enumerate(
            zip(rounds, round_inputs, strict=True), start=1
        ):
            write_round(
                directory=directory,
                number=number,
                record=record,
                round_input=round_input,
            )
        write_feed(
            directory=directory,
            number=len(rounds),
            lines=[compose_feed_line(record=rounds[-1], text="[Bash] git push")],
        )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            finished=PINNED + timedelta(hours=1, minutes=58),
            rows=[
                _compose_assignment_row(
                    issue=13, ended_round=1, finding=_compose_draft_pull_request()
                )
            ],
        ),
    )


def fabricate_a_silent_round(*, state):
    """Write a daemon running a round that has yet to write its own line."""
    write_running_daemon(state=state)
    pushed = compose_ended_round(minute=1)
    directory = write_assignment_with_rounds(
        state=state,
        issue=13,
        records=[pushed, compose_running_round(minute=30, number=2)],
        round_inputs={2: ONE_POST_INPUT},
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[compose_feed_line(record=pushed, text="[Bash] git push")],
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            finished=PINNED + timedelta(hours=1, minutes=58),
            rows=[
                _compose_assignment_row(
                    issue=13, ended_round=1, started_round=StartedRound(number=2)
                )
            ],
        ),
    )


def fabricate_titles_and_pull_request_states(*, state):
    """Write assignments and issues carrying every web reporting fact."""
    write_running_daemon(state=state)
    pull_request_rows = []
    for issue, title, pull_request_state, is_draft, merge_state, check_result in (
        (
            10,
            "Draft assignment",
            PullRequestState.OPEN,
            True,
            PullRequestMergeState.BLOCKED,
            CheckResult.NONE,
        ),
        (
            11,
            "Ready assignment",
            PullRequestState.OPEN,
            False,
            PullRequestMergeState.CLEAN,
            CheckResult.PASSING,
        ),
        (
            12,
            "Merged assignment",
            PullRequestState.MERGED,
            False,
            PullRequestMergeState.UNKNOWN,
            CheckResult.PASSING,
        ),
        (
            13,
            "Closed assignment",
            PullRequestState.CLOSED,
            False,
            PullRequestMergeState.CLEAN,
            CheckResult.PASSING,
        ),
        (
            15,
            "Behind assignment",
            PullRequestState.OPEN,
            False,
            PullRequestMergeState.BEHIND,
            CheckResult.RUNNING,
        ),
        (
            16,
            "Red assignment",
            PullRequestState.OPEN,
            False,
            PullRequestMergeState.BLOCKED,
            CheckResult.FAILING,
        ),
    ):
        write_assignment(
            state=state,
            identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}-assignment",
            issue=issue,
            title=title,
            harness_session_identifier=None,
        )
        pull_request_rows.append(
            _compose_assignment_row(
                issue=issue,
                finding=PullRequestFinding(
                    number=52,
                    state=pull_request_state,
                    is_draft=is_draft,
                    merge_state=merge_state,
                    head=HEAD,
                    check_result=check_result,
                    has_running_checks=False,
                    new_posts=0,
                    new_pull_request_signals=[],
                    is_check_failure_withheld=check_result is CheckResult.FAILING,
                    is_wrap_up_due=pull_request_state is not PullRequestState.OPEN,
                ),
            )
        )
    write_assignment(
        state=state,
        identifier=f"GH14-{ASSIGNMENT_TIMESTAMP}-assignment",
        issue=14,
        harness_session_identifier=None,
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            finished=PINNED + timedelta(hours=1, minutes=58),
            rows=[
                compose_request_row(issue=20, finding=UNCLAIMED).model_copy(
                    update={"title": "Available issue"}
                ),
                compose_request_row(
                    issue=21,
                    finding=StartTimeFinding(
                        linked_pull_requests=[],
                        blocking_issues=[IssueReference(number=20)],
                    ),
                ).model_copy(update={"title": "Blocked issue"}),
                *pull_request_rows,
                _compose_assignment_row(issue=14),
            ],
        ),
    )


def fabricate_campaign_report(*, state):
    """Write a running daemon with an idle campaign, an ended one and a request."""
    write_running_daemon(state=state)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            finished=PINNED + timedelta(hours=1, minutes=58),
            rows=fabricate_campaigns(state=state),
        ),
    )


STATUS_REPORTS = {
    "nothing": fabricate_nothing,
    "everything": fabricate_status_everything,
    "dead-daemon": fabricate_a_dead_daemon,
    "at-cap": fabricate_the_cap,
    "silent-round": fabricate_a_silent_round,
    "repeat-assignments": fabricate_repeat_assignments,
    "campaigns": fabricate_campaign_report,
}
