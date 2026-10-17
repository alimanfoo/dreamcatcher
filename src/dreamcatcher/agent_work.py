"""Read and record agent work of both kinds.

Every assignment and every conversation is a piece of agent work, with a
directory under `work/` and a worktree under `worktrees/`, both named by its
identifier. Creation writes the work record once, and nothing writes it again.
Every fact that changes later has a file of its own in the work's directory,
and each write replaces that file whole without merging into what was there. So
writers in different processes or threads never erase each other's facts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

from pydantic import AwareDatetime, Field

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    AssignmentRoundPurpose,
    SuccessfulAgentRoundEnding,
    read_agent_round_records,
)
from dreamcatcher.config import AgentHarness, QuotableText
from dreamcatcher.documents import (
    DreamcatcherDocument,
    read_json,
    read_json_if_exists,
    write_json,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import (
    AgentWorkKind,
    HarnessConfig,
    HarnessSessionIdentifier,
    refuse_reportable_harness_session_identifier,
)
from dreamcatcher.harnesses import find_harness_session_identifier
from dreamcatcher.state import StateDirectory

# The file in a work directory saying what the work was created with.
_WORK_RECORD_NAME = "work.json"

# The file in a work directory naming the harness session that its rounds
# continue.
_HARNESS_SESSION_RECORD_NAME = "harness-session.json"

# The file in a work directory saying when the user last asked it to recover.
_RETRY_REQUEST_RECORD_NAME = "retry-request.json"

# The file in a work directory saying when the user cancelled it.
_CANCEL_RECORD_NAME = "cancel.json"

# The directory in a work directory holding a directory per round.
_AGENT_ROUNDS_DIRECTORY_NAME = "rounds"


class AgentWorkRecord(DreamcatcherDocument):
    """Model the request that created a piece of agent work, and its settings.

    Creation writes the record once, and nothing writes it again. Every round
    reads this record, so later config edits do not change work in progress.
    """

    issue: int
    title: str
    dispatch_label: str
    kind: AgentWorkKind
    harness: AgentHarness
    model: QuotableText
    effort: QuotableText
    harness_config: HarnessConfig = Field(default_factory=dict)
    prompt: str


@dataclass(frozen=True, kw_only=True)
class AgentWork:
    """Represent one piece of agent work as its persisted state currently reads.

    The directory name is the agent work identifier. The record holds the
    settings that the dispatch chose, and every fact that changes later is read
    from a file of its own beside the record. The rounds are ordered from oldest
    to newest.
    """

    directory: Path
    worktree: Path
    record: AgentWorkRecord
    harness_session_identifier: HarnessSessionIdentifier | None = None
    retry_requested_at: datetime | None = None
    cancelled_at: datetime | None = None
    rounds: list[AgentRoundRecord] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        """The identifier that the directory, worktree and messages all carry."""
        return self.directory.name

    @property
    def is_complete(self) -> bool:
        """Whether a wrap-up round has exited successfully."""
        if not self.rounds:
            return False
        round = self.rounds[-1]
        return (
            round.purpose is AssignmentRoundPurpose.WRAP_UP
            and round.outcome is AgentRoundOutcome.SUCCESSFUL
        )

    @property
    def ended_at(self) -> datetime | None:
        """When the work was cancelled or completed, if it has ended."""
        if self.cancelled_at is not None:
            return self.cancelled_at
        if not self.is_complete:
            return None
        return cast("SuccessfulAgentRoundEnding", self.rounds[-1].ending).at

    @property
    def is_open(self) -> bool:
        """Whether the work has neither completed nor been cancelled."""
        return self.ended_at is None

    @property
    def rounds_directory(self) -> Path:
        """The directory holding a directory per round."""
        return self.directory / _AGENT_ROUNDS_DIRECTORY_NAME

    @property
    def next_round_number(self) -> int:
        """The number the work's next round will carry."""
        return self.rounds[-1].number + 1 if self.rounds else 1

    def find_harness_session_identifier(self) -> HarnessSessionIdentifier | None:
        """Return the recorded or recoverable harness session identifier."""
        return find_harness_session_identifier(
            harness=self.record.harness,
            agent_work_identifier=self.identifier,
            recorded=self.harness_session_identifier,
            raw_outputs=(
                self.compose_round_paths(number=round_record.number).raw_output
                for round_record in reversed(self.rounds)
            ),
        )

    def compose_round_paths(self, *, number: int) -> AgentRoundPaths:
        """Return the worktree and file paths for a numbered round.

        Every round runs in the work's worktree, and writes into a directory
        named by the number of the round it is. Round numbers start at one and
        increase in execution order.
        """
        return AgentRoundPaths(
            worktree=self.worktree,
            rounds_directory=self.rounds_directory,
            number=number,
        )


def compose_agent_work_identifier(
    *, issue: int, kind: AgentWorkKind, at: datetime
) -> str:
    """Return the identifier of the work of this kind created at the issue at `at`."""
    return f"GH{issue}-{at:%Y%m%d-%H%M%S}-{kind}"


def record_agent_work(
    *, state: StateDirectory, identifier: str, record: AgentWorkRecord
) -> AgentWork:
    """Write the record that makes the agent work exist, and return the work."""
    directory = state.work / identifier
    write_json(document=record, path=directory / _WORK_RECORD_NAME)
    return AgentWork(
        directory=directory, worktree=state.worktrees / identifier, record=record
    )


