from contextlib import contextmanager
from datetime import timedelta
from importlib.metadata import version

import pytest
from clocks import PINNED
from conftest import configure
from records import (
    MERGED_INPUT,
    hold_daemon_lock_for_test,
    read_conversation,
    read_newest_work,
    write_assignment,
    write_campaign,
    write_conversation,
    write_feed,
    write_round,
)

from dreamcatcher import web
from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import (
    AgentWorkEndReason,
    end_agent_work,
    read_agent_work_at_issue,
)
from dreamcatcher.cli import _MAX_INTERVAL_SECONDS, main
from dreamcatcher.config import AgentHarness
from dreamcatcher.daemon import DreamcatcherDaemon
from dreamcatcher.documents import write_json
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler import derive_agent_work_fault
from dreamcatcher.scheduler.models import GlobalCooldown, SchedulerRecord
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158-assignment"


def write_faulted_conversation(*, state: StateDirectory, issue: int) -> None:
    """Write a conversation whose latest two rounds errored."""
    write_faulted_rounds(directory=write_conversation(state=state, issue=issue))


def write_faulted_rounds(*, directory) -> None:
    """Write two errored rounds for the work at this directory."""
    for number in (1, 2):
        ended = PINNED + timedelta(minutes=number)
        write_round(
            directory=directory,
            number=number,
            record=AgentRoundRecord(
                number=number,
                started=ended,
                pid=1,
                ending=_compose_agent_round_ending(at=ended, status=number),
            ),
        )


@pytest.fixture
def watching(tmp_path):
    """A checkout a daemon has watched, holding one assignment with a live round."""
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    hold_daemon_lock_for_test(path=state.lock)
    directory = write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
        ),
    )
    write_feed(
        directory=directory, number=1, lines=[FeedLine(at=PINNED, text="[Bash] pytest")]
    )
    return state


@pytest.fixture
def served(monkeypatch):
    """Return the state directories whose web interface a run served."""
    states = []

    @contextmanager
    def serve_web_in_background(*, state):
        states.append(state)
        yield

    monkeypatch.setattr(web, "serve_web_in_background", serve_web_in_background)
    return states


@pytest.fixture
def started(monkeypatch, served):
    """Return the daemons a run started, with the tick loop held back."""
    daemons = []

    def run(daemon, /, *, companion=None):
        if companion is None:
            daemons.append(daemon)
            return
        with companion:
            daemons.append(daemon)

    monkeypatch.setattr(DreamcatcherDaemon, "run", run)
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
                ending=_compose_agent_round_ending(at=ended, status=number),
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


def test_view_shows_the_one_piece_of_agent_work_at_the_issue(
    monkeypatch, watching, capsys
):
    monkeypatch.chdir(watching.root)

    assert main(argv=["view", "GH13"]) == 0
    assert ASSIGNMENT_ID in capsys.readouterr().out


def test_an_issue_reads_however_the_reader_wrote_it(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["view", "gh13"]) == 0
    assert ASSIGNMENT_ID in capsys.readouterr().out


def test_retry_clears_the_assignments_fault(monkeypatch, faulted, capsys):
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

    assignment = read_newest_work(
        state=faulted, issue=13, kind=AgentWorkKind.ASSIGNMENT
    )
    assert assignment.retry_requested_at == requested
    assert not derive_agent_work_fault(
        rounds=assignment.rounds,
        retry_requested_at=assignment.retry_requested_at,
        most_recent_cooldown_ended=PINNED - timedelta(minutes=1),
    )
    assert "later scheduler update" in capsys.readouterr().out


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
    assert conversation.retry_requested_at == requested
    assert not derive_agent_work_fault(
        rounds=conversation.rounds,
        retry_requested_at=conversation.retry_requested_at,
        most_recent_cooldown_ended=None,
    )
    assert "GH13-20260819-184158-conversation" in capsys.readouterr().out


