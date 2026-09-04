import json
import os
import sys
from contextlib import suppress

import psutil
import pytest
from clocks import PINNED, Ticking
from conftest import (
    CONFIG_HEAD,
    FILED,
    LABEL,
    LATER,
    REPOSITORY,
    SMITH_CLAUDE,
    SMITH_CODEX,
    git,
    gone,
    listing,
)
from fakes import Line
from records import write_round, write_session

from dreamcatcher.commands import spawn
from dreamcatcher.config import CONFIG_NAME, Harness
from dreamcatcher.daemon import Daemon
from dreamcatcher.errors import ReportableError
from dreamcatcher.rounds import Ending, RoundRecord
from dreamcatcher.state import Candidate, LastTick, StateDirectory, Waiting

KEY = "GH13-20260819-184158"

# What every round the tests here write down says woke it.
CAUSE = "dispatched"

# How long a scripted harness waits after its first line, so a round the daemon
# launched is certainly still running at the next tick. The waits these tests
# give the daemon take no real time, so its ticks are milliseconds apart.
STILL_RUNNING = 30

# The key of the session that a dispatch at the pinned time cuts for issue 8.
DISPATCHED_KEY = "GH8-20260819-184158"


@pytest.fixture
def left_running(tmp_path):
    """A process standing in for a round that outlived the daemon that ran it."""
    child = spawn(sys.executable, "-c", "import time; time.sleep(60)", cwd=tmp_path)
    yield child
    # Whatever a test left of it, and never through the tool's own teardown:
    # that signals a process group, which a test may already have emptied.
    with suppress(OSError):
        child.process.kill()
    child.process.wait()


@pytest.fixture
def alone(fake, stand_ins, monkeypatch):
    """Return a factory installing these stand-ins and nothing else at all.

    A harness the developer installed for their own use sits on the PATH of
    the machine the suite runs on, and would answer a startup check that a
    test means to fail. So the PATH holds the stand-ins alone.
    """

    def install(*programs: str) -> None:
        for program in programs:
            fake(program)
        monkeypatch.setenv("PATH", str(stand_ins))

    return install


class Interrupting:
    """A wait that lets the daemon tick, then interrupts it like a user would.

    The settle runs before each wait is counted, so a test that needs the round
    a tick launched to have finished waits for it there.
    """

    def __init__(self, ticks: int, settle=lambda: None) -> None:
        self.ticks = ticks
        self.settle = settle
        self.waited: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.settle()
        self.waited.append(seconds)
        if len(self.waited) == self.ticks:
            raise KeyboardInterrupt


def idling(root, ticks: int = 2) -> tuple[Daemon, Interrupting, Ticking]:
    waiting = Interrupting(ticks)
    ticking = Ticking(step=300)
    return Daemon(root, Harness.CLAUDE, clock=ticking, wait=waiting), waiting, ticking


def settling(root, ticks: int = 1) -> Daemon:
    """A daemon that lets each round it launches finish before the next tick.

    A round the daemon still holds is ended as the run goes down, so a test
    that reads what a round wrote lets the round finish while the run is still
    going.
    """
    daemon, _, _ = idling(root, ticks)

    def settle() -> None:
        for running in list(daemon.rounds.values()):
            running.wait()

    daemon.wait = Interrupting(ticks, settle)
    return daemon


def test_the_daemon_ticks_on_the_interval_until_the_user_interrupts(
    watched, harnesses, gh
):
    daemon, waiting, _ = idling(watched)

    daemon.run()

    assert waiting.waited == [300, 300]


def test_every_tick_records_when_it_ran(watched, harnesses, gh):
    daemon, _, ticking = idling(watched)

    daemon.run()

    recorded = daemon.state.last_tick.read_text(encoding="utf-8")
    assert len(ticking.readings) == 2
    assert LastTick.model_validate_json(recorded).at == ticking.readings[-1]


def test_the_daemon_bootstraps_the_state_directory_and_releases_the_lock(
    watched, harnesses, gh
):
    daemon, _, _ = idling(watched)

    daemon.run()

    assert (daemon.state.path / ".gitignore").exists()
    assert not daemon.state.lock.exists()


def test_a_second_daemon_refuses_while_the_first_holds_the_repo(watched, harnesses, gh):
    daemon, _, _ = idling(watched)
    daemon.state.bootstrap()
    daemon.state.lock.write_text(f"{os.getpid()}\n", encoding="utf-8")

    with pytest.raises(ReportableError, match=f"pid {os.getpid()}"):
        daemon.run()


