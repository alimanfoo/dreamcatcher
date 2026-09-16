import os
from datetime import timedelta
from importlib.metadata import version

import pytest
from clocks import PINNED
from records import write_agent_assignment, write_feed, write_round

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    RoundPurpose,
    compose_agent_round_ending,
)
from dreamcatcher.cli import main
from dreamcatcher.config import Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.documents import write_text
from dreamcatcher.feed import Line
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"


@pytest.fixture
def watching(tmp_path):
    """A checkout a daemon has watched, holding one assignment with a live round."""
    state = StateDirectory(root=tmp_path)
    state.bootstrap()
    write_text(text=f"{os.getpid()}\n", path=state.lock)
    directory = write_agent_assignment(state=state, identifier=ASSIGNMENT_ID, issue=13)
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=1, purpose=RoundPurpose.IMPLEMENT
        ),
    )
    write_feed(
        directory=directory, number=1, lines=[Line(at=PINNED, text="[Bash] pytest")]
    )
    return state


@pytest.fixture
def started(monkeypatch):
    """Return the daemons a run started, with the tick loop held back."""
    daemons = []
    monkeypatch.setattr(Daemon, "run", lambda daemon: daemons.append(daemon))
    return daemons


def test_version_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == version("dreamcatcher")


def test_a_checkout_no_daemon_has_watched_has_nothing_to_show(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)

    assert main(argv=["board"]) == 1
    assert "nothing to show" in capsys.readouterr().err


def test_board_shows_every_assignment(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["board"]) == 0
    assert "agent working" in capsys.readouterr().out


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


def test_feed_shows_what_the_assignment_said(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)
    # A following view runs until the assignment has run its final round, so this
    # one is over before the view opens and the view never waits. An assignment's
    # rounds read back in the order they started, so the final round starts
    # after the first one rather than alongside it.
    later = PINNED + timedelta(minutes=1)
    write_round(
        directory=watching.assignments / ASSIGNMENT_ID,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=later,
            pid=1,
            purpose=RoundPurpose.WRAP_UP,
            ending=compose_agent_round_ending(at=later, status=0),
        ),
    )

    assert main(argv=["feed", "GH13"]) == 0
    assert "round 1: dispatched" in capsys.readouterr().out


def test_feed_naming_a_round_shows_that_rounds_feed(monkeypatch, watching, capsys):
    monkeypatch.chdir(watching.root)

    assert main(argv=["feed", "GH13", "--round", "1"]) == 0
    assert "round 1: dispatched" in capsys.readouterr().out


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


def test_the_board_takes_no_issue(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(argv=["board", "GH13"])

    assert exit_info.value.code == 2
    assert "GH13" in capsys.readouterr().err


@pytest.mark.parametrize("verb", ["run", "board", "assignment", "feed"])
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
    assert started[0].harness is Harness.CLAUDE


def test_the_harness_flag_says_what_to_run_rounds_with(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(argv=["run", "--harness", "codex"]) == 0
    assert started[0].harness is Harness.CODEX


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
    assert all(harness in complaint for harness in Harness)


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
