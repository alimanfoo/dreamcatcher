from datetime import timedelta

import pytest
from clocks import PINNED
from records import (
    find_conversation_directory,
    read_conversation,
    write_assignment,
    write_conversation,
)

from dreamcatcher.agent_work import (
    AgentWork,
    compose_agent_work_identifier,
    find_agent_work,
    find_newest_agent_work,
    read_agent_work,
    read_agent_work_at_issue,
    read_harness_session_identifier,
    read_retry_requested_at,
    record_harness_session_identifier,
    request_agent_work_retry,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory

IDENTIFIER = "GH12-20260819-184158-assignment"


def written_work(*, state: StateDirectory) -> AgentWork:
    """Write an assignment with no harness session, and return it as read."""
    write_assignment(
        state=state, identifier=IDENTIFIER, issue=12, harness_session_identifier=None
    )
    work = find_agent_work(state=state, identifier=IDENTIFIER)
    assert work is not None
    return work


def test_work_records_the_harness_session_its_first_round_reports(tmp_path):
    work = written_work(state=StateDirectory(root=tmp_path))
    assert read_harness_session_identifier(directory=work.directory) is None

    record_harness_session_identifier(work=work, identifier="abc-123")
    record_harness_session_identifier(work=work, identifier="abc-123")

    assert read_harness_session_identifier(directory=work.directory) == "abc-123"


def test_work_refuses_a_different_harness_session(tmp_path):
    work = written_work(state=StateDirectory(root=tmp_path))
    record_harness_session_identifier(work=work, identifier="abc-123")

    with pytest.raises(
        ReportableError,
        match=(
            "GH12-20260819-184158-assignment reported harness session another-session, "
            "but it already recorded abc-123"
        ),
    ):
        record_harness_session_identifier(work=work, identifier="another-session")

    assert read_harness_session_identifier(directory=work.directory) == "abc-123"


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
    work = written_work(state=StateDirectory(root=tmp_path))
    with pytest.raises(ReportableError, match=message):
        record_harness_session_identifier(work=work, identifier=identifier)

    assert read_harness_session_identifier(directory=work.directory) is None


def test_the_latest_retry_request_is_the_one_the_work_reads(tmp_path):
    work = written_work(state=StateDirectory(root=tmp_path))
    assert read_retry_requested_at(directory=work.directory) is None

    request_agent_work_retry(work=work, at=PINNED)
    request_agent_work_retry(work=work, at=PINNED + timedelta(minutes=1))

    assert read_retry_requested_at(directory=work.directory) == PINNED + timedelta(
        minutes=1
    )


def test_a_session_recorded_through_an_earlier_read_keeps_a_later_retry(tmp_path):
    # The daemon read the conversation before the user's retry landed, then
    # its round reported a harness session.
    state = StateDirectory(root=tmp_path)
    write_conversation(state=state, issue=8, harness_session_identifier=None)
    read_by_the_daemon = read_conversation(state=state, issue=8)
    read_by_the_retry = read_conversation(state=state, issue=8)
    assert read_by_the_daemon is not None
    assert read_by_the_retry is not None
    record = read_by_the_daemon.directory / "work.json"
    created = record.read_bytes()

    request_agent_work_retry(work=read_by_the_retry, at=PINNED)
    record_harness_session_identifier(
        work=read_by_the_daemon, identifier="conversation-session"
    )

    conversation = read_conversation(state=state, issue=8)
    assert conversation is not None
    assert conversation.retry_requested_at == PINNED
    assert conversation.harness_session_identifier == "conversation-session"
    assert record.read_bytes() == created


def test_an_identifier_names_the_issue_the_time_and_the_kind():
    assert (
        compose_agent_work_identifier(
            issue=20, kind=AgentWorkKind.CONVERSATION, at=PINNED
        )
        == "GH20-20260819-184158-conversation"
    )


def test_the_reader_lists_both_kinds_by_identifier_and_skips_unrecorded_work(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    write_conversation(state=state, issue=8)
    write_assignment(state=state, identifier=IDENTIFIER, issue=12)
    (state.work / "GH9-20260819-184158-assignment").mkdir()

    assert [work.identifier for work in read_agent_work(state=state)] == [
        IDENTIFIER,
        "GH8-20260819-184158-conversation",
    ]


def test_a_state_directory_with_no_work_reads_as_none(tmp_path):
    state = StateDirectory(root=tmp_path)

    assert read_agent_work(state=state) == []
    assert find_agent_work(state=state, identifier=IDENTIFIER) is None


def test_the_newest_work_at_an_issue_is_of_the_kind_asked_for(tmp_path):
    state = StateDirectory(root=tmp_path)
    older = "GH8-20260818-090000-assignment"
    newer = "GH8-20260819-090000-assignment"
    for identifier in (newer, older):
        write_assignment(state=state, identifier=identifier, issue=8)
    write_conversation(state=state, issue=8)

    assignments = read_agent_work_at_issue(
        state=state, issue=8, kind=AgentWorkKind.ASSIGNMENT
    )
    newest = find_newest_agent_work(state=state, issue=8, kind=AgentWorkKind.ASSIGNMENT)

    assert [work.identifier for work in assignments] == [older, newer]
    assert newest is not None
    assert newest.identifier == newer
    assert (
        find_newest_agent_work(state=state, issue=9, kind=AgentWorkKind.ASSIGNMENT)
        is None
    )


def test_a_work_record_that_is_not_an_object_is_reportable(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_conversation(state=state, issue=8)
    (find_conversation_directory(state=state, issue=8) / "work.json").write_bytes(
        b"null"
    )

    with pytest.raises(ReportableError, match=r"work\.json"):
        read_agent_work(state=state)
