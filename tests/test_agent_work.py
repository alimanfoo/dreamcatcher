from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pytest
from clocks import PINNED
from records import write_conversation

from dreamcatcher.agent_work import (
    read_harness_session_identifier,
    read_retry_requested_at,
    record_harness_session_identifier,
    request_agent_work_retry,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.issue_conversations import read_conversation
from dreamcatcher.state import StateDirectory


@dataclass(frozen=True, kw_only=True)
class Work:
    directory: Path
    identifier: str = "GH12-20260819-184158"


def test_work_records_the_harness_session_its_first_round_reports(tmp_path):
    work = Work(directory=tmp_path)
    assert read_harness_session_identifier(directory=tmp_path) is None

    record_harness_session_identifier(work=work, identifier="abc-123")
    record_harness_session_identifier(work=work, identifier="abc-123")

    assert read_harness_session_identifier(directory=tmp_path) == "abc-123"


def test_work_refuses_a_different_harness_session(tmp_path):
    work = Work(directory=tmp_path)
    record_harness_session_identifier(work=work, identifier="abc-123")

    with pytest.raises(
        ReportableError,
        match=(
            "GH12-20260819-184158 reported harness session another-session, "
            "but it already recorded abc-123"
        ),
    ):
        record_harness_session_identifier(work=work, identifier="another-session")

    assert read_harness_session_identifier(directory=tmp_path) == "abc-123"


@pytest.mark.parametrize(
    ("identifier", "message"),
    [
        ("", "identifier is empty"),
        ("bad%identifier", "cannot hold a percent sign"),
        ("--last", "must begin with a letter or digit"),
        ("abc; touch another-file", "contain only ASCII letters"),
    ],
)
def test_work_refuses_an_invalid_harness_session_identifier(
    tmp_path, identifier, message
):
    with pytest.raises(ReportableError, match=message):
        record_harness_session_identifier(
            work=Work(directory=tmp_path), identifier=identifier
        )

    assert read_harness_session_identifier(directory=tmp_path) is None


def test_the_latest_retry_request_is_the_one_the_work_reads(tmp_path):
    work = Work(directory=tmp_path)
    assert read_retry_requested_at(directory=tmp_path) is None

    request_agent_work_retry(work=work, at=PINNED)
    request_agent_work_retry(work=work, at=PINNED + timedelta(minutes=1))

    assert read_retry_requested_at(directory=tmp_path) == PINNED + timedelta(minutes=1)


def test_a_session_recorded_through_an_earlier_read_keeps_a_later_retry(tmp_path):
    # The daemon read the conversation before the user's retry landed, then
    # its round reported a harness session.
    state = StateDirectory(root=tmp_path)
    write_conversation(state=state, issue=8, harness_session_identifier=None)
    read_by_the_daemon = read_conversation(state=state, issue=8)
    read_by_the_retry = read_conversation(state=state, issue=8)
    assert read_by_the_daemon is not None
    assert read_by_the_retry is not None

    request_agent_work_retry(work=read_by_the_retry, at=PINNED)
    record_harness_session_identifier(
        work=read_by_the_daemon, identifier="conversation-session"
    )

    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at == PINNED
    assert conversation.harness_session_identifier == "conversation-session"
