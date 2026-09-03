from importlib.metadata import version

import pytest

from dreamcatcher.cli import main
from dreamcatcher.config import Harness
from dreamcatcher.daemon import Daemon


@pytest.fixture
def started(monkeypatch):
    """Return the daemons a run started, with the tick loop held back."""
    daemons = []
    monkeypatch.setattr(Daemon, "run", lambda daemon: daemons.append(daemon))
    return daemons


def test_version_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == version("dreamcatcher")


def test_scry_is_not_implemented_yet(capsys):
    assert main(["scry"]) == 1
    assert "scry" in capsys.readouterr().err


def test_a_bare_invocation_asks_for_a_verb(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([])

    assert exit_info.value.code == 2
    assert "verb" in capsys.readouterr().err


def test_run_starts_a_daemon_on_the_current_directory(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(["run", "--harness", "claude"]) == 0
    assert started[0].state.root == watched
    assert started[0].harness is Harness.CLAUDE


def test_the_harness_flag_says_what_to_run_rounds_with(monkeypatch, watched, started):
    monkeypatch.chdir(watched)

    assert main(["run", "--harness", "codex"]) == 0
    assert started[0].harness is Harness.CODEX


def test_a_run_with_no_harness_asks_for_one(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["run"])

    assert exit_info.value.code == 2
    assert "--harness" in capsys.readouterr().err


def test_a_harness_that_does_not_exist_is_refused(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--harness", "cloud"])

    assert exit_info.value.code == 2
    complaint = capsys.readouterr().err
    assert "cloud" in complaint
    assert all(harness in complaint for harness in Harness)


def test_a_failure_the_user_must_read_is_a_message_not_a_traceback(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)

    assert main(["run", "--harness", "claude"]) == 1
    assert "main checkout" in capsys.readouterr().err


def test_a_write_the_daemon_cannot_make_is_a_message_not_a_traceback(
    monkeypatch, watched, capsys
):
    monkeypatch.chdir(watched)
    (watched / ".dreamcatcher").write_text("not a directory\n", encoding="utf-8")

    assert main(["run", "--harness", "claude"]) == 1
    assert "cannot write" in capsys.readouterr().err
