import os
import sys
from collections.abc import Sequence
from datetime import timedelta
from io import BytesIO, TextIOWrapper

import psutil
import pytest
from clocks import PINNED, Ticking
from conftest import (
    CONFIG_HEAD,
    POST_LIST_PATHS,
    POSTED_BY,
    REPOSITORY,
    SMITH_CLAUDE,
    configure,
    gone,
)
from fakes import Line
from records import write_agent_assignment, write_round

from dreamcatcher.agent_rounds import (
    AgentRoundPurpose,
    AgentRoundRecord,
    RoundOutcome,
    compose_agent_round_ending,
)
from dreamcatcher.config import CONFIG_NAME, AgentHarness
from dreamcatcher.daemon import Daemon
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.scheduler import GlobalCooldown, Scheduler, SchedulerRecord
from dreamcatcher.state import StateDirectory

ASSIGNMENT_ID = "GH13-20260819-184158"

# What every round the tests here write down says woke it.
PURPOSE = AgentRoundPurpose.IMPLEMENT

# How long a scripted harness waits after its first line, so a round the daemon
# launched is certainly still running at the next tick. The waits these tests
# give the daemon take no real time, so its ticks are milliseconds apart.
STILL_RUNNING = 30

# The identifier of the assignment that a dispatch cuts for issue 8.
DISPATCHED_ASSIGNMENT_ID = "GH8-20260819-184158"

# Where gh keeps the conversation on the pull request that the assignment on disk
# has open.
CONVERSATION = POST_LIST_PATHS["conversation"]


@pytest.fixture
def alone(fake, stand_ins, monkeypatch):
    """Return a factory installing these stand-ins and nothing else at all.

    A harness the developer installed for their own use sits on the PATH of
    the machine the suite runs on, and would answer a startup check that a
    test means to fail. So the PATH holds the stand-ins alone.
    """

    def install(*, programs: Sequence[str]) -> None:
        for program in programs:
            fake(program=program)
        monkeypatch.setenv("PATH", str(stand_ins))

    return install


class Interrupting:
    """A wait that lets the daemon tick, then interrupts it like a user would.

    The settle runs before each wait is counted, so a test that needs the round
    a tick launched to have finished waits for it there.
    """

    def __init__(self, *, ticks: int, settle=lambda: None) -> None:
        self.ticks = ticks
        self.settle = settle
        self.waited: list[float] = []

    def __call__(self, seconds: float, /) -> None:
        self.settle()
        self.waited.append(seconds)
        if len(self.waited) == self.ticks:
            raise KeyboardInterrupt


def idling(*, root, ticks: int = 2) -> tuple[Daemon, Interrupting, Ticking]:
    waiting = Interrupting(ticks=ticks)
    ticking = Ticking(step=300)
    return (
        Daemon(root=root, harness=AgentHarness.CLAUDE, clock=ticking, wait=waiting),
        waiting,
        ticking,
    )


def settling(*, root, ticks: int = 1) -> Daemon:
    """A daemon that lets each round it launches finish before the next tick.

    A round the daemon still holds is ended as the run goes down, so a test
    that reads what a round wrote lets the round finish while the run is still
    going.
    """
    daemon, _, _ = idling(root=root, ticks=ticks)

    def settle() -> None:
        for running in list(daemon.rounds.values()):
            running.wait()

    daemon.wait = Interrupting(ticks=ticks, settle=settle)
    return daemon


def test_the_daemon_ticks_on_the_interval_until_the_user_interrupts(
    watched, harnesses, gh
):
    daemon, waiting, _ = idling(root=watched)

    daemon.run()

    assert waiting.waited == [300, 300]


def test_the_daemon_reports_when_it_has_started_before_its_first_tick(
    watched, harnesses, gh, monkeypatch, capsys
):
    daemon, _, _ = idling(root=watched)

    def verify_report(*, scheduler, at):
        assert (
            capsys.readouterr().out == "2026-08-19T18:41:58Z  dreamcatcher is running\n"
        )
        raise KeyboardInterrupt

    monkeypatch.setattr(daemon, "tick", verify_report)
    daemon.run()


