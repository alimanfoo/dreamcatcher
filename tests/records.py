"""Write the records a state directory holds, as the daemon would have left them.

A test that starts from a state directory already holding assignments and rounds
writes them here, rather than creating them through the scheduler. So it reaches
the state it is about without a GitHub, an origin to cut from, or a harness to run.
"""

from collections.abc import Sequence
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

from clocks import PINNED

from dreamcatcher import (
    agent_assignments,
    agent_rounds,
    agent_work,
    issue_conversations,
)
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DEFAULT_INTERVAL_SECONDS
from dreamcatcher.daemon_runs import DaemonRunRecord, RecordedRoute
from dreamcatcher.documents import DreamcatcherDocument, write_json, write_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.github import PullRequestState
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.lock import hold_daemon_lock
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory

# The daemon locks that the running test holds, by path.
_HELD_DAEMON_LOCKS: dict[Path, ExitStack] = {}

# The routes a fabricated daemon run loaded, unless a test says: those of the
# configuration that conftest writes.
SMITH_ROUTES = (RecordedRoute(label="dream:smith", kind=AgentWorkKind.ASSIGNMENT),)

# The routes of a daemon run that loaded one conversation label and nothing else.
SCOUT_ROUTES = (RecordedRoute(label="dream:scout", kind=AgentWorkKind.CONVERSATION),)

# The head commit of the pull request that the tests ask gh about, unless a test
# moves it.
HEAD = "3aa91fcd8f64716f7c44d904d6891025bd606f1a"

# What a round that wraps a merged pull request up was given.
MERGED_INPUT = agent_assignments.AssignmentRoundInput(
    pull_request_state=PullRequestState.MERGED,
    pull_request_head=HEAD,
    signals=[],
    user_posts=[],
)

# The number of the pull request a fabricated assignment opened, unless a test says.
_PULL_REQUEST_52 = 52


def write_daemon_run(
    *,
    state: StateDirectory,
    pid: int,
    harness: AgentHarness = AgentHarness.CLAUDE,
    version: str = "3.0.0.beta1",
    max_agents: int = 1,
    routes: Sequence[RecordedRoute] = SMITH_ROUTES,
) -> None:
    """Write the facts fixed for one daemon run."""
    write_json(
        document=DaemonRunRecord(
            pid=pid,
            preferred_harness=harness,
            version=version,
            max_agents=max_agents,
            interval_seconds=DEFAULT_INTERVAL_SECONDS,
            routes=list(routes),
        ),
        path=state.daemon_run_record,
    )


def hold_daemon_lock_for_test(*, path: Path) -> None:
    """Hold the daemon lock, as a running daemon would, until the test ends."""
    held = ExitStack()
    held.enter_context(hold_daemon_lock(path=path))
    _HELD_DAEMON_LOCKS[path] = held


def release_daemon_lock(*, path: Path) -> None:
    """Release a lock that the test holds, as a daemon that dies would."""
    _HELD_DAEMON_LOCKS.pop(path).close()


def release_daemon_locks() -> None:
    """Release every lock that the test still holds."""
    while _HELD_DAEMON_LOCKS:
        _, held = _HELD_DAEMON_LOCKS.popitem()
        held.close()


def write_assignment(
    *,
    state: StateDirectory,
    identifier: str,
    issue: int,
    harness_session_identifier: str | None = "abc-123",
    title: str | None = None,
    pull_request: int | None = _PULL_REQUEST_52,
) -> Path:
    """Write an assignment's worktree and its records, and return its own directory.

    The title is `Issue <n>` unless the test gives one. An assignment given no
    pull request is one that no round has opened yet.
    """
    (state.worktrees / identifier).mkdir(parents=True)
    directory = state.work / identifier
    if pull_request is not None:
        write_json(
            document=agent_assignments._PullRequestRecord(number=pull_request),
            path=directory / agent_assignments._PULL_REQUEST_RECORD_NAME,
        )
    agent_work._record_agent_work(
        state=state,
        identifier=identifier,
        record=agent_work.AgentWorkRecord(
            issue=issue,
            title=f"Issue {issue}" if title is None else title,
            dispatch_label="dream:smith",
            kind=AgentWorkKind.ASSIGNMENT,
            harness=AgentHarness.CLAUDE,
            model="opus[1m]",
            effort="xhigh",
            instructions=f"/dream:smith GH{issue}",
        ),
    )
    _write_harness_session(directory=directory, identifier=harness_session_identifier)
    return directory


def compose_conversation_identifier(*, issue: int, at: datetime = PINNED) -> str:
    """Return the identifier of the conversation that the tests write at an issue."""
    return agent_work._compose_agent_work_identifier(
        issue=issue, kind=AgentWorkKind.CONVERSATION, at=at
    )


def find_conversation_directory(*, state: StateDirectory, issue: int) -> Path:
    """Return the directory of the conversation that the tests write at an issue."""
    return state.work / compose_conversation_identifier(issue=issue)


def write_conversation(
    *,
    state: StateDirectory,
    issue: int,
    harness: AgentHarness = AgentHarness.CLAUDE,
    harness_session_identifier: str | None = "conversation-session",
    at: datetime = PINNED,
    dispatch_label: str = "dream:conversation",
) -> Path:
    """Write a conversation worktree and record, and return its directory.

    The conversation is created at the pinned time unless the test gives
    another, so a test that writes a second one at the issue gives a later time.
    """
    identifier = compose_conversation_identifier(issue=issue, at=at)
    (state.worktrees / identifier).mkdir(parents=True)
    work = agent_work._record_agent_work(
        state=state,
        identifier=identifier,
        record=agent_work.AgentWorkRecord(
            issue=issue,
            title=f"Issue {issue}",
            dispatch_label=dispatch_label,
            kind=AgentWorkKind.CONVERSATION,
            harness=harness,
            model="opus[1m]",
            effort="xhigh",
            instructions=f"/dream:conversation GH{issue}",
        ),
    )
    _write_harness_session(
        directory=work.directory, identifier=harness_session_identifier
    )
    return work.directory