def test_retry_clears_the_fault_of_the_work_it_names_and_no_other(
    monkeypatch, faulted, capsys
):
    write_faulted_conversation(state=faulted, issue=13)
    requested = PINNED + timedelta(minutes=3)
    monkeypatch.chdir(faulted.root)
    monkeypatch.setattr("dreamcatcher.cli.read_current_time", lambda: requested)
    conversation = read_conversation(state=faulted, issue=13)
    assert conversation is not None

    assert main(argv=["retry", conversation.identifier]) == 0

    assignment = read_newest_work(
        state=faulted, issue=13, kind=AgentWorkKind.ASSIGNMENT
    )
    conversation = read_conversation(state=faulted, issue=13)
    assert conversation is not None
    assert assignment.retry_requested_at is None
    assert conversation.retry_requested_at == requested
    assert capsys.readouterr().out == (
        f"{conversation.identifier} can run again on a later scheduler update.\n"
    )


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

    assert main(argv=["retry", "GH13"]) == 1

    assignment = read_newest_work(
        state=faulted, issue=13, kind=AgentWorkKind.ASSIGNMENT
    )
    assert assignment.retry_requested_at is None
    assert capsys.readouterr().err == f"{ASSIGNMENT_ID} is not in fault.\n"


def test_retry_refuses_an_issue_with_no_work_in_fault(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["retry", "GH13"]) == 1
    assert capsys.readouterr().err == f"{ASSIGNMENT_ID} is not in fault.\n"


def test_stop_requests_the_newest_assignments_running_round(
    monkeypatch, watching, capsys
):
    monkeypatch.chdir(watching.root)

    assert main(argv=["stop", "GH13"]) == 0

    assignment = read_newest_work(
        state=watching, issue=13, kind=AgentWorkKind.ASSIGNMENT
    )
    paths = assignment.compose_round_paths(number=1)
    assert paths.stop_request.read_text(encoding="utf-8") == ""
    assert (
        f"Requested a stop for {assignment.identifier} round 1."
        in capsys.readouterr().out
    )


def test_stop_requests_an_issue_conversations_running_round(
    monkeypatch, tmp_path, capsys
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    hold_daemon_lock_for_test(path=state.lock)
    directory = write_conversation(state=state, issue=13)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
        ),
    )
    monkeypatch.chdir(tmp_path)

    assert main(argv=["stop", "GH13"]) == 0

    conversation = read_conversation(state=state, issue=13)
    assert conversation is not None
    paths = conversation.compose_round_paths(number=1)
    assert paths.stop_request.read_text(encoding="utf-8") == ""
    assert (
        f"Requested a stop for {conversation.identifier} round 1."
        in capsys.readouterr().out
    )


def test_cancel_ends_the_newest_assignment_and_stops_its_running_round(
    monkeypatch, watching, capsys
):
    monkeypatch.chdir(watching.root)

    assert main(argv=["cancel", "GH13"]) == 0

    assignment = read_newest_work(
        state=watching, issue=13, kind=AgentWorkKind.ASSIGNMENT
    )
    assert not assignment.is_open
    assert assignment.compose_round_paths(number=1).stop_request.is_file()
    assert capsys.readouterr().out == f"{ASSIGNMENT_ID} is cancelled.\n"


def test_cancel_of_an_assignment_without_a_pull_request(monkeypatch, tmp_path, capsys):
    configure(root=tmp_path)
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13, pull_request=None)
    monkeypatch.chdir(tmp_path)

    assert main(argv=["cancel", "GH13"]) == 0

    assert capsys.readouterr().out == f"{ASSIGNMENT_ID} is cancelled.\n"


def test_cancel_leaves_older_assignments_at_the_issue_alone(monkeypatch, watching):
    write_assignment(
        state=watching, identifier="GH13-20260818-090000-assignment", issue=13
    )
    monkeypatch.chdir(watching.root)

    assert main(argv=["cancel", ASSIGNMENT_ID]) == 0

    older, newest = read_agent_work_at_issue(state=watching, issue=13)
    assert older.is_open
    assert newest.identifier == ASSIGNMENT_ID
    assert not newest.is_open