def test_the_daemon_runs_the_harness_it_was_given(watched):
    assert Daemon(watched, Harness.CODEX).harness is Harness.CODEX


def test_a_checkout_with_no_config_names_the_file_it_needs(repo):
    with pytest.raises(ReportableError, match=CONFIG_NAME):
        Daemon(repo, Harness.CLAUDE)


def test_a_directory_that_is_not_a_repository_is_refused(tmp_path):
    with pytest.raises(ReportableError, match="main checkout"):
        Daemon(tmp_path, Harness.CLAUDE)


def test_a_linked_worktree_is_refused(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

    with pytest.raises(ReportableError, match="main checkout"):
        Daemon(tmp_path, Harness.CLAUDE)


def test_the_state_directory_sits_in_the_checkout(watched):
    daemon = Daemon(watched, Harness.CLAUDE)

    assert daemon.state == StateDirectory(watched)


def test_a_run_refuses_when_a_harness_it_could_dispatch_to_is_not_installed(
    watched, alone
):
    alone("claude")
    daemon, _, _ = idling(watched)

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        daemon.run()


def test_a_run_refuses_when_the_harness_it_was_named_is_not_installed(repo, alone):
    (repo / CONFIG_NAME).write_text(CONFIG_HEAD + SMITH_CLAUDE, encoding="utf-8")
    alone("claude")

    with pytest.raises(ReportableError, match="codex is not on the PATH"):
        Daemon(repo, Harness.CODEX, wait=Interrupting(1)).run()


def test_a_round_the_daemon_before_this_one_left_running_is_ended(
    watched, harnesses, gh, left_running
):
    directory = write_session(StateDirectory(watched), KEY, 13)
    write_round(
        directory, 1, RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE)
    )
    daemon, _, _ = idling(watched)

    daemon.run()

    assert gone(left_running.pid)


def test_a_round_that_recorded_an_ending_is_left_running_by_the_sweep(
    watched, harnesses, gh, left_running
):
    directory = write_session(StateDirectory(watched), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED,
            pid=left_running.pid,
            cause=CAUSE,
            ending=Ending(at=PINNED, status=0),
        ),
    )
    daemon, _, _ = idling(watched)

    daemon.run()

    assert psutil.pid_exists(left_running.pid)


def configure(root, head: str = CONFIG_HEAD) -> None:
    """Write a config for that checkout, with this ahead of its one mapping."""
    (root / CONFIG_NAME).write_text(head + SMITH_CLAUDE + SMITH_CODEX, encoding="utf-8")


def held(daemon) -> str:
    """Why the daemon's most recent tick launched nothing at all."""
    hold = recorded(daemon).hold
    assert hold is not None
    return hold


def recorded(daemon) -> LastTick:
    """What the daemon's most recent tick wrote down."""
    return LastTick.model_validate_json(
        daemon.state.last_tick.read_text(encoding="utf-8")
    )


@pytest.fixture
def gh(fake):
    """A gh that knows the repository and offers no labelled issue at all."""
    stand_in = fake("gh")
    stand_in.replies(json.dumps({"nameWithOwner": REPOSITORY}), to="repo view")
    stand_in.replies("[]", to="issue list")
    stand_in.replies(
        json.dumps({"closedByPullRequestsReferences": []}), to="issue view"
    )
    stand_in.replies("[]", to="api")
    return stand_in


@pytest.fixture
def offered(gh):
    """That gh, now offering one labelled issue nothing stands in the way of."""
    gh.replies(listing((8, FILED)), to="issue list")
    return gh


@pytest.fixture
def dispatching(cloned, offered, harnesses):
    """A checkout that a run can carry a labelled issue to a first round from."""
    configure(cloned)
    harnesses["claude"].streams([Line("what the round said\n")])
    return cloned


def test_a_tick_dispatches_the_oldest_issue_nothing_stands_in_the_way_of(
    dispatching, harnesses
):
    daemon = settling(dispatching)

    daemon.run()

    session = daemon.state.sessions / DISPATCHED_KEY
    assert (daemon.state.worktrees / DISPATCHED_KEY / "README.md").exists()
    assert (session / "session.json").exists()
    assert recorded(daemon).dispatched == DISPATCHED_KEY
    assert (
        harnesses["claude"].calls[0].directory
        == (daemon.state.worktrees / DISPATCHED_KEY).resolve()
    )