def read_agent_work(*, state: StateDirectory) -> list[AgentWork]:
    """Return every piece of agent work of both kinds, ordered by identifier.

    A directory under `work/` is agent work once its record exists, so a
    directory without one is omitted. An invalid record raises ReportableError.

    The state directory is also what the round records are read through, so a
    process that reads the same one again reads only the records that can have
    changed since.
    """
    if not state.work.is_dir():
        return []
    return [
        _read_agent_work(state=state, directory=directory)
        for directory in sorted(state.work.iterdir())
        if (directory / _WORK_RECORD_NAME).is_file()
    ]


def read_agent_work_at_issue(
    *, state: StateDirectory, issue: int, kind: AgentWorkKind
) -> list[AgentWork]:
    """Return the agent work of one kind at the issue, oldest first."""
    return [
        work
        for work in read_agent_work(state=state)
        if work.record.issue == issue and work.record.kind is kind
    ]


def find_newest_agent_work(
    *, state: StateDirectory, issue: int, kind: AgentWorkKind
) -> AgentWork | None:
    """Return the newest agent work of one kind at the issue, if there is any."""
    work = read_agent_work_at_issue(state=state, issue=issue, kind=kind)
    return work[-1] if work else None


def find_agent_work(*, state: StateDirectory, identifier: str) -> AgentWork | None:
    """Return the agent work with this exact identifier, if it exists.

    Only that work's own files are read, so another piece of work that cannot be
    read does not hide this one.
    """
    if not state.work.is_dir():
        return None
    directory = next(
        (path for path in state.work.iterdir() if path.name == identifier), None
    )
    if directory is None or not (directory / _WORK_RECORD_NAME).is_file():
        return None
    return _read_agent_work(state=state, directory=directory)


def _read_agent_work(*, state: StateDirectory, directory: Path) -> AgentWork:
    """Return the agent work whose own files sit in this directory."""
    return AgentWork(
        directory=directory,
        worktree=state.worktrees / directory.name,
        record=read_json(model=AgentWorkRecord, path=directory / _WORK_RECORD_NAME),
        harness_session_identifier=read_harness_session_identifier(directory=directory),
        retry_requested_at=read_retry_requested_at(directory=directory),
        cancelled_at=read_user_request_time(path=directory / _CANCEL_RECORD_NAME),
        rounds=read_agent_round_records(
            cache=state.document_cache,
            directory=directory / _AGENT_ROUNDS_DIRECTORY_NAME,
        ),
    )


class _UserRequestRecord(DreamcatcherDocument):
    """Model when the user asked something of agent work."""

    at: AwareDatetime


class _HarnessSessionRecord(DreamcatcherDocument):
    """Model the harness session that every round of agent work continues."""

    identifier: HarnessSessionIdentifier


def read_harness_session_identifier(
    *, directory: Path
) -> HarnessSessionIdentifier | None:
    """Return the harness session recorded in the directory, if any."""
    record = read_json_if_exists(
        model=_HarnessSessionRecord, path=directory / _HARNESS_SESSION_RECORD_NAME
    )
    return None if record is None else record.identifier


def record_harness_session_identifier(*, work: AgentWork, identifier: str) -> None:
    """Record the harness session that every round of the agent work continues.

    Recording the session that is already recorded changes nothing. A different
    session raises ReportableError, because all the rounds of one piece of agent
    work continue one session.
    """
    safe_identifier = refuse_reportable_harness_session_identifier(
        agent_work_identifier=work.identifier, identifier=identifier
    )
    recorded = read_harness_session_identifier(directory=work.directory)
    if recorded == safe_identifier:
        return
    if recorded is not None:
        raise ReportableError(
            f"{work.identifier} reported harness session {safe_identifier}, "
            f"but it already recorded {recorded}."
        )
    write_json(
        document=_HarnessSessionRecord(identifier=safe_identifier),
        path=work.directory / _HARNESS_SESSION_RECORD_NAME,
    )


def read_user_request_time(*, path: Path) -> datetime | None:
    """Return when the user made the request that the file at path records."""
    record = read_json_if_exists(model=_UserRequestRecord, path=path)
    return None if record is None else record.at


def record_user_request(*, path: Path, at: datetime) -> None:
    """Write the time of the user's request to path, replacing any earlier one."""
    write_json(document=_UserRequestRecord(at=at), path=path)


def read_retry_requested_at(*, directory: Path) -> datetime | None:
    """Return when the user last asked the agent work here to recover."""
    return read_user_request_time(path=directory / _RETRY_REQUEST_RECORD_NAME)


def request_agent_work_retry(*, work: AgentWork, at: datetime) -> None:
    """Record when the user asked faulted agent work to recover again."""
    record_user_request(path=work.directory / _RETRY_REQUEST_RECORD_NAME, at=at)


def read_cancelled_at(*, work: AgentWork) -> datetime | None:
    """Return when the user cancelled the agent work, read afresh from its file."""
    return read_user_request_time(path=work.directory / _CANCEL_RECORD_NAME)


def cancel_agent_work(*, work: AgentWork, at: datetime) -> None:
    """Record when the user cancelled the agent work."""
    record_user_request(path=work.directory / _CANCEL_RECORD_NAME, at=at)