def test_the_daemon_flushes_every_report(watched, harnesses, gh, monkeypatch):
    daemon, _, _ = idling(root=watched, ticks=1)
    reports = []

    def report(line, /, *, flush):
        reports.append((line, flush))

    monkeypatch.setattr("builtins.print", report)
    daemon.run()

    assert reports == [
        ("2026-08-19T18:41:58Z  dreamcatcher is running", True),
        ("2026-08-19T18:41:58Z  nothing launched", True),
    ]


def test_a_tick_output_the_daemon_cannot_write_is_a_named_failure(
    watched, harnesses, gh, monkeypatch
):
    daemon, _, _ = idling(root=watched, ticks=1)
    writes = 0

    def fail_on_the_tick(_line, /, *, flush):
        nonlocal writes
        assert flush
        writes += 1
        if writes == 2:
            raise BrokenPipeError

    monkeypatch.setattr("builtins.print", fail_on_the_tick)

    with pytest.raises(ReportableError, match="Could not write daemon output"):
        daemon.run()

    assert daemon.state.scheduler_record.exists()


def test_every_tick_records_when_it_ran(watched, harnesses, gh, capsys):
    daemon, _, ticking = idling(root=watched)

    daemon.run()

    recorded = daemon.state.scheduler_record.read_text(encoding="utf-8")
    assert len(ticking.readings) == 2
    assert SchedulerRecord.model_validate_json(recorded).at == ticking.readings[-1]
    assert capsys.readouterr().out == (
        "2026-08-19T18:41:58Z  dreamcatcher is running\n"
        "2026-08-19T18:41:58Z  nothing launched\n"
        "2026-08-19T18:46:58Z  nothing launched\n"
    )


def test_a_successful_scheduler_tick_is_recorded_and_reported(
    watched, capsys, monkeypatch
):
    daemon, _, _ = idling(root=watched, ticks=1)
    scheduler = Scheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=daemon.config,
        state=daemon.state,
        harness=daemon.harness,
        clock=daemon.clock,
        rounds=daemon.rounds,
    )
    observed = SchedulerRecord(at=PINNED, launched=ASSIGNMENT_ID)

    def launch(*, at):
        assert at == PINNED
        return observed

    monkeypatch.setattr(scheduler, "tick", launch)

    daemon.tick(scheduler=scheduler, at=PINNED)

    assert recorded(daemon=daemon) == observed
    assert (
        capsys.readouterr().out
        == f"2026-08-19T18:41:58Z  launched round for {ASSIGNMENT_ID}\n"
    )


def test_the_daemon_bootstraps_the_state_directory_and_releases_the_lock(
    watched, harnesses, gh
):
    daemon, _, _ = idling(root=watched)

    daemon.run()

    assert (daemon.state.path / ".gitignore").exists()
    assert daemon.state.repository.read_text(encoding="utf-8") == f"{REPOSITORY}\n"
    assert not daemon.state.lock.exists()


def test_a_second_daemon_refuses_while_the_first_holds_the_repo(watched, harnesses, gh):
    daemon, _, _ = idling(root=watched)
    daemon.state.bootstrap()
    daemon.state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")

    with pytest.raises(ReportableError, match=f"pid {os.getpid()}"):
        daemon.run()


def test_the_daemon_runs_the_harness_it_was_given(watched):
    assert (
        Daemon(root=watched, harness=AgentHarness.CODEX).harness is AgentHarness.CODEX
    )


def test_a_checkout_with_no_config_names_the_file_it_needs(repo):
    with pytest.raises(ReportableError, match=CONFIG_NAME):
        Daemon(root=repo, harness=AgentHarness.CLAUDE)


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path):
    with pytest.raises(ReportableError, match="main checkout"):
        Daemon(root=tmp_path, harness=AgentHarness.CLAUDE)


