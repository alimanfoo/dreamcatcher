from datetime import timedelta
from importlib.metadata import version
from unittest.mock import Mock

import pytest
from clocks import PINNED
from conftest import configure
from records import (
    write_assignment,
    write_conversation,
    write_daemon_lock,
    write_feed,
    write_round,
)

from dreamcatcher import web
from dreamcatcher.agent_assignments import read_assignments_for_issue
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    AssignmentRoundPurpose,
    ConversationRoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.cli import MAX_INTERVAL_SECONDS, main
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DreamcatcherDaemon
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.issue_conversations import read_conversation
from dreamcatcher.scheduler import derive_agent_work_fault
from dreamcatcher.scheduler.models import GlobalCooldown, SchedulerRecord
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"


def write_faulted_conversation(*, state: StateDirectory, issue: int) -> None:
    """Write a conversation whose latest two rounds errored."""
    directory = write_conversation(state=state, issue=issue)
    for number in (1, 2):
        ended = PINNED + timedelta(minutes=number)
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=ended,
                pid=1,
                purpose=ConversationRoundPurpose.DISCUSS,
                is_recovery=number > 1,
                ending=compose_agent_round_ending(at=ended, status=number),
            ),
        )


@pytest.fixture
def watching(tmp_path):
    """A checkout a daemon has watched, holding one assignment with a live round."""
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_daemon_lock(path=state.lock)
    directory = write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=AssignmentRoundPurpose.IMPLEMENT,
        ),
    )
    write_feed(
        directory=directory, number=1, lines=[FeedLine(at=PINNED, text="[Bash] pytest")]
    )
    return state


@pytest.fixture
def started(monkeypatch):
    """Return the daemons a run started, with the tick loop held back."""
    daemons = []
    monkeypatch.setattr(
        DreamcatcherDaemon, "run", lambda daemon: daemons.append(daemon)
    )
    return daemons


@pytest.fixture
def faulted(tmp_path):
    """A watched checkout whose only assignment has failed twice."""
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    directory = write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13)
    for number in (1, 2):
        ended = PINNED + timedelta(minutes=number)
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=ended,
                pid=1,
                purpose=AssignmentRoundPurpose.IMPLEMENT,
                ending=compose_agent_round_ending(at=ended, status=number),
            ),
        )
    return state


def test_version_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == version("dreamcatcher")


def test_a_checkout_no_daemon_has_watched_has_nothing_to_show(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)

    assert main(argv=["status"]) == 1
    assert "nothing to show" in capsys.readouterr().err


def test_web_serves_the_state_directory_in_the_current_checkout(monkeypatch, watching):
    monkeypatch.chdir(watching.root)
    served = []

    def record_server(*, state, port):
        served.append((state, port))

    monkeypatch.setattr(web, "serve_web", record_server)

    assert main(argv=["web", "--port", "8123"]) == 0
    assert served == [(watching, 8123)]


def test_web_refuses_a_checkout_no_daemon_has_watched(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(argv=["web"]) == 1
    assert "nothing to show" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_web_refuses_an_invalid_port(port, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["web", "--port", port])

    assert exit_info.value.code == 2
    assert "--port" in capsys.readouterr().err


def test_status_shows_every_assignment(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["status"]) == 0
    assert "working" in capsys.readouterr().out


def test_assignment_shows_the_newest_assignment_at_the_issue(
    monkeypatch, watching, capsys
):
    monkeypatch.chdir(watching.root)

    assert main(argv=["assignment", "GH13"]) == 0
    assert ASSIGNMENT_ID in capsys.readouterr().out


def test_an_issue_reads_however_the_reader_wrote_it(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["assignment", "gh13"]) == 0
    assert ASSIGNMENT_ID in capsys.readouterr().out


def test_something_that_is_not_an_issue_reference_is_refused(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["assignment", "the one about the parser"])

    assert exit_info.value.code == 2
    assert "GH123" in capsys.readouterr().err


def test_retry_clears_the_newest_assignments_fault(monkeypatch, faulted, capsys):
    requested = PINNED + timedelta(minutes=3)
    write_json(
        document=SchedulerRecord(
            at=PINNED,
            most_recent_cooldown_ended=PINNED - timedelta(minutes=1),
        ),
        path=faulted.scheduler_record,
    )
    monkeypatch.chdir(faulted.root)
    monkeypatch.setattr("dreamcatcher.cli.read_current_time", lambda: requested)

    assert main(argv=["retry", "GH13"]) == 0

    assignment = read_assignments_for_issue(state=faulted, issue=13)[-1]
    assert assignment.record.retry_requested_at == requested
    assert not derive_agent_work_fault(
        rounds=assignment.rounds,
        retry_requested_at=assignment.record.retry_requested_at,
        most_recent_cooldown_ended=PINNED - timedelta(minutes=1),
    )
    assert "next scheduler tick" in capsys.readouterr().out


def test_retry_clears_a_conversations_fault(monkeypatch, tmp_path, capsys):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_faulted_conversation(state=state, issue=13)
    requested = PINNED + timedelta(minutes=3)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("dreamcatcher.cli.read_current_time", lambda: requested)

    assert main(argv=["retry", "GH13"]) == 0

    conversation = read_conversation(state=state, issue=13)
    assert conversation is not None
    assert conversation.record.retry_requested_at == requested
    assert not derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.record.retry_requested_at,
        most_recent_cooldown_ended=None,
    )
    assert "conversation-GH13" in capsys.readouterr().out


