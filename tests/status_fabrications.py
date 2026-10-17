"""Fabricate local status-report states shared by presentation tests."""

from collections.abc import Mapping, Sequence
from datetime import timedelta
from types import MappingProxyType

from clocks import PINNED
from conftest import ASSIGNMENT_LABEL, DAEMON_PID, REPOSITORY, comment
from records import (
    MERGED_INPUT,
    compose_conversation_identifier,
    hold_daemon_lock_for_test,
    release_daemon_lock,
    write_assignment,
    write_conversation,
    write_daemon_run,
    write_feed,
    write_final_output,
    write_round,
    write_tick,
)
from rows import UNCLAIMED, request_row

from dreamcatcher.agent_assignments import (
    AssignmentRoundInput,
    PullRequestObservation,
    cancel_assignment,
)
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import read_agent_work_at_issue
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.github import ConversationComment, PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind, HarnessSessionIdentifier
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    InitialConversationIssue,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    PullRequestFinding,
    RequestFinding,
    RequestRow,
    SchedulerRecord,
    StartedRound,
    StartTimeFinding,
    UnlistedIssueFinding,
)
from dreamcatcher.state import StateDirectory

LOOKED_AT = PINNED + timedelta(hours=2)
ASSIGNMENT_TIMESTAMP = "20260819-184158"
HARNESS_SESSION_IDENTIFIER = "abc-123"


def _assignment_row(
    *,
    issue: int,
    finding: RequestFinding | None = None,
    started_round: StartedRound | None = None,
) -> RequestRow:
    """Return the row of the assignment that the fabrications write at the issue."""
    return request_row(
        issue=issue,
        agent_work=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}-assignment",
        finding=finding,
        started_round=started_round,
    )


def _draft_pull_request(*, new_posts: int = 0) -> PullRequestFinding:
    """Return what the tick reads of the draft that the fabrications open."""
    return PullRequestFinding(
        number=52,
        state=PullRequestState.OPEN,
        is_draft=True,
        new_posts=new_posts,
        is_final_turn_due=False,
    )


def conversation_row(*, finding: RequestFinding, issue: int = 8) -> RequestRow:
    """Return the row of the conversation that the tests write at the issue."""
    return request_row(
        issue=issue,
        kind=AgentWorkKind.CONVERSATION,
        agent_work=compose_conversation_identifier(issue=issue),
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
    FeedLine(at=PINNED + timedelta(minutes=3), text="  [Bash] ls"),
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
    is_listed: bool = False,
    harness_session_identifier: HarnessSessionIdentifier
    | None = "conversation-session",
) -> None:
    """Write one initial conversation exchange."""
    directory = write_conversation(
        state=state,
        issue=8,
        harness_session_identifier=harness_session_identifier,
    )
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                conversation_row(
                    finding=(
                        IssueCommentsFinding(new_comments=0)
                        if is_listed
                        else UnlistedIssueFinding()
                    )
                )
            ],
        ),
    )
    if not has_round:
        return
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=status
            ),
        ),
    )
    write_json(
        document=ConversationRoundInput(
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
        path=(directory / "rounds" / "1" / "round-input.json"),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="I found the answer.")],
    )
    write_final_output(directory=directory, number=1, text="The answer.")


# What an assignment round woken by one post from the user was given.
ONE_POST_INPUT = AssignmentRoundInput(
    pull_request_state=PullRequestState.OPEN,
    user_posts=[ConversationComment.model_validate(comment())],
)

# What an assignment round given the input of one that did not finish was given,
# when that input held no posts.
CARRY_ON_INPUT = AssignmentRoundInput(
    pull_request_state=PullRequestState.OPEN, user_posts=[]
)