def test_a_linked_worktree_is_refused(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="main checkout"):
        Daemon(root=tmp_path, harness=AgentHarness.CLAUDE)


def test_the_state_directory_sits_in_the_checkout(watched):
    daemon = Daemon(root=watched, harness=AgentHarness.CLAUDE)

    assert daemon.state == StateDirectory(root=watched)


def test_a_run_refuses_when_a_harness_it_could_dispatch_to_is_not_installed(
    watched, alone
):
    alone(programs=["claude"])
    daemon, _, _ = idling(root=watched)

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        daemon.run()


def test_a_run_refuses_when_the_harness_it_was_named_is_not_installed(repo, alone):
    (repo / CONFIG_NAME).write_text(CONFIG_HEAD + SMITH_CLAUDE, encoding="utf-8")
    alone(programs=["claude"])

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        Daemon(root=repo, harness=AgentHarness.CODEX, wait=Interrupting(ticks=1)).run()


def test_a_round_the_daemon_before_this_one_left_running_is_ended(
    watched, harnesses, gh, left_running
):
    directory = write_agent_assignment(
        state=StateDirectory(root=watched), identifier=ASSIGNMENT_ID, issue=13
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1, started=PINNED, pid=left_running.pid, purpose=PURPOSE
        ),
    )
    daemon, _, _ = idling(root=watched)

    daemon.run()

    assert gone(pid=left_running.pid)
    record = AgentRoundRecord.model_validate_json(
        (directory / "rounds" / "1" / "round.json").read_text(encoding="utf-8")
    )
    assert record.outcome is RoundOutcome.INTERRUPTED


def test_a_round_that_recorded_an_ending_is_left_running_by_the_sweep(
    watched, harnesses, gh, left_running
):
    directory = write_agent_assignment(
        state=StateDirectory(root=watched), identifier=ASSIGNMENT_ID, issue=13
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=left_running.pid,
            purpose=PURPOSE,
            ending=compose_agent_round_ending(at=PINNED, status=0),
        ),
    )
    daemon, _, _ = idling(root=watched)

    daemon.run()

    assert psutil.pid_exists(left_running.pid)


def held(*, daemon) -> str:
    """Why the daemon's most recent tick launched nothing at all."""
    hold = recorded(daemon=daemon).hold
    assert hold is not None
    return hold


def recorded(*, daemon) -> SchedulerRecord:
    """What the daemon's most recent tick wrote down."""
    return SchedulerRecord.model_validate_json(
        daemon.state.scheduler_record.read_text(encoding="utf-8")
    )


def test_a_tick_whose_listing_failed_records_what_it_could_not_read(
    dispatching, offered, capsys
):
    offered.fails(
        stderr="gh: could not connect to github.com\ngh: try again", to="issue list"
    )
    daemon, _, _ = idling(root=dispatching, ticks=1)

    daemon.run()

    assert "could not connect" in held(daemon=daemon)
    assert recorded(daemon=daemon).issue_observations == []
    output = capsys.readouterr().out
    assert output.startswith(
        "2026-08-19T18:41:58Z  dreamcatcher is running\n2026-08-19T18:41:58Z  held: "
    )
    assert output.endswith("gh: could not connect to github.com gh: try again\n")
    assert output.count("\n") == 2


def test_tick_output_escapes_text_the_stream_cannot_encode(
    dispatching, offered, harnesses, monkeypatch
):
    offered.fails(stderr="gh: wait — try again", to="issue list")
    daemon, _, _ = idling(root=dispatching, ticks=1)
    buffered = BytesIO()
    output = TextIOWrapper(buffered, encoding="ascii", newline="\n")
    monkeypatch.setattr(sys, "stdout", output)

    daemon.run()
    output.flush()

    assert b"gh: wait \\u2014 try again" in buffered.getvalue()