def test_a_dispatched_round_records_what_caused_it_and_what_it_said(dispatching):
    daemon = settling(dispatching)

    daemon.run()

    written = daemon.state.sessions / DISPATCHED_KEY / "rounds" / "1"
    assert (
        RoundRecord.model_validate_json(
            (written / "round.json").read_text(encoding="utf-8")
        ).cause
        == "dispatched"
    )
    assert "what the round said" in (written / "feed.txt").read_text(encoding="utf-8")


def test_a_tick_launches_one_round_and_leaves_the_rest_in_the_queue(
    dispatching, offered
):
    configure(dispatching, "max_agents = 2\n\n")
    offered.replies(listing((8, FILED), (9, LATER)), to="issue list")
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).candidates == [
        Candidate(issue=8, label=LABEL),
        Candidate(issue=9, label=LABEL),
    ]
    assert recorded(daemon).dispatched == DISPATCHED_KEY
    assert not (daemon.state.worktrees / "GH9-20260819-184158").exists()


def test_a_second_tick_judges_a_dispatched_issue_handled(dispatching):
    configure(dispatching, "max_agents = 2\n\n")
    daemon, _, _ = idling(dispatching, ticks=2)

    daemon.run()

    assert recorded(daemon).dispatched is None
    assert recorded(daemon).candidates == [
        Candidate(issue=8, label=LABEL, reason="a session of this run is working on it")
    ]


def test_a_tick_at_the_cap_spends_no_github_call(dispatching, offered, harnesses):
    harnesses["claude"].streams([Line("still working\n")], delay=STILL_RUNNING)
    daemon, _, _ = idling(dispatching, ticks=2)

    daemon.run()

    assert recorded(daemon).hold == "at cap: 1 rounds running"
    assert [call.arguments[:2] for call in offered.calls] == [
        ["repo", "view"],
        ["issue", "list"],
        ["issue", "view"],
        ["api", f"repos/{REPOSITORY}/issues/8/dependencies/blocked_by"],
    ]


def test_a_tick_with_nothing_eligible_dispatches_nothing(dispatching, offered):
    offered.replies(json.dumps([{"number": 7, "state": "open"}]), to="api")
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).dispatched is None
    assert recorded(daemon).candidates == [
        Candidate(issue=8, label=LABEL, reason="blocked by GH7")
    ]
    assert not daemon.state.worktrees.exists()


def test_a_tick_whose_listing_failed_records_what_it_could_not_read(
    dispatching, offered
):
    offered.fails("gh: could not connect to github.com", to="issue list")
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert "could not connect" in held(daemon)
    assert recorded(daemon).candidates == []


def test_a_tick_that_could_not_dispatch_records_the_failure_and_ticks_again(
    dispatching,
):
    # A file where every worktree goes, so no dispatch can ever cut one.
    state = StateDirectory(dispatching)
    state.path.mkdir(parents=True)
    state.worktrees.write_text("something else is here\n", encoding="utf-8")
    daemon, waiting, _ = idling(dispatching, ticks=2)

    daemon.run()

    assert waiting.waited == [300, 300]
    assert "git worktree add" in held(daemon)
    assert recorded(daemon).dispatched is None


def test_a_run_that_cannot_be_told_which_repository_this_is_refuses(
    cloned, gh, harnesses
):
    configure(cloned)
    gh.fails("gh: no such remote", to="repo view")

    with pytest.raises(ReportableError, match="cannot tell which repository"):
        Daemon(cloned, Harness.CLAUDE, wait=Interrupting(1)).run()


def test_the_daemon_ends_the_rounds_it_holds_as_it_goes_down(dispatching, harnesses):
    harnesses["claude"].streams([Line("still working\n")], delay=STILL_RUNNING)
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    running = daemon.rounds[DISPATCHED_KEY]
    assert not running.is_alive
    assert gone(running.child.pid)


def test_a_round_that_failed_lately_holds_every_launch(dispatching):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED,
            pid=1,
            cause=CAUSE,
            ending=Ending(at=PINNED.replace(minute=35), status=1),
        ),
    )
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert held(daemon) == (
        "the last round failed (exit 1) — next attempt at 18:50 UTC"
    )
    assert recorded(daemon).dispatched is None
    assert not (daemon.state.worktrees / DISPATCHED_KEY).exists()