def test_retry_clears_assignment_and_conversation_faults(monkeypatch, faulted, capsys):
    write_faulted_conversation(state=faulted, issue=13)
    requested = PINNED + timedelta(minutes=3)
    monkeypatch.chdir(faulted.root)
    monkeypatch.setattr("dreamcatcher.cli.read_current_time", lambda: requested)

    assert main(argv=["retry", "GH13"]) == 0

    assignment = read_assignments_for_issue(state=faulted, issue=13)[-1]
    conversation = read_conversation(state=faulted, issue=13)
    assert conversation is not None
    assert assignment.record.retry_requested_at == requested
    assert conversation.record.retry_requested_at == requested
    output = capsys.readouterr().out
    assert assignment.identifier in output
    assert conversation.identifier in output


def test_retry_reports_when_only_the_assignment_retry_was_saved(
    monkeypatch, faulted, capsys
):
    write_faulted_conversation(state=faulted, issue=13)
    requested = PINNED + timedelta(minutes=3)
    monkeypatch.chdir(faulted.root)
    monkeypatch.setattr("dreamcatcher.cli.read_current_time", lambda: requested)
    monkeypatch.setattr(
        "dreamcatcher.cli.request_conversation_retry",
        Mock(side_effect=ReportableError("conversation record is read-only")),
    )

    assert main(argv=["retry", "GH13"]) == 1

    assignment = read_assignments_for_issue(state=faulted, issue=13)[-1]
    conversation = read_conversation(state=faulted, issue=13)
    assert conversation is not None
    assert assignment.record.retry_requested_at == requested
    assert conversation.record.retry_requested_at is None
    error = capsys.readouterr().err
    assert f"{assignment.identifier} can recover" in error
    assert "conversation-GH13 could not be retried" in error
    assert "conversation record is read-only" in error


def test_retry_refuses_a_fault_an_elapsed_cooldown_cleared(
    monkeypatch, faulted, capsys
):
    cooldown_ended = PINNED + timedelta(minutes=3)
    write_json(
        document=SchedulerRecord(
            at=PINNED,
            cooldown=GlobalCooldown(started=PINNED, ends=cooldown_ended),
        ),
        path=faulted.scheduler_record,
    )
    monkeypatch.chdir(faulted.root)
    monkeypatch.setattr(
        "dreamcatcher.cli.read_current_time",
        lambda: cooldown_ended,
    )

    assert main(argv=["retry", "GH13"]) == 1

    assignment = read_assignments_for_issue(state=faulted, issue=13)[-1]
    assert assignment.record.retry_requested_at is None
    assert "no agent work in fault" in capsys.readouterr().err


def test_retry_refuses_an_issue_with_no_agent_work(monkeypatch, tmp_path, capsys):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    state.path.mkdir()
    monkeypatch.chdir(tmp_path)

    assert main(argv=["retry", "GH13"]) == 1
    assert "no agent work in fault" in capsys.readouterr().err


def test_retry_refuses_an_issue_with_no_work_in_fault(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["retry", "GH13"]) == 1
    assert "no agent work in fault" in capsys.readouterr().err


def test_feed_shows_what_the_assignment_said(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)
    # A following view runs until the assignment has completed its wrap-up, so this
    # one is over before the view opens and the view never waits. An assignment's
    # rounds read back in the order they started, so the wrap-up round starts
    # after the first one rather than alongside it.
    later = PINNED + timedelta(minutes=1)
    write_round(
        directory=watching.assignments / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=later,
            pid=1,
            purpose=AssignmentRoundPurpose.WRAP_UP,
            ending=compose_agent_round_ending(at=later, status=0),
        ),
    )

    assert main(argv=["feed", "GH13", "--assignment"]) == 0
    assert "round 1: implement" in capsys.readouterr().out