def test_cancel_refuses_an_assignment_that_has_already_ended(
    monkeypatch, watching, capsys
):
    monkeypatch.chdir(watching.root)
    assert main(argv=["cancel", "GH13"]) == 0
    capsys.readouterr()

    assert main(argv=["cancel", "GH13"]) == 1
    assert capsys.readouterr().err == f"{ASSIGNMENT_ID} has already ended.\n"


@pytest.mark.parametrize(
    "command",
    ["retry", "stop", "cancel", "view", "feed"],
)
def test_a_command_refuses_an_issue_without_agent_work(
    monkeypatch, tmp_path, capsys, command
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    state.path.mkdir()
    monkeypatch.chdir(tmp_path)

    assert main(argv=[command, "GH13"]) == 1
    assert capsys.readouterr().err == "No agent work here for GH13.\n"


def test_stop_refuses_a_round_without_a_resumable_session(
    monkeypatch, tmp_path, capsys
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    hold_daemon_lock_for_test(path=state.lock)
    directory = write_assignment(
        state=state,
        identifier=ASSIGNMENT_ID,
        issue=13,
        harness_session_identifier=None,
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
        ),
    )
    monkeypatch.chdir(tmp_path)

    assert main(argv=["stop", "GH13"]) == 1

    assignment = read_newest_work(state=state, issue=13, kind=AgentWorkKind.ASSIGNMENT)
    paths = assignment.compose_round_paths(number=1)
    assert not paths.stop_request.exists()
    assert "has no running round that can be stopped" in capsys.readouterr().err


def test_stop_refuses_a_conversation_round_without_a_resumable_session(
    monkeypatch, tmp_path, capsys
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    hold_daemon_lock_for_test(path=state.lock)
    directory = write_conversation(
        state=state,
        issue=13,
        harness_session_identifier=None,
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
        ),
    )
    monkeypatch.chdir(tmp_path)

    assert main(argv=["stop", "GH13"]) == 1

    conversation = read_conversation(state=state, issue=13)
    assert conversation is not None
    paths = conversation.compose_round_paths(number=1)
    assert not paths.stop_request.exists()
    assert "has no running round that can be stopped" in capsys.readouterr().err


def test_feed_shows_what_the_assignment_said(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)
    # A following view runs until the assignment has completed its wrap-up, so this
    # one is over before the view opens and the view never waits. An assignment's
    # rounds read back in the order they started, so the wrap-up round starts
    # after the first one rather than alongside it.
    later = PINNED + timedelta(minutes=1)
    write_round(
        directory=watching.work / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=later,
            pid=1,
            ending=_compose_agent_round_ending(at=later, status=0),
        ),
        round_input=MERGED_INPUT,
    )

    assert main(argv=["feed", "GH13"]) == 0
    assert "round 1: start" in capsys.readouterr().out


def test_feed_naming_a_round_shows_that_rounds_feed(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["feed", "GH13", "--round", "1"]) == 0
    assert "round 1: start" in capsys.readouterr().out


def test_conversation_shows_its_local_detail(monkeypatch, watching, capsys):
    write_conversation(state=watching, issue=8)
    monkeypatch.chdir(watching.root)

    assert main(argv=["view", "GH8"]) == 0
    assert "conversation GH8-" in capsys.readouterr().out


def test_feed_shows_what_the_conversation_said(monkeypatch, watching, capsys):
    directory = write_conversation(state=watching, issue=8)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="The answer.")],
    )
    monkeypatch.chdir(watching.root)

    assert main(argv=["feed", "GH8"]) == 0
    assert "The answer." in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["assignment", "GH13"],
        ["conversation", "GH13"],
        ["campaign", "GH13"],
        ["stop", "GH13", "--assignment"],
        ["feed", "GH13", "--conversation"],
        ["feed", "GH13", "--campaign"],
    ],
)
def test_a_command_or_kind_selector_that_is_gone_is_refused(arguments, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=arguments)

    assert exit_info.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_a_feed_with_no_issue_to_show_asks_for_one(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["feed"])

    assert exit_info.value.code == 2
    assert "GH<n>" in capsys.readouterr().err


