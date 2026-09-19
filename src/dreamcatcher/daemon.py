"""Run the foreground daemon for one Dreamcatcher instance."""

from __future__ import annotations

import sys
from contextlib import suppress
from time import sleep
from typing import TYPE_CHECKING

from dreamcatcher import teardown
from dreamcatcher.agent_assignments import read_agent_assignments
from dreamcatcher.agent_rounds import record_agent_round_interruption
from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.commands import locate_program
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.github import (
    UnknownGitHubResponse,
    identify_github_account,
    identify_github_repository,
)
from dreamcatcher.harnesses import HARNESS_ADAPTERS
from dreamcatcher.lock import hold_daemon_lock
from dreamcatcher.scheduler import AgentWorkScheduler, InvalidSchedulerRecordError
from dreamcatcher.state import StateDirectory
from dreamcatcher.words import describe_time

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from dreamcatcher.agent_rounds import AgentRound


def _write_output(*, line: str) -> None:
    """Write and flush one line, escaped for the stream that receives it."""
    try:
        encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_line, flush=True)
    except (OSError, UnicodeError) as error:
        raise ReportableError("Could not write daemon output.") from error


class DreamcatcherDaemon:
    """The foreground process watching one repo.

    The clock and the wait are the daemon's own, so a test can pin the time and
    end the loop.
    """

    def __init__(
        self,
        *,
        root: Path,
        harness: AgentHarness,
        clock: Callable[[], datetime] = read_current_time,
        wait: WaitForSeconds = sleep,
    ) -> None:
        """Set the daemon up for the repo checked out at root."""
        if not (root / ".git").is_dir():
            raise ReportableError(
                f"Start dreamcatcher from a repository's main checkout. "
                f"{root} is not one."
            )
        self.harness = harness
        self.config = read_dreamcatcher_config(root=root)
        self.state = StateDirectory(root=root)
        self.clock = clock
        self.wait = wait
        # The rounds this daemon is running, by the identifier of the assignment each
        # belongs to. They are what the cap counts, and what the daemon ends as
        # it goes down.
        self.rounds: dict[str, AgentRound] = {}

    def run(self) -> None:
        """Hold the repo and tick until the user interrupts.

        Everything a run cannot do without is settled before the loop: the
        harness CLIs, the state directory, the repository's name, the account
        gh is signed in as, the lock, and the assignments the sweep reads. A run
        refuses when any of those will not answer, rather than starting a loop
        that could never dispatch. Once the loop is going, a tick that fails
        reports the failure and the next tick tries again. An invalid scheduler
        record ends the run because retrying cannot change the document it reads.

        The repository and the account are read here and nowhere else. Neither
        can change while the daemon holds the repo, a run that cannot name the
        repository dispatches nothing, and the relay reads every post against
        the account before the marker tells the user's posts from the
        assignment's own.
        """
        self._locate_harnesses()
        self.state.bootstrap()
        repository = _require_known_github_value(
            value=identify_github_repository(root=self.state.root),
            question="which repository this is",
        )
        write_text(text=f"{repository}\n", path=self.state.repository)
        account = _require_known_github_value(
            value=identify_github_account(),
            question="which account gh is signed in as",
        )
        scheduler = AgentWorkScheduler(
            repository=repository,
            account=account,
            config=self.config,
            state=self.state,
            harness=self.harness,
            clock=self.clock,
            rounds=self.rounds,
        )
        with hold_daemon_lock(path=self.state.lock):
            self._sweep_orphans()
            at = self.clock()
            _write_output(line=f"{describe_time(at=at)}  dreamcatcher is running")
            try:
                with suppress(KeyboardInterrupt):
                    while True:
                        self.run_scheduler_cycle(scheduler=scheduler, at=at)
                        self.wait(self.config.interval)
                        at = self.clock()
            finally:
                # Rounds die with the daemon by design, so this happens however
                # the run ends: on the user's interrupt, and on a failure the
                # daemon could not carry on from. A round that already ended
                # keeps the ending it recorded for itself.
                for agent_round in self.rounds.values():
                    agent_round.stop()

    def run_scheduler_cycle(
        self, *, scheduler: AgentWorkScheduler, at: datetime
    ) -> None:
        """Run one scheduler tick, then record and report its result.

        A tick that failed reports the evidence and the next tick tries again,
        rather than the daemon ending and leaving the assignments it holds to
        nobody. The last complete scheduler record stays in place.

        Writing that evidence down is the exception. A daemon that cannot write
        `scheduler.json` has no way left to say anything at all, so that
        failure ends the run with a message the user can act on, and the rounds
        it was holding end with it.
        """
        try:
            scheduler_record = scheduler.tick(at=at)
        except InvalidSchedulerRecordError:
            raise
        except ReportableError as failure:
            reason = " ".join(str(failure).split())
            _write_output(line=f"{describe_time(at=at)}  held: {reason}")
            return
        write_json(document=scheduler_record, path=self.state.scheduler_record)
        if scheduler_record.launched is not None:
            outcome_description = f"launched round for {scheduler_record.launched}"
        elif scheduler_record.hold is not None:
            outcome_description = f"held: {' '.join(scheduler_record.hold.split())}"
        else:
            outcome_description = "nothing launched"
        _write_output(
            line=(f"{describe_time(at=scheduler_record.at)}  {outcome_description}")
        )

    def _locate_harnesses(self) -> None:
        """Refuse the run when a harness it could dispatch to is not installed.

        Every harness a route can settle a label on is looked up, not just
        the one the run named, because a label carrying one harness block runs
        on that harness whatever the run named.
        """
        for harness in sorted({self.harness, *self.config.routed_harnesses}):
            locate_program(program=HARNESS_ADAPTERS[harness].program)

    def _sweep_orphans(self) -> None:
        """End whatever a daemon that ran before this one left running.

        Rounds die with the daemon that started them, so a round still running
        here means the daemon that started it went down without ending it,
        which a crash or a kill does. A round whose record says how it ended is
        over and is left alone. Every other round is ended, and ending a round
        that has already gone does nothing, so nothing here has to ask whether
        one has. Its record is then reconciled as interrupted, which a later
        tick recovers.

        The pid is the one the record kept, and the operating system was free
        to give it to somebody else once the daemon that recorded it died.
        Ending it reaches that pid's own process group, and a pid handed on to
        a stranger is almost never a group of its own, so it names no group and
        nothing happens. That leaves a window, and it is accepted, as the same
        window is where the tool ends its own rounds.

        Windows cannot reach this at all: a round there sits in a job that
        empties itself when the daemon's last handle on it closes, so no round
        outlives its daemon and there is never anything to end.
        """
        for assignment in read_agent_assignments(state=self.state):
            for record in assignment.rounds:
                if record.ending is None:
                    teardown.end(pid=record.pid)
                    record_agent_round_interruption(
                        record=record,
                        path=assignment.compose_round_paths(
                            number=record.number
                        ).record,
                    )


def _require_known_github_value(
    *, value: str | UnknownGitHubResponse, question: str
) -> str:
    """Return what gh named, or refuse the run saying what it could not tell."""
    if isinstance(value, UnknownGitHubResponse):
        raise ReportableError(f"dreamcatcher cannot tell {question}: {value.reason}")
    return value
