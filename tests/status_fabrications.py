"""Fabricate local status-report states shared by presentation tests."""

from collections.abc import Sequence
from datetime import timedelta

from clocks import PINNED
from conftest import DAEMON_PID, DISPATCH_LABEL, REPOSITORY, configure
from observations import observed_conversation, observed_issue
from records import (
    AssignmentReporting,
    write_agent_assignment,
    write_daemon_lock,
    write_daemon_run,
    write_feed,
    write_final_output,
    write_issue_conversation,
    write_round,
    write_tick,
)

from dreamcatcher.agent_assignments import PullRequestObservation
from dreamcatcher.agent_rounds import (
    AgentAssignmentRoundPurpose,
    AgentRoundRecord,
    IssueConversationRoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.github import PullRequestState
from dreamcatcher.issue_conversations import IssueConversationInput
from dreamcatcher.scheduler import (
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    IssueConversationObservation,
    IssueFactValue,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory

LOOKED_AT = PINNED + timedelta(hours=2)
ASSIGNMENT_TIMESTAMP = "20260819-184158"
HARNESS_SESSION_IDENTIFIER = "abc-123"

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

DOUBLE_LABELLED = "carries more than one dispatch label: dream:less, dream:smith"


def fabricate_conversation(
    *,
    state: StateDirectory,
    has_round: bool = True,
    status: int = 0,
    is_eligible: bool = False,
) -> None:
    """Write one initial conversation exchange."""
    directory = write_issue_conversation(state=state, issue=8)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            conversation_observations=[observed_conversation()] if is_eligible else [],
        ),
    )
    if not has_round:
        return
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            purpose=IssueConversationRoundPurpose.DISCUSS,
            started=PINNED,
            pid=1,
            ending=compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=status
            ),
        ),
    )
    write_json(
        document=IssueConversationInput(
            issue=8,
            title="Issue 8",
            body="Explain it.",
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
        path=(directory / "rounds" / "1" / "inbox.json"),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="I found the answer.")],
    )
    write_final_output(directory=directory, number=1, text="The answer.")


def written(*, state, issue: int, records: Sequence[AgentRoundRecord]):
    """Write an assignment for the issue, with these rounds behind it."""
    directory = write_agent_assignment(
        state=state,
        identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}",
        issue=issue,
        harness_session_identifier=(HARNESS_SESSION_IDENTIFIER if records else None),
    )
    for number, record in enumerate(records, start=1):
        write_round(directory=directory, number=number, record=record)
    return directory


def ended(
    *,
    minute: int,
    number: int = 1,
    status: int = 0,
    purpose: AgentAssignmentRoundPurpose = AgentAssignmentRoundPurpose.IMPLEMENT,
):
    """Return a round that started that minute and ran for four minutes."""
    started = PINNED + timedelta(minutes=minute)
    return AgentRoundRecord(
        number=number,
        started=started,
        pid=1,
        purpose=purpose,
        ending=compose_agent_round_ending(
            at=started + timedelta(minutes=4), status=status
        ),
    )


def running(
    *,
    minute: int,
    number: int = 1,
    purpose: AgentAssignmentRoundPurpose = AgentAssignmentRoundPurpose.IMPLEMENT,
    is_recovery: bool = False,
):
    """Return a round that started that minute and is still running."""
    return AgentRoundRecord(
        number=number,
        started=PINNED + timedelta(minutes=minute),
        pid=1,
        purpose=purpose,
        is_recovery=is_recovery,
    )


def holding(*, state):
    """Configure the instance and write the lock that its daemon holds."""
    configure(root=state.root)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_daemon_run(state=state, pid=DAEMON_PID)
    write_daemon_lock(path=state.lock, pid=DAEMON_PID, process_started_at=PINNED)


def fabricate_nothing(*, state):
    """Write a state directory that a daemon has only bootstrapped."""
    configure(root=state.root)
    state.bootstrap()
    write_daemon_run(state=state, pid=DAEMON_PID)