def test_a_round_belongs_to_the_feed_and_to_no_other_command(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["view", "GH13", "--round", "1"])

    assert exit_info.value.code == 2
    assert "--round" in capsys.readouterr().err


def test_status_takes_no_issue(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["status", "GH13"])

    assert exit_info.value.code == 2
    assert "GH13" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        "init",
        "run",
        "retry",
        "stop",
        "cancel",
        "web",
        "status",
        "view",
        "feed",
    ],
)
def test_every_command_describes_itself_in_its_own_help(command, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=[command, "--help"])

    # argparse sets the command's description between the usage line and the
    # first list of arguments, so a command that carries none runs the two
    # together and the reader learns nothing but the arguments.
    assert exit_info.value.code == 0
    _, _, described = capsys.readouterr().out.partition("\n\n")
    assert not described.startswith(("positional arguments:", "options:"))


@pytest.mark.parametrize(
    ("command", "description"),
    [
        ("view", "until the work ends"),
        ("feed", "until the work ends"),
    ],
)
def test_live_view_help_explains_what_ends_each_view(command, description, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=[command, "--help"])

    assert exit_info.value.code == 0
    assert description in " ".join(capsys.readouterr().out.split())


def test_status_help_says_why_a_labelled_issue_has_no_work(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["status", "--help"])

    assert exit_info.value.code == 0
    assert "with why no work has started" in " ".join(capsys.readouterr().out.split())


def test_a_bare_invocation_asks_for_a_command(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=[])

    assert exit_info.value.code == 2
    assert "command" in capsys.readouterr().err


def test_run_starts_a_daemon_on_the_current_directory(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "claude"]) == 0
    assert started[0].state.root == watched
    assert started[0].preferred_harness is AgentHarness.CLAUDE
    assert started[0].interval == 120
    assert started[0].max_agents == 1


def test_run_serves_the_web_interface_while_the_daemon_runs(
    monkeypatch, watched, started, served
):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "claude"]) == 0
    assert served == [started[0].state]


def test_noweb_runs_only_the_daemon(monkeypatch, watched, started, served):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "claude", "--noweb"]) == 0
    assert len(started) == 1
    assert served == []


def test_the_harness_flag_says_what_to_run_rounds_with(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "codex"]) == 0
    assert started[0].preferred_harness is AgentHarness.CODEX


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
                str(_MAX_INTERVAL_SECONDS + 1),
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


def test_a_lock_the_daemon_cannot_take_is_a_message_not_a_traceback(
    monkeypatch, watched, capsys, harnesses
):
    monkeypatch.chdir(watched)
    (watched / ".dreamcatcher").write_text("not a directory\n", encoding="utf-8")

    assert main(argv=["run", "--harness", "claude"]) == 1
    assert "cannot lock" in capsys.readouterr().err


OLDER_ASSIGNMENT_ID = "GH13-20260818-090000-assignment"


def write_older_assignment(*, state: StateDirectory) -> None:
    """Write an assignment at GH13 older than the one the checkout is watching."""
    directory = write_assignment(state=state, identifier=OLDER_ASSIGNMENT_ID, issue=13)
    started = PINNED - timedelta(days=1)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=started,
            pid=1,
            ending=_compose_agent_round_ending(at=started, status=0),
        ),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=started, text="[Bash] git log")],
    )


def test_an_identifier_shows_that_assignment_rather_than_the_newest(
    monkeypatch, watching, capsys
):
    write_older_assignment(state=watching)
    monkeypatch.chdir(watching.root)

    assert main(argv=["view", OLDER_ASSIGNMENT_ID.lower()]) == 0
    shown = capsys.readouterr().out
    assert f"assignment {OLDER_ASSIGNMENT_ID}" in shown
    assert ASSIGNMENT_ID not in shown


@pytest.mark.parametrize("round_selection", [[], ["--round", "1"]])
def test_an_identifier_shows_that_assignments_feed_alone(
    monkeypatch, watching, capsys, round_selection
):
    write_older_assignment(state=watching)
    monkeypatch.chdir(watching.root)

    assert main(argv=["feed", OLDER_ASSIGNMENT_ID, *round_selection]) == 0
    shown = capsys.readouterr().out
    assert "[Bash] git log" in shown
    assert "[Bash] pytest" not in shown