def compose_campaign_identifier(*, issue: int, at: datetime = PINNED) -> str:
    """Return the identifier of the campaign that the tests write at a parent."""
    return agent_work._compose_agent_work_identifier(
        issue=issue, kind=AgentWorkKind.CAMPAIGN, at=at
    )


def write_campaign(
    *,
    state: StateDirectory,
    issue: int,
    harness: AgentHarness = AgentHarness.CLAUDE,
    harness_session_identifier: str | None = "lead-session",
    dispatch_label: str = "dream:lead",
) -> Path:
    """Write a campaign record at the parent issue, and return its directory.

    Its worktree is left for its first round's preparation to add.
    """
    work = agent_work._record_agent_work(
        state=state,
        identifier=compose_campaign_identifier(issue=issue),
        record=agent_work.AgentWorkRecord(
            issue=issue,
            title=f"Parent {issue}",
            dispatch_label=dispatch_label,
            kind=AgentWorkKind.CAMPAIGN,
            harness=harness,
            model="opus[1m]",
            effort="xhigh",
            instructions=f"Acknowledge GH{issue} with a comment on it.",
        ),
    )
    _write_harness_session(
        directory=work.directory, identifier=harness_session_identifier
    )
    return work.directory


def _write_harness_session(*, directory: Path, identifier: str | None) -> None:
    """Write the harness session of the work at this directory, when it has one."""
    if identifier is not None:
        write_json(
            document=agent_work._HarnessSessionRecord(identifier=identifier),
            path=directory / agent_work._HARNESS_SESSION_RECORD_NAME,
        )


def write_round(
    *,
    directory: Path,
    number: int,
    record: agent_rounds.AgentRoundRecord,
    round_input: DreamcatcherDocument | None = None,
) -> agent_rounds.AgentRoundRecord:
    """Write the record of one round of the work at this directory, and its input.

    A successful round given a merged or closed pull request also completes its
    assignment, as the round's finishing step records before its ending.
    """
    paths = _round_paths(directory=directory, number=number)
    if round_input is not None:
        write_json(document=round_input, path=paths.round_input)
    if (
        isinstance(round_input, agent_assignments.AssignmentRoundInput)
        and round_input.pull_request_state is not PullRequestState.OPEN
        and isinstance(record.ending, agent_rounds.SuccessfulAgentRoundEnding)
    ):
        write_ending(
            directory=directory,
            reason=agent_work.AgentWorkEndReason.COMPLETED,
            at=record.ending.at,
        )
    write_json(document=record, path=paths.record)
    return record


def write_ending(
    *, directory: Path, reason: agent_work.AgentWorkEndReason, at: datetime
) -> None:
    """Record that the work at this directory ended, and why."""
    write_json(
        document=agent_work.AgentWorkEnding(at=at, reason=reason),
        path=directory / agent_work._ENDING_RECORD_NAME,
    )


def write_feed(*, directory: Path, number: int, lines: Sequence[FeedLine]) -> None:
    """Write the feed of one round of the assignment at this directory."""
    write_text(
        text="".join(line.render() for line in lines),
        path=_round_paths(directory=directory, number=number).feed,
    )


def write_tick(*, state: StateDirectory, tick: SchedulerRecord) -> None:
    """Write what the daemon's most recent tick saw."""
    write_json(document=tick, path=state.scheduler_record)


def _round_paths(*, directory: Path, number: int) -> agent_rounds.AgentRoundPaths:
    """Where the numbered round of the assignment at this directory wrote."""
    return agent_rounds.AgentRoundPaths(
        worktree=directory,
        rounds_directory=directory / agent_work._AGENT_ROUNDS_DIRECTORY_NAME,
        number=number,
    )


def write_running_conversation(
    *, state: StateDirectory, issue: int, started: datetime
) -> None:
    """Write a conversation whose first round has started and not ended.

    The round reads as running only while the state's lock names a live daemon.
    """
    directory = write_conversation(state=state, issue=issue)
    write_round(
        directory=directory,
        number=1,
        record=agent_rounds.AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
        ),
        round_input=issue_conversations.ConversationRoundInput(
            issue=issue,
            initial_issue=issue_conversations.InitialConversationIssue(
                title=f"Issue {issue}",
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


def write_final_output(*, directory: Path, number: int, text: str) -> None:
    """Write the final output that one round of the work at this directory reported."""
    write_text(
        text=text, path=_round_paths(directory=directory, number=number).final_output
    )


def read_assignments(*, state: StateDirectory) -> list[agent_work.AgentWork]:
    """Return every assignment in the state directory, by identifier."""
    return [
        work
        for work in agent_work.read_agent_work(state=state)
        if work.record.kind is AgentWorkKind.ASSIGNMENT
    ]


def read_campaign(*, state: StateDirectory, issue: int) -> agent_work.AgentWork | None:
    """Return the newest campaign at the parent issue, if there is one."""
    return agent_work.find_newest_agent_work(
        state=state, issue=issue, kind=AgentWorkKind.CAMPAIGN
    )


def read_conversation(
    *, state: StateDirectory, issue: int
) -> agent_work.AgentWork | None:
    """Return the newest conversation at the issue, if there is one."""
    return agent_work.find_newest_agent_work(
        state=state, issue=issue, kind=AgentWorkKind.CONVERSATION
    )