def test_feed_naming_a_round_shows_that_rounds_feed(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["feed", "GH13", "--assignment", "--round", "1"]) == 0
    assert "round 1: implement" in capsys.readouterr().out


def test_conversation_shows_its_local_detail(monkeypatch, watching, capsys):
    write_conversation(state=watching, issue=8)
    monkeypatch.chdir(watching.root)

    assert main(argv=["conversation", "GH8"]) == 0
    assert "issue conversation GH8" in capsys.readouterr().out


def test_feed_shows_what_the_conversation_said(monkeypatch, watching, capsys):
    directory = write_conversation(state=watching, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            purpose=ConversationRoundPurpose.DISCUSS,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="The answer.")],
    )
    monkeypatch.chdir(watching.root)

    assert main(argv=["feed", "GH8", "--conversation"]) == 0
    assert "The answer." in capsys.readouterr().out


def test_feed_requires_one_owner_selector(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["feed", "GH13"])

    assert exit_info.value.code == 2
    assert "--assignment --conversation" in capsys.readouterr().err


def test_feed_refuses_two_owner_selectors(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["feed", "GH13", "--assignment", "--conversation"])

    assert exit_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_a_feed_with_no_issue_to_show_asks_for_one(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["feed"])

    assert exit_info.value.code == 2
    assert "GH<n>" in capsys.readouterr().err


def test_a_round_belongs_to_the_feed_and_to_no_other_verb(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["assignment", "GH13", "--round", "1"])

    assert exit_info.value.code == 2
    assert "--round" in capsys.readouterr().err


def test_status_takes_no_issue(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["status", "GH13"])

    assert exit_info.value.code == 2
    assert "GH13" in capsys.readouterr().err


@pytest.mark.parametrize(
    "verb", ["run", "retry", "web", "status", "assignment", "feed"]
)
def test_every_verb_describes_itself_in_its_own_help(verb, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=[verb, "--help"])

    # argparse sets the verb's description between the usage line and the
    # first list of arguments, so a verb that carries none runs the two
    # together and the reader learns nothing but the arguments.
    assert exit_info.value.code == 0
    _, _, described = capsys.readouterr().out.partition("\n\n")
    assert not described.startswith(("positional arguments:", "options:"))


def test_a_bare_invocation_asks_for_a_verb(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=[])

    assert exit_info.value.code == 2
    assert "verb" in capsys.readouterr().err


def test_run_starts_a_daemon_on_the_current_directory(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "claude"]) == 0
    assert started[0].state.root == watched
    assert started[0].harness is AgentHarness.CLAUDE
    assert started[0].interval == 120
    assert started[0].max_agents == 1


def test_the_harness_flag_says_what_to_run_rounds_with(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "codex"]) == 0
    assert started[0].harness is AgentHarness.CODEX


def test_run_uses_the_requested_interval_and_agent_cap(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert (
        main(
            argv=[
                "run",
                "--harness",
                "claude",
                "--interval",
                "30",
                "--max-agents",
                "4",
            ]
        )
        == 0
    )
    assert started[0].interval == 30
    assert started[0].max_agents == 4


@pytest.mark.parametrize(
    ("option", "value"), [("--interval", "0"), ("--max-agents", "many")]
)
def test_run_refuses_a_non_positive_integer_control(option, value, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["run", "--harness", "claude", option, value])

    assert exit_info.value.code == 2
    assert "must be a positive integer" in capsys.readouterr().err


def test_run_refuses_an_interval_too_large_to_wait(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(
            argv=[
                "run",
                "--harness",
                "claude",
                "--interval",
                str(MAX_INTERVAL_SECONDS + 1),
            ]
        )

    assert exit_info.value.code == 2
    assert "must be no greater than" in capsys.readouterr().err


def test_a_run_with_no_harness_asks_for_one(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["run"])

    assert exit_info.value.code == 2
    assert "--harness" in capsys.readouterr().err


def test_a_harness_that_does_not_exist_is_refused(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["run", "--harness", "cloud"])

    assert exit_info.value.code == 2
    complaint = capsys.readouterr().err
    assert "cloud" in complaint
    assert all(harness in complaint for harness in AgentHarness)


def test_a_failure_the_user_must_read_is_a_message_not_a_traceback(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)

    assert main(argv=["run", "--harness", "claude"]) == 1
    assert "main checkout" in capsys.readouterr().err


def test_a_write_the_daemon_cannot_make_is_a_message_not_a_traceback(
    monkeypatch, watched, capsys, harnesses
):
    monkeypatch.chdir(watched)
    (watched / ".dreamcatcher").write_text("not a directory\n", encoding="utf-8")

    assert main(argv=["run", "--harness", "claude"]) == 1
    assert "cannot write" in capsys.readouterr().err