def write_switched_conversations(*, state: StateDirectory) -> tuple[str, str]:
    """Write two conversations at GH8, under the label the user left and the next.

    Each has a running round with its own output. Return the older identifier,
    then the newer.
    """
    identifiers = []
    for hours, label, text in (
        (0, "dream:conversation", "The first answer."),
        (1, "dream:scout", "The second answer."),
    ):
        at = PINNED + timedelta(hours=hours)
        directory = write_conversation(
            state=state, issue=8, at=at, dispatch_label=label
        )
        write_round(
            directory=directory,
            number=1,
            record=AgentRoundRecord(number=1, started=at, pid=1),
        )
        write_feed(directory=directory, number=1, lines=[FeedLine(at=at, text=text)])
        identifiers.append(directory.name)
    older, newer = identifiers
    return older, newer


def test_an_older_conversation_can_be_selected_after_a_label_switch(
    monkeypatch, watching, capsys
):
    older, newer = write_switched_conversations(state=watching)
    monkeypatch.chdir(watching.root)

    assert main(argv=["view", "GH8"]) == 1
    asked = capsys.readouterr().err
    assert f"dreamcatcher view {older}\n  dreamcatcher view {newer}" in asked
    assert main(argv=["view", older]) == 0
    assert f"conversation {older}" in capsys.readouterr().out
    assert main(argv=["feed", older]) == 0
    shown = capsys.readouterr().out
    assert "The first answer." in shown
    assert "The second answer." not in shown


def test_stop_names_an_older_conversation_and_stops_it_alone(
    monkeypatch, watching, capsys
):
    older, newer = write_switched_conversations(state=watching)
    monkeypatch.chdir(watching.root)

    assert main(argv=["stop", older]) == 0

    assert f"Requested a stop for {older} round 1." in capsys.readouterr().out
    assert (watching.work / older / "rounds" / "1" / "stop-request").is_file()
    assert not (watching.work / newer / "rounds" / "1" / "stop-request").exists()


def test_stop_refuses_an_older_assignment_with_no_running_round(
    monkeypatch, watching, capsys
):
    write_older_assignment(state=watching)
    monkeypatch.chdir(watching.root)

    assert main(argv=["stop", OLDER_ASSIGNMENT_ID]) == 1

    assert (
        f"{OLDER_ASSIGNMENT_ID} has no running round that can be stopped."
        in capsys.readouterr().err
    )
    assert not list(watching.work.glob("*/rounds/*/stop-request"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["view", "GH8-20260101-090000-conversation"],
        ["feed", "GH13-20260101-090000-assignment"],
        ["stop", "GH13-20260101-090000-assignment"],
        ["retry", "GH13-20260101-090000-assignment"],
        ["cancel", "GH13-20260101-090000-assignment"],
    ],
)
def test_an_identifier_of_no_work_is_refused(monkeypatch, watching, capsys, arguments):
    write_conversation(state=watching, issue=8)
    monkeypatch.chdir(watching.root)

    assert main(argv=arguments) == 1

    assert capsys.readouterr().err == f"No agent work here is named {arguments[1]}.\n"
    assert not list(watching.work.glob("*/rounds/*/stop-request"))


@pytest.mark.parametrize("command", ["retry", "stop", "cancel", "view", "feed"])
@pytest.mark.parametrize(
    "text", ["the one about the parser", "GH\u0661\u0662", "GH13-yesterday-assignment"]
)
def test_text_that_names_neither_an_issue_nor_work_is_refused(command, text, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=[command, text])

    assert exit_info.value.code == 2
    assert f"not as {text}" in capsys.readouterr().err


