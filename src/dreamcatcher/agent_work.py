"""Record the facts that change after agent work is created.

Creation writes the record of each assignment and each conversation once, and
nothing writes it again. Every fact that changes later has a file of its own in
the directory of the assignment or conversation, and each write replaces that
file whole without merging into what was there. So writers in different
processes or threads never erase each other's facts.

This module holds the facts that both kinds of agent work record.
"""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import AwareDatetime

from dreamcatcher.documents import (
    DreamcatcherDocument,
    read_json_if_exists,
    write_json,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import (
    HarnessSessionIdentifier,
    refuse_reportable_harness_session_identifier,
)

# The file in an assignment's or conversation's directory naming the harness
# session that its rounds continue.
_HARNESS_SESSION_RECORD_NAME = "harness-session.json"

# The file in an assignment's or conversation's directory saying when the user
# last asked it to recover.
_RETRY_REQUEST_RECORD_NAME = "retry-request.json"


class AgentWork(Protocol):
    """Identify an assignment or a conversation, and the directory it owns."""

    @property
    def directory(self) -> Path:
        """The directory holding the records of the assignment or conversation."""
        ...

    @property
    def identifier(self) -> str:
        """The agent work identifier, which harness sessions and messages carry."""
        ...


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
    session raises ReportableError, because all the rounds of one assignment or
    conversation continue one session.
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
