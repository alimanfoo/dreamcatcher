"""Read and record agent work of both kinds.

Every assignment and every conversation is a piece of agent work, with a
directory under `work/` and a worktree under `worktrees/`, both named by its
identifier. Creation writes the work record once, and nothing writes it again.
Every fact that changes later has a file of its own in the work's directory,
and each write replaces that file whole without merging into what was there. So
writers in different processes or threads never erase each other's facts.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, Field

from dreamcatcher.agent_rounds import (
    AgentRoundOutcome,
    AgentRoundPaths,
    AgentRoundRecord,
    read_agent_round_records,
    request_agent_round_stop,
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

# The file in a work directory saying when and why the work ended.
_ENDING_RECORD_NAME = "ended.json"

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


class AgentWorkEndReason(StrEnum):
    """The reasons agent work ends."""

    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentWorkEnding(DreamcatcherDocument):
    """Model when and why a piece of agent work ended."""

    at: AwareDatetime
    reason: AgentWorkEndReason


@dataclass(frozen=True, kw_only=True)
class AgentWork:
    """Represent one piece of agent work as its persisted state currently reads.

    The directory name is the agent work identifier. The record holds the
    settings that the dispatch chose, and every fact that changes later is read
    from a file of its own beside the record. The rounds are ordered from oldest
    to newest.

    Agent work is open until its ending is recorded.
    """

    directory: Path
    worktree: Path
    record: AgentWorkRecord
    harness_session_identifier: HarnessSessionIdentifier | None = None
    retry_requested_at: datetime | None = None
    ending: AgentWorkEnding | None = None
    rounds: list[AgentRoundRecord] = field(default_factory=list)

    @property
    def identifier(self) -> str:
        """The identifier that the directory, worktree and messages all carry."""
        return self.directory.name

    @property
    def is_open(self) -> bool:
        """Whether the work has not ended."""
        return self.ending is None

    @property
    def relayed_rounds(self) -> list[AgentRoundRecord]:
        """The rounds whose input is behind the cursor, oldest first.

        A round that errored or was interrupted did not finish its turn, so what
        it was given is given again. Every other round has been relayed what it
        was given, a running round included.
        """
        return [
            record
            for record in self.rounds
            if record.outcome
            not in {AgentRoundOutcome.ERRORED, AgentRoundOutcome.INTERRUPTED}
        ]

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
    return _read_selected_agent_work(state=state, is_selected=lambda record: True)


def read_agent_work_of_kind(
    *, state: StateDirectory, kind: AgentWorkKind
) -> list[AgentWork]:
    """Return the agent work of one kind, ordered by identifier."""
    return _read_selected_agent_work(
        state=state, is_selected=lambda record: record.kind is kind
    )


def read_agent_work_at_issue(
    *, state: StateDirectory, issue: int, kind: AgentWorkKind
) -> list[AgentWork]:
    """Return the agent work of one kind at the issue, oldest first."""
    return _read_selected_agent_work(
        state=state,
        is_selected=lambda record: record.issue == issue and record.kind is kind,
    )


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
    if not is_agent_work_recorded(state=state, identifier=identifier):
        return None
    directory = state.work / identifier
    return _read_agent_work(
        state=state,
        directory=directory,
        record=read_json(model=AgentWorkRecord, path=directory / _WORK_RECORD_NAME),
    )


def is_agent_work_recorded(*, state: StateDirectory, identifier: str) -> bool:
    """Return whether agent work with this exact identifier has its record.

    The identifier names a directory directly under `work/`, so one that would
    reach elsewhere, such as `..`, names no work.
    """
    directory = state.work / identifier
    return (
        directory.resolve().parent == state.work.resolve()
        and (directory / _WORK_RECORD_NAME).is_file()
    )


def find_open_agent_work_by_issue(*, work: list[AgentWork]) -> dict[int, AgentWork]:
    """Return the open work among these, keyed by issue."""
    return {item.record.issue: item for item in work if item.is_open}


def _read_selected_agent_work(
    *, state: StateDirectory, is_selected: Callable[[AgentWorkRecord], bool]
) -> list[AgentWork]:
    """Return the agent work whose record is selected, ordered by identifier.

    Each record is read first, so work that is not selected costs one read.
    """
    if not state.work.is_dir():
        return []
    selected = []
    for directory in sorted(state.work.iterdir()):
        path = directory / _WORK_RECORD_NAME
        if not path.is_file():
            continue
        record = read_json(model=AgentWorkRecord, path=path)
        if is_selected(record):
            selected.append(
                _read_agent_work(state=state, directory=directory, record=record)
            )
    return selected


def _read_agent_work(
    *, state: StateDirectory, directory: Path, record: AgentWorkRecord
) -> AgentWork:
    """Return the agent work whose record is read and whose files are here."""
    return AgentWork(
        directory=directory,
        worktree=state.worktrees / directory.name,
        record=record,
        harness_session_identifier=_read_harness_session_identifier(
            directory=directory
        ),
        retry_requested_at=_read_retry_requested_at(directory=directory),
        ending=_read_agent_work_ending(directory=directory),
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


def _read_harness_session_identifier(
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
    recorded = _read_harness_session_identifier(directory=work.directory)
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


def _read_user_request_time(*, path: Path) -> datetime | None:
    """Return when the user made the request that the file at path records."""
    record = read_json_if_exists(model=_UserRequestRecord, path=path)
    return None if record is None else record.at


def _record_user_request(*, path: Path, at: datetime) -> None:
    """Write the time of the user's request to path, replacing any earlier one."""
    write_json(document=_UserRequestRecord(at=at), path=path)


def _read_retry_requested_at(*, directory: Path) -> datetime | None:
    """Return when the user last asked the agent work here to recover."""
    return _read_user_request_time(path=directory / _RETRY_REQUEST_RECORD_NAME)


def request_agent_work_retry(*, work: AgentWork, at: datetime) -> None:
    """Record when the user asked faulted agent work to recover again."""
    _record_user_request(path=work.directory / _RETRY_REQUEST_RECORD_NAME, at=at)


def request_round_stop_if_ended(*, work: AgentWork, paths: AgentRoundPaths) -> None:
    """Ask a round that has just started to stop if its work has ended.

    Call this once the round's record exists, so that an ending recorded at the
    same moment either lands before this read or finds the round itself.
    """
    if _read_agent_work_ending(directory=work.directory) is not None:
        request_agent_round_stop(paths=paths)


def end_agent_work(
    *, work: AgentWork, reason: AgentWorkEndReason, at: datetime
) -> None:
    """Record that the agent work ended, and why."""
    write_json(
        document=AgentWorkEnding(at=at, reason=reason),
        path=work.directory / _ENDING_RECORD_NAME,
    )


def _read_agent_work_ending(*, directory: Path) -> AgentWorkEnding | None:
    return read_json_if_exists(
        model=AgentWorkEnding, path=directory / _ENDING_RECORD_NAME
    )