def test_campaign_shows_its_local_detail_and_feed(monkeypatch, watching, capsys):
    directory = write_campaign(state=watching, issue=20)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="I acknowledged the plan.")],
    )
    monkeypatch.chdir(watching.root)

    assert main(argv=["view", "GH20"]) == 0
    assert "campaign GH20-" in capsys.readouterr().out
    assert main(argv=["feed", "GH20"]) == 0
    assert "I acknowledged the plan." in capsys.readouterr().out


def test_stop_refuses_a_campaign_with_no_running_round(monkeypatch, watching, capsys):
    write_campaign(state=watching, issue=20)
    monkeypatch.chdir(watching.root)

    assert main(argv=["stop", "GH20"]) == 1
    assert "has no running round that can be stopped" in capsys.readouterr().err


def test_retry_reports_a_retry_that_could_not_be_saved(monkeypatch, faulted, capsys):
    monkeypatch.chdir(faulted.root)

    def refuse_retry(*, work, at):
        raise ReportableError("assignment record is read-only")

    monkeypatch.setattr("dreamcatcher.cli.request_agent_work_retry", refuse_retry)

    assert main(argv=["retry", "GH13"]) == 1
    assert capsys.readouterr().err == "assignment record is read-only\n"


@pytest.mark.parametrize("command", ["retry", "stop", "cancel", "view", "feed"])
def test_an_issue_with_more_than_one_piece_of_work_asks_which(
    monkeypatch, watching, capsys, command
):
    directory = write_conversation(
        state=watching, issue=13, at=PINNED - timedelta(days=1)
    )
    write_faulted_rounds(directory=directory)
    monkeypatch.chdir(watching.root)

    assert main(argv=[command, "GH13"]) == 1

    assert capsys.readouterr() == (
        "",
        "GH13 has more than one piece of agent work. Run one of these:\n"
        f"  dreamcatcher {command} {directory.name}\n"
        f"  dreamcatcher {command} {ASSIGNMENT_ID}\n",
    )
    assert not list(watching.work.glob("*/rounds/*/stop-request"))
    assert not list(watching.work.glob("*/retry-request.json"))
    assert not list(watching.work.glob("*/ended.json"))


def test_an_identifier_selects_its_work_when_the_issue_has_more(
    monkeypatch, watching, capsys
):
    write_conversation(state=watching, issue=13, at=PINNED - timedelta(days=1))
    monkeypatch.chdir(watching.root)

    assert main(argv=["stop", ASSIGNMENT_ID]) == 0

    assert f"Requested a stop for {ASSIGNMENT_ID} round 1." in capsys.readouterr().out


def test_retry_reaches_an_older_conversation_in_fault_after_a_label_switch(
    monkeypatch, watching, capsys
):
    older, newer = write_switched_conversations(state=watching)
    write_faulted_rounds(directory=watching.work / older)
    monkeypatch.chdir(watching.root)

    assert main(argv=["retry", older]) == 0

    assert (watching.work / older / "retry-request.json").is_file()
    assert not (watching.work / newer / "retry-request.json").exists()
    assert f"{older} can run again" in capsys.readouterr().out


def test_retry_refuses_ended_work_whose_last_rounds_errored(
    monkeypatch, faulted, capsys
):
    assignment = read_newest_work(
        state=faulted, issue=13, kind=AgentWorkKind.ASSIGNMENT
    )
    end_agent_work(work=assignment, reason=AgentWorkEndReason.CANCELLED, at=PINNED)
    monkeypatch.chdir(faulted.root)

    assert main(argv=["retry", "GH13"]) == 1

    assert capsys.readouterr().err == f"{ASSIGNMENT_ID} is not in fault.\n"
    assert not (faulted.work / ASSIGNMENT_ID / "retry-request.json").exists()


@pytest.mark.parametrize("write_work", [write_conversation, write_campaign])
def test_cancel_refuses_work_that_is_not_an_assignment(
    monkeypatch, tmp_path, capsys, write_work
):
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    identifier = write_work(state=state, issue=13).name
    monkeypatch.chdir(tmp_path)

    assert main(argv=["cancel", "GH13"]) == 1

    assert capsys.readouterr().err == f"{identifier} is not an assignment.\n"
    assert not (state.work / identifier / "ended.json").exists()