def fabricate_everything(
    *,
    state,
    conversation_observations: Sequence[IssueConversationObservation] = (),
):
    """Write a running daemon with varied issue and assignment statuses."""
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[
            ended(minute=1),
            running(
                minute=30,
                number=2,
                purpose=AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK,
                is_recovery=True,
            ),
        ],
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
    written(
        state=state,
        issue=9,
        records=[ended(minute=1, status=1), ended(minute=2, number=2, status=2)],
    )
    written(
        state=state,
        issue=12,
        records=[
            ended(minute=1),
            ended(minute=2, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP),
        ],
    )
    written(state=state, issue=44, records=[])
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            launched_agent_work_identifiers=[f"GH13-{ASSIGNMENT_TIMESTAMP}"],
            issue_observations=[
                observed_issue(issue=50),
                observed_issue(issue=51),
                observed_issue(
                    issue=52,
                    values={"blocked": IssueFactValue.TRUE},
                    evidence={"blocked": "blocked by GH50"},
                ),
                observed_issue(
                    issue=53,
                    dispatch_labels=(DISPATCH_LABEL, "dream:less"),
                    values={"routing_conflict": IssueFactValue.TRUE},
                    evidence={"routing_conflict": DOUBLE_LABELLED},
                ),
            ],
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=f"GH31-{ASSIGNMENT_TIMESTAMP}",
                    issue=31,
                    reason="1 new post to answer",
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH20-{ASSIGNMENT_TIMESTAMP}",
                    issue=20,
                    reason="no round required",
                    is_round_required=False,
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH35-{ASSIGNMENT_TIMESTAMP}",
                    issue=35,
                    reason="the last round failed (exit 2)",
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH9-{ASSIGNMENT_TIMESTAMP}",
                    issue=9,
                    reason="two consecutive rounds failed",
                ),
                AgentAssignmentObservation(
                    assignment_identifier=f"GH44-{ASSIGNMENT_TIMESTAMP}",
                    issue=44,
                    reason=NO_ROUND_HAS_RUN,
                ),
            ],
            conversation_observations=list(conversation_observations),
        ),
    )


def fabricate_status_everything(*, state):
    """Write the combined report, including output wider than its console."""
    fabricate_everything(state=state)
    write_feed(
        directory=state.assignments / f"GH13-{ASSIGNMENT_TIMESTAMP}",
        number=2,
        lines=[
            FeedLine(
                at=PINNED + timedelta(minutes=31),
                text="The agent is explaining a long change that would otherwise "
                "wrap onto another line and move every assignment below it.",
            )
        ],
    )


def fabricate_a_failed_setup(*, state):
    """Write an assignment, a failed setup, and available work."""
    holding(state=state)
    written(state=state, issue=13, records=[])
    failure = "assignment setup failed"
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            issue_observations=[
                observed_issue(
                    issue=20,
                    values={"claimed_elsewhere": IssueFactValue.UNKNOWN},
                    evidence={"claimed_elsewhere": failure},
                ).model_copy(update={"setup_failure": failure}),
                observed_issue(issue=21),
            ],
        ),
    )


def fabricate_a_dead_daemon(*, state):
    """Write the same assignments with their former daemon gone."""
    fabricate_everything(state=state)
    state.lock.unlink()


def fabricate_the_cap(*, state):
    """Write a daemon at its cap, which holds every assignment."""
    holding(state=state)
    directory = written(state=state, issue=13, records=[running(minute=30)])
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED + timedelta(minutes=31), text="[Bash] pytest")],
    )
    written(state=state, issue=20, records=[ended(minute=1)])
    hold = "at cap: 1 of 1 agents running"
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            hold=hold,
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=f"GH20-{ASSIGNMENT_TIMESTAMP}",
                    issue=20,
                    reason=hold,
                )
            ],
        ),
    )