def written(
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


def ended(
    *,
    minute: int,
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


def running(
    *,
    minute: int,
    number: int = 1,
):
    """Return a round that started that minute and is still running."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
    )


def holding(*, state):
    """Record the instance and hold the lock as its running daemon."""
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_daemon_run(state=state, pid=DAEMON_PID)
    hold_daemon_lock_for_test(path=state.lock)


def fabricate_nothing(*, state):
    """Write a state directory that a daemon has only bootstrapped."""
    state.bootstrap()
    write_daemon_run(state=state, pid=DAEMON_PID)


def fabricate_everything(
    *,
    state,
    conversation_rows: Sequence[RequestRow] = (),
):
    """Write a running daemon with varied issue and assignment statuses."""
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[ended(minute=1), running(minute=30, number=2)],
        round_inputs={2: ONE_POST_INPUT},
    )
    write_feed(directory=directory, number=1, lines=SAID)
    write_feed(
        directory=directory,
        number=2,
        lines=[FeedLine(at=PINNED + timedelta(minutes=31), text="[Bash] pytest")],
    )
    write_feed(
        directory=written(state=state, issue=20, records=[ended(minute=1)]),
        number=1,
        lines=[FeedLine(at=PINNED, text="[Bash] git push")],
    )
    written(state=state, issue=31, records=[ended(minute=1)])
    written(state=state, issue=35, records=[ended(minute=1, status=2)])
    written(state=state, issue=40, records=[ended(minute=1)])
    faulted_directory = written(
        state=state,
        issue=9,
        records=[ended(minute=1, status=1), ended(minute=2, number=2, status=2)],
        round_inputs={2: CARRY_ON_INPUT},
    )
    write_feed(
        directory=faulted_directory,
        number=2,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=3),
                text="[failed] You hit your spend cap.",
            )
        ],
    )
    written(
        state=state,
        issue=12,
        records=[ended(minute=1), ended(minute=2, number=2)],
        round_inputs={2: MERGED_INPUT},
    )
    written(state=state, issue=44, records=[])
    written(state=state, issue=70, records=[ended(minute=1)])
    cancel_assignment(
        assignment=read_agent_work_at_issue(
            state=state, issue=70, kind=AgentWorkKind.ASSIGNMENT
        )[0],
        at=PINNED + timedelta(minutes=10),
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            rows=[
                request_row(issue=50, finding=UNCLAIMED),
                request_row(issue=51, finding=UNCLAIMED),
                request_row(
                    issue=52,
                    finding=StartTimeFinding(
                        linked_pull_requests=[], blocking_issues=[50]
                    ),
                ),
                request_row(issue=53, label="dream:less", finding=DOUBLE_LABELLED),
                request_row(issue=53, finding=DOUBLE_LABELLED),
                request_row(
                    issue=55,
                    finding=StartTimeFinding(
                        linked_pull_requests=[61], blocking_issues=[50, 51]
                    ),
                ),
                _assignment_row(issue=13, started_round=StartedRound(number=2)),
                _assignment_row(issue=31, finding=_draft_pull_request(new_posts=1)),
                _assignment_row(issue=20, finding=_draft_pull_request()),
                _assignment_row(issue=35, finding=_draft_pull_request()),
                _assignment_row(issue=9),
                _assignment_row(issue=44),
                *conversation_rows,
            ],
        ),
    )


def fabricate_status_everything(*, state):
    """Write the combined report, including output wider than its console."""
    fabricate_everything(state=state)
    write_feed(
        directory=state.work / f"GH13-{ASSIGNMENT_TIMESTAMP}-assignment",
        number=2,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=31),
                text="The agent is explaining a long change that would otherwise "
                "wrap onto another line and move every assignment below it.",
            )
        ],
    )


def fabricate_a_dead_daemon(*, state):
    """Write the same assignments with their former daemon gone."""
    fabricate_everything(state=state)
    release_daemon_lock(path=state.lock)


def fabricate_the_cap(*, state):
    """Write a daemon at its cap whose latest tick also failed to list issues."""
    holding(state=state)
    directory = written(state=state, issue=13, records=[running(minute=30)])
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED + timedelta(minutes=31), text="[Bash] pytest")],
    )
    written(state=state, issue=20, records=[ended(minute=1)])
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            failures=["could not list issues for dream:less: could not connect"],
            rows=[_assignment_row(issue=20, finding=_draft_pull_request(new_posts=1))],
        ),
    )


def fabricate_repeat_assignments(*, state):
    """Write three assignments at one issue to show repeat assignment dispatches."""
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_daemon_run(state=state, pid=DAEMON_PID)
    for stamp, rounds, round_inputs in (
        (
            "20260817-090000",
            (ended(minute=1), ended(minute=2, number=2)),
            (None, MERGED_INPUT),
        ),
        (
            "20260818-090000",
            (ended(minute=1), ended(minute=2, number=2)),
            (None, MERGED_INPUT),
        ),
        ("20260819-184158", (ended(minute=1),), (None,)),
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
            lines=[
                FeedLine(
                    at=PINNED + timedelta(minutes=len(rounds) + 1),
                    text="[Bash] git push",
                )
            ],
        )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            rows=[_assignment_row(issue=13, finding=_draft_pull_request())],
        ),
    )


def fabricate_a_silent_round(*, state):
    """Write a daemon running a round that has yet to write its own line."""
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[ended(minute=1), running(minute=30, number=2)],
        round_inputs={2: ONE_POST_INPUT},
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="[Bash] git push")],
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            rows=[_assignment_row(issue=13, started_round=StartedRound(number=2))],
        ),
    )


def fabricate_titles_and_pull_request_states(*, state):
    """Write assignments and issues carrying every web reporting fact."""
    holding(state=state)
    for issue, title, pull_request_state, is_draft in (
        (10, "Draft assignment", PullRequestState.OPEN, True),
        (11, "Ready assignment", PullRequestState.OPEN, False),
        (12, "Merged assignment", PullRequestState.MERGED, False),
        (13, "Closed assignment", PullRequestState.CLOSED, False),
    ):
        write_assignment(
            state=state,
            identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}-assignment",
            issue=issue,
            title=title,
            pull_request_observation=PullRequestObservation(
                number=52,
                state=pull_request_state,
                is_draft=is_draft,
                observed_at=PINNED,
            ),
            harness_session_identifier=None,
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
            rows=[
                request_row(issue=20, title="Available issue", finding=UNCLAIMED),
                request_row(
                    issue=21,
                    title="Blocked issue",
                    finding=StartTimeFinding(
                        linked_pull_requests=[], blocking_issues=[20]
                    ),
                ),
                *(_assignment_row(issue=issue) for issue in (10, 11, 12, 13, 14)),
            ],
        ),
    )


STATUS_REPORTS = {
    "nothing": fabricate_nothing,
    "everything": fabricate_status_everything,
    "dead-daemon": fabricate_a_dead_daemon,
    "at-cap": fabricate_the_cap,
    "silent-round": fabricate_a_silent_round,
    "repeat-assignments": fabricate_repeat_assignments,
}