def test_a_round_that_failed_long_enough_ago_holds_nothing(dispatching):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED,
            pid=1,
            cause=CAUSE,
            ending=Ending(at=PINNED.replace(hour=18, minute=0), status=1),
        ),
    )
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).dispatched == DISPATCHED_KEY


def test_a_round_that_ended_well_holds_nothing(dispatching):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED, pid=1, cause=CAUSE, ending=Ending(at=PINNED, status=0)
        ),
    )
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).dispatched == DISPATCHED_KEY


def test_a_session_whose_last_round_was_interrupted_reads_as_waiting(
    dispatching, left_running
):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    write_round(
        directory, 1, RoundRecord(started=PINNED, pid=left_running.pid, cause=CAUSE)
    )
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).waiting == [
        Waiting(session=KEY, issue=13, reason="the last round was interrupted")
    ]


def test_a_session_whose_last_round_failed_reads_as_waiting_with_its_status(
    dispatching,
):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED,
            pid=1,
            cause=CAUSE,
            ending=Ending(at=PINNED.replace(hour=18, minute=0), status=2),
        ),
    )
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).waiting == [
        Waiting(session=KEY, issue=13, reason="the last round failed (exit 2)")
    ]


def test_a_session_the_daemon_is_running_a_round_for_is_not_waiting(
    dispatching, harnesses
):
    configure(dispatching, "max_agents = 2\n\n")
    harnesses["claude"].streams([Line("still working\n")], delay=STILL_RUNNING)
    daemon, _, _ = idling(dispatching, ticks=2)

    daemon.run()

    # The round the daemon held recorded no ending, so the session would have
    # read as interrupted had the daemon not been running it.
    written = daemon.state.sessions / DISPATCHED_KEY / "rounds" / "1" / "round.json"
    assert (
        RoundRecord.model_validate_json(written.read_text(encoding="utf-8")).ending
        is None
    )
    assert recorded(daemon).waiting == []


def test_a_session_whose_last_round_ended_well_is_not_waiting(dispatching):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    write_round(
        directory,
        1,
        RoundRecord(
            started=PINNED, pid=1, cause=CAUSE, ending=Ending(at=PINNED, status=0)
        ),
    )
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).waiting == []


def test_a_session_that_has_run_no_round_at_all_waits_for_its_first(dispatching):
    write_session(StateDirectory(dispatching), KEY, 13)
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert recorded(daemon).waiting == [
        Waiting(session=KEY, issue=13, reason="no round has run yet")
    ]


def test_a_dispatch_whose_round_will_not_start_leaves_no_session_behind(dispatching):
    # A file where the session's rounds go, so no round can record its start.
    occupied = StateDirectory(dispatching).sessions / DISPATCHED_KEY / "rounds"
    occupied.parent.mkdir(parents=True)
    occupied.write_text("something else is here\n", encoding="utf-8")
    daemon, _, _ = idling(dispatching, ticks=1)

    daemon.run()

    assert "cannot write" in held(daemon)
    assert recorded(daemon).candidates == [Candidate(issue=8, label=LABEL)]
    assert not (daemon.state.worktrees / DISPATCHED_KEY).exists()
    branch = f"dreamcatcher-{DISPATCHED_KEY}"
    assert git("branch", "--list", branch, cwd=dispatching) == ""


def test_a_run_that_cannot_read_a_session_refuses_to_start(dispatching):
    directory = write_session(StateDirectory(dispatching), KEY, 13)
    (directory / "session.json").write_text("{}", encoding="utf-8")
    daemon, _, _ = idling(dispatching, ticks=1)

    with pytest.raises(ReportableError, match=r"session\.json is not valid"):
        daemon.run()


def test_a_session_that_goes_bad_under_a_running_daemon_costs_one_tick(dispatching):
    # The startup sweep read this session, so only a tick meets it broken.
    daemon, _, _ = idling(dispatching)
    directory = write_session(daemon.state, KEY, 13)
    (directory / "session.json").write_text("{}", encoding="utf-8")

    daemon.tick(REPOSITORY)

    assert "session.json is not valid" in held(daemon)
    assert recorded(daemon).candidates == []