def test_a_tick_that_could_not_dispatch_records_the_failure_and_ticks_again(
    dispatching,
):
    # A file where every worktree goes, so no dispatch can ever cut one.
    state = StateDirectory(root=dispatching)
    state.path.mkdir(parents=True)
    state.worktrees.write_text("something else is here\n", encoding="utf-8")
    daemon, waiting, _ = idling(root=dispatching, ticks=2)

    daemon.run()

    assert waiting.waited == [300, 300]
    assert "git worktree add" in held(daemon=daemon)
    assert recorded(daemon=daemon).launched is None


def test_a_run_that_cannot_be_told_which_repository_this_is_refuses(
    cloned, gh, harnesses
):
    configure(root=cloned)
    gh.fails(stderr="gh: no such remote", to="repo view")

    with pytest.raises(ReportableError, match="cannot tell which repository"):
        Daemon(
            root=cloned, harness=AgentHarness.CLAUDE, wait=Interrupting(ticks=1)
        ).run()


def test_the_daemon_ends_the_rounds_it_holds_as_it_goes_down(dispatching, harnesses):
    harnesses["claude"].streams(
        lines=[Line(text="still working\n")], delay=STILL_RUNNING
    )
    daemon, _, _ = idling(root=dispatching, ticks=1)

    daemon.run()

    running = daemon.rounds[DISPATCHED_ASSIGNMENT_ID]
    assert not running.is_alive
    assert gone(pid=running.child.pid)


def test_a_run_that_cannot_read_an_assignment_refuses_to_start(dispatching):
    directory = write_agent_assignment(
        state=StateDirectory(root=dispatching), identifier=ASSIGNMENT_ID, issue=13
    )
    (directory / "assignment.json").write_text("{}", encoding="utf-8")
    daemon, _, _ = idling(root=dispatching, ticks=1)

    with pytest.raises(ReportableError, match=r"assignment\.json is not valid"):
        daemon.run()


def test_a_failed_tick_preserves_the_last_scheduler_record(dispatching, capsys):
    # The startup sweep read this assignment, so only a tick meets it broken.
    daemon, _, _ = idling(root=dispatching)
    previous = SchedulerRecord(
        at=PINNED,
        cooldown=GlobalCooldown(started=PINNED, ends=PINNED + timedelta(minutes=15)),
    )
    write_json(document=previous, path=daemon.state.scheduler_record)
    directory = write_agent_assignment(
        state=daemon.state, identifier=ASSIGNMENT_ID, issue=13
    )
    (directory / "assignment.json").write_text("{}", encoding="utf-8")

    scheduler = Scheduler(
        repository=REPOSITORY,
        account=POSTED_BY,
        config=daemon.config,
        state=daemon.state,
        harness=daemon.harness,
        clock=daemon.clock,
        rounds=daemon.rounds,
    )
    daemon.tick(scheduler=scheduler, at=daemon.clock())

    assert recorded(daemon=daemon) == previous
    output = capsys.readouterr().out
    assert "held:" in output
    assert "assignment.json is not valid" in output


def test_an_invalid_scheduler_record_ends_the_run(watched, harnesses, gh):
    daemon, _, _ = idling(root=watched)
    daemon.state.bootstrap()
    write_text(text="{}", path=daemon.state.scheduler_record)

    with pytest.raises(ReportableError, match=r"scheduler\.json is not valid"):
        daemon.run()


def test_a_run_that_cannot_be_told_which_account_gh_is_signed_in_as_refuses(
    cloned, gh, harnesses
):
    configure(root=cloned)
    gh.fails(stderr="gh: you are not logged in", to="api user")

    with pytest.raises(ReportableError, match="cannot tell which account"):
        Daemon(
            root=cloned, harness=AgentHarness.CLAUDE, wait=Interrupting(ticks=1)
        ).run()