def fabricate_repeat_assignments(*, state):
    """Write three assignments at one issue to show a repeat dispatch."""
    configure(root=state.root)
    write_text(text=f"{REPOSITORY}\n", path=state.repository)
    write_daemon_run(state=state, pid=DAEMON_PID)
    for stamp, rounds in (
        (
            "20260817-090000",
            (
                ended(minute=1),
                ended(minute=2, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP),
            ),
        ),
        (
            "20260818-090000",
            (
                ended(minute=1),
                ended(minute=2, number=2, purpose=AgentAssignmentRoundPurpose.WRAP_UP),
            ),
        ),
        ("20260819-184158", (ended(minute=1),)),
    ):
        directory = write_agent_assignment(
            state=state, identifier=f"GH13-{stamp}", issue=13
        )
        for number, record in enumerate(rounds, start=1):
            write_round(directory=directory, number=number, record=record)
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
            assignment_observations=[
                AgentAssignmentObservation(
                    assignment_identifier=f"GH13-{ASSIGNMENT_TIMESTAMP}",
                    issue=13,
                    reason="no round required",
                    is_round_required=False,
                )
            ],
        ),
    )


def fabricate_a_silent_round(*, state):
    """Write a daemon running a round that has yet to write its own line."""
    holding(state=state)
    directory = written(
        state=state,
        issue=13,
        records=[
            ended(minute=1),
            running(
                minute=30,
                number=2,
                purpose=AgentAssignmentRoundPurpose.ADDRESS_FEEDBACK,
            ),
        ],
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
            launched_agent_work_identifiers=[f"GH13-{ASSIGNMENT_TIMESTAMP}"],
        ),
    )


def fabricate_titles_and_pull_request_states(*, state):
    """Write assignments and issues carrying every web reporting fact."""
    holding(state=state)
    assignment_observations = []
    for issue, title, pull_request_state, is_draft in (
        (10, "Draft assignment", PullRequestState.OPEN, True),
        (11, "Ready assignment", PullRequestState.OPEN, False),
        (12, "Merged assignment", PullRequestState.MERGED, False),
        (13, "Closed assignment", PullRequestState.CLOSED, False),
    ):
        write_agent_assignment(
            state=state,
            identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}",
            issue=issue,
            reporting=AssignmentReporting(
                title=title,
                pull_request_observation=PullRequestObservation(
                    state=pull_request_state,
                    is_draft=is_draft,
                    observed_at=PINNED,
                ),
            ),
            harness_session_identifier=None,
        )
        assignment_observations.append(
            AgentAssignmentObservation(
                assignment_identifier=f"GH{issue}-{ASSIGNMENT_TIMESTAMP}",
                issue=issue,
                reason=NO_ROUND_HAS_RUN,
            )
        )
    write_agent_assignment(
        state=state,
        identifier=f"GH14-{ASSIGNMENT_TIMESTAMP}",
        issue=14,
        harness_session_identifier=None,
    )
    assignment_observations.append(
        AgentAssignmentObservation(
            assignment_identifier=f"GH14-{ASSIGNMENT_TIMESTAMP}",
            issue=14,
            reason=NO_ROUND_HAS_RUN,
        )
    )
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(hours=1, minutes=58),
            issue_observations=[
                observed_issue(issue=20).model_copy(
                    update={"title": "Available issue"}
                ),
                observed_issue(
                    issue=21,
                    values={"blocked": IssueFactValue.TRUE},
                    evidence={"blocked": "blocked by GH20"},
                ).model_copy(update={"title": "Blocked issue"}),
                observed_issue(
                    issue=22,
                    values={"claimed_elsewhere": IssueFactValue.UNKNOWN},
                    evidence={"claimed_elsewhere": "assignment setup failed"},
                ).model_copy(
                    update={
                        "title": "Failed setup issue",
                        "setup_failure": "assignment setup failed",
                    }
                ),
            ],
            assignment_observations=assignment_observations,
        ),
    )


STATUS_REPORTS = {
    "nothing": fabricate_nothing,
    "everything": fabricate_status_everything,
    "failed-setup": fabricate_a_failed_setup,
    "dead-daemon": fabricate_a_dead_daemon,
    "at-cap": fabricate_the_cap,
    "silent-round": fabricate_a_silent_round,
    "repeat-assignments": fabricate_repeat_assignments,
}
