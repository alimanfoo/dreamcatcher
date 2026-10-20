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
    _compose_agent_work_identifier,
    find_agent_work,
    find_newest_agent_work,
    parse_agent_work_identifier,
    read_agent_work,
    read_agent_work_at_issue,
    record_harness_session_identifier,
    request_agent_work_retry,
    select_agent_work,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory

IDENTIFIER = "GH12-20260819-184158-assignment"


def read_work(*, state: StateDirectory) -> AgentWork:
    """Return the assignment that the tests write, as a read finds it now."""
    work = find_agent_work(state=state, identifier=IDENTIFIER)
    assert work is not None
    return work


def written_work(*, state: StateDirectory) -> AgentWork:
    """Write an assignment with no harness session, and return it as read."""
    write_assignment(
        state=state, identifier=IDENTIFIER, issue=12, harness_session_identifier=None
    )
    return read_work(state=state)


def test_work_records_the_harness_session_its_first_round_reports(tmp_path):
    state = StateDirectory(root=tmp_path)
    work = written_work(state=state)
    assert read_work(state=state).harness_session_identifier is None

    record_harness_session_identifier(work=work, identifier="abc-123")
    record_harness_session_identifier(work=work, identifier="abc-123")

    assert read_work(state=state).harness_session_identifier == "abc-123"


def test_work_refuses_a_different_harness_session(tmp_path):
    state = StateDirectory(root=tmp_path)
    work = written_work(state=state)
    record_harness_session_identifier(work=work, identifier="abc-123")

    with pytest.raises(
        ReportableError,
        match=(
            "GH12-20260819-184158-assignment reported harness session another-session, "
            "but it already recorded abc-123"
        ),
    ):
        record_harness_session_identifier(work=work, identifier="another-session")

    assert read_work(state=state).harness_session_identifier == "abc-123"


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
    state = StateDirectory(root=tmp_path)
    work = written_work(state=state)
    with pytest.raises(ReportableError, match=message):
        record_harness_session_identifier(work=work, identifier=identifier)

    assert read_work(state=state).harness_session_identifier is None


def test_the_latest_retry_request_is_the_one_the_work_reads(tmp_path):
    state = StateDirectory(root=tmp_path)
    work = written_work(state=state)
    assert read_work(state=state).retry_requested_at is None

    request_agent_work_retry(work=work, at=PINNED)
    request_agent_work_retry(work=work, at=PINNED + timedelta(minutes=1))

    assert read_work(state=state).retry_requested_at == PINNED + timedelta(minutes=1)


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
        _compose_agent_work_identifier(
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


def test_an_identifier_that_reaches_outside_the_work_directory_names_no_work(
    tmp_path,
):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=IDENTIFIER, issue=12)
    (state.path / "work.json").write_bytes(
        (state.work / IDENTIFIER / "work.json").read_bytes()
    )

    assert find_agent_work(state=state, identifier="..") is None


@pytest.mark.parametrize(
    "text",
    [
        "GH12-20260819-184158-assignment",
        "gh12-20260819-184158-ASSIGNMENT",
        "GH012-20260819-184158-assignment",
    ],
)
def test_an_identifier_reads_as_its_work_spells_it(text):
    assert parse_agent_work_identifier(text=text) == IDENTIFIER


@pytest.mark.parametrize(
    "text",
    [
        "GH12",
        "GH12-20260819-184158-review",
        "GH12-20261319-184158-assignment",
        "GH12-20260819-184158-assignment-extra",
    ],
)
def test_text_that_could_name_no_work_is_no_identifier(text):
    assert parse_agent_work_identifier(text=text) is None


def test_an_issue_selects_its_newest_work_of_the_kind(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_assignment(
        state=state, identifier="GH12-20260818-090000-assignment", issue=12
    )
    write_assignment(state=state, identifier=IDENTIFIER, issue=12)
    write_conversation(state=state, issue=12)

    selected = select_agent_work(
        state=state, reference=12, kind=AgentWorkKind.ASSIGNMENT
    )

    assert selected.identifier == IDENTIFIER


def test_an_identifier_selects_that_exact_work(tmp_path):
    state = StateDirectory(root=tmp_path)
    older = "GH12-20260818-090000-assignment"
    write_assignment(state=state, identifier=older, issue=12)
    write_assignment(state=state, identifier=IDENTIFIER, issue=12)

    selected = select_agent_work(
        state=state, reference=older, kind=AgentWorkKind.ASSIGNMENT
    )

    assert selected.identifier == older


def test_an_issue_without_work_of_the_kind_selects_none(tmp_path):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=IDENTIFIER, issue=12)

    with pytest.raises(ReportableError, match=r"No conversation here for GH12\."):
        select_agent_work(state=state, reference=12, kind=AgentWorkKind.CONVERSATION)


@pytest.mark.parametrize(
    "identifier", [IDENTIFIER, "GH12-20260801-090000-conversation"]
)
def test_an_identifier_names_no_work_of_another_kind_or_none_at_all(
    identifier, tmp_path
):
    state = StateDirectory(root=tmp_path)
    write_assignment(state=state, identifier=IDENTIFIER, issue=12)

    with pytest.raises(
        ReportableError, match=f"No conversation here is named {identifier}"
    ):
        select_agent_work(
            state=state, reference=identifier, kind=AgentWorkKind.CONVERSATION
        )
