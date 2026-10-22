"""Run the foreground daemon for one dreamcatcher instance."""

from __future__ import annotations

import os
import signal
import sys
from contextlib import contextmanager, nullcontext, suppress
from time import sleep
from typing import TYPE_CHECKING

from dreamcatcher import teardown
from dreamcatcher.agent_rounds import (
    describe_round_launch_failure,
    record_agent_round_interruption,
    record_agent_round_stop,
)
from dreamcatcher.agent_work import read_agent_work
from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.daemon_runs import DaemonRunRecord, RecordedRoute
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import require_main_checkout
from dreamcatcher.github import require_github_identity
from dreamcatcher.harnesses import require_harnesses_on_path
from dreamcatcher.lock import hold_daemon_lock
from dreamcatcher.scheduler import (
    DEFAULT_MAX_AGENTS,
    InvalidSchedulerRecordError,
    Scheduler,
    SchedulingContext,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.version import DREAMCATCHER_VERSION
from dreamcatcher.words import describe_time

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from contextlib import AbstractContextManager
    from datetime import datetime, tzinfo
    from pathlib import Path
    from types import FrameType

    from dreamcatcher.agent_rounds import AgentRound
    from dreamcatcher.scheduler import SchedulerRecord

DEFAULT_INTERVAL_SECONDS = 120
_NO_COMPANION = nullcontext()

# The signals that end the daemon as Ctrl-C does: a kill, a shutdown, and on
# POSIX the hangup that closing its terminal sends. Windows has no hangup, and
# its Job Objects already end the harnesses of a daemon that dies.
_TERMINATION_SIGNALS = (
    (signal.SIGTERM,) if sys.platform == "win32" else (signal.SIGTERM, signal.SIGHUP)
)


def _write_output(*, line: str) -> None:
    """Write and flush one line, escaped for the stream that receives it."""
    try:
        encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_line, flush=True)
    except (OSError, UnicodeError) as error:
        raise ReportableError("Could not write daemon output.") from error


def _raise_interrupt(signal_number: int, frame: FrameType | None, /) -> None:
    """Raise an interrupt where the daemon is, as Ctrl-C does.

    The signal module calls this with positional arguments.
    """
    raise KeyboardInterrupt


@contextmanager
def _interrupt_on_termination_signals() -> Generator[None]:
    """Turn each termination signal into an interrupt, and then restore it.

    A signal that the daemon was started to ignore stays ignored, so a daemon
    started under nohup still outlives its terminal.
    """
    previous_handlers = {
        number: signal.signal(number, _raise_interrupt)
        for number in _TERMINATION_SIGNALS
        if signal.getsignal(number) is not signal.SIG_IGN
    }
    try:
        yield
    finally:
        for number, handler in previous_handlers.items():
            signal.signal(number, handler)


class DreamcatcherDaemon:
    """Run the foreground process that watches one repository.

    The clock and the wait are the daemon's own, so a test can pin the time and
    end the loop.
    """

    def __init__(
        self,
        *,
        root: Path,
        preferred_harness: AgentHarness,
        interval: int = DEFAULT_INTERVAL_SECONDS,
        max_agents: int = DEFAULT_MAX_AGENTS,
        zone: tzinfo | None = None,
    ) -> None:
        """Configure the daemon for the main checkout at root.

        Report times use the machine's local zone when zone is None.
        """
        require_main_checkout(root=root)
        self.preferred_harness = preferred_harness
        self.interval = interval
        self.max_agents = max_agents
        self.zone = zone
        self.config = read_dreamcatcher_config(root=root)
        self.state = StateDirectory(root=root)
        self.clock: Callable[[], datetime] = read_current_time
        self.wait: WaitForSeconds = sleep
        # The rounds this daemon is running, by their agent work identifier.
        # They are what the cap counts, and what the daemon ends as it goes
        # down.
        self.rounds: dict[str, AgentRound] = {}

    def run(self, *, companion: AbstractContextManager[None] = _NO_COMPANION) -> None:
        """Hold the daemon lock and run scheduler ticks until interrupted.

        Everything a daemon run cannot do without is settled before the loop: the
        harness CLIs, the state directory, the repository's name, the account
        gh is signed in as, the lock, and the agent work the sweep reads. A daemon
        run refuses when any of those will not answer, rather than starting a loop
        that could never dispatch. Once the loop is going, a tick that fails
        reports the failure and the next tick tries again. An invalid scheduler
        record ends the daemon run because retrying cannot change the document it reads.
        A lost daemon lock ends it too, because another daemon may then hold the
        checkout.

        The repository and signed-in account are fixed for the daemon run. The account
        identifies user posts before the marker excludes the agent's own posts.

        The companion starts after the daemon's startup checks pass and ends with the
        daemon.

        While the loop runs, a termination signal interrupts it as Ctrl-C does, so
        `kill`, a shutdown or a closed terminal ends the rounds as well.
        """
        # A label carrying one dispatch recipe runs on that harness whatever the
        # preference, so every harness a route can settle a label on must be there.
        require_harnesses_on_path(
            harnesses={self.preferred_harness, *self.config.routed_harnesses}
        )
        with hold_daemon_lock(path=self.state.lock) as daemon_lock:
            self.state.bootstrap()
            write_json(
                document=DaemonRunRecord(
                    pid=os.getpid(),
                    preferred_harness=self.preferred_harness,
                    version=DREAMCATCHER_VERSION,
                    max_agents=self.max_agents,
                    interval_seconds=self.interval,
                    routes=[
                        RecordedRoute(label=route.label, kind=route.kind)
                        for route in self.config.routes
                    ],
                ),
                path=self.state.daemon_run_record,
            )
            identity = require_github_identity(root=self.state.root)
            write_text(text=f"{identity.repository}\n", path=self.state.repository)
            scheduler = Scheduler(
                context=SchedulingContext(
                    repository=identity.repository,
                    account=identity.account,
                    config=self.config,
                    state=self.state,
                    clock=self.clock,
                ),
                preferred_harness=self.preferred_harness,
                rounds=self.rounds,
                max_agents=self.max_agents,
            )
            self._sweep_orphans()
            try:
                with (
                    suppress(KeyboardInterrupt),
                    _interrupt_on_termination_signals(),
                    companion,
                ):
                    at = self.clock()
                    _write_output(
                        line=(
                            f"{describe_time(at=at, zone=self.zone)}  "
                            f"dreamcatcher v{DREAMCATCHER_VERSION} is running"
                        )
                    )
                    while True:
                        self.run_scheduler_tick(scheduler=scheduler, at=at)
                        self.wait(self.interval)
                        daemon_lock.require_held()
                        at = self.clock()
            finally:
                # Rounds die with the daemon by design, so this happens however
                # the daemon run ends: on the user's interrupt, and on a failure the
                # daemon could not carry on from. A round that already ended
                # keeps the ending it recorded for itself.
                for agent_round in self.rounds.values():
                    agent_round.end_for_daemon_shutdown()

    def run_scheduler_tick(self, *, scheduler: Scheduler, at: datetime) -> None:
        """Run one scheduler tick, then persist and report its result.

        A failed tick reports the error and leaves the last complete scheduler
        record in place so that the next tick can try again.

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
            _write_output(
                line=f"{describe_time(at=at, zone=self.zone)}  update failed: {reason}"
            )
            return
        write_json(document=scheduler_record, path=self.state.scheduler_record)
        outcome = _describe_tick_outcome(
            record=scheduler_record,
            is_at_capacity=scheduler.is_at_capacity,
            zone=self.zone,
        )
        _write_output(
            line=f"{describe_time(at=scheduler_record.at, zone=self.zone)}  {outcome}"
        )

    def _sweep_orphans(self) -> None:
        """Terminate and reconcile rounds left running by an earlier daemon.

        A terminal record is left unchanged. A record with a pending stop
        request is marked stopped; every other record without an ending is
        marked interrupted so that a later scheduler tick gives its input
        again. A record with no process id ended before its harness was
        spawned, so there is nothing to terminate.

        The pid is the one the record kept, and the operating system was free
        to give it to somebody else once the daemon that recorded it died.
        Ending it reaches that pid's own process group, and a pid handed on to
        a stranger is almost never a group of its own, so it names no group and
        nothing happens. A reused pid that does lead a process group can cause
        this sweep to terminate an unrelated group. The record can be stale
        for the whole interval between daemon runs.

        Windows Job Objects empty when the earlier daemon closes its last
        handle, so termination there is already complete.
        """
        for work in read_agent_work(state=self.state):
            for record in work.rounds:
                if record.ending is None:
                    if record.pid is not None:
                        teardown.end_process_tree(pid=record.pid)
                    paths = work.compose_round_paths(number=record.number)
                    if paths.stop_request.is_file():
                        record_agent_round_stop(
                            record=record, path=paths.record, at=self.clock()
                        )
                    else:
                        record_agent_round_interruption(
                            record=record,
                            path=paths.record,
                        )


def _describe_tick_outcome(
    *, record: SchedulerRecord, is_at_capacity: bool, zone: tzinfo | None
) -> str:
    """Say what the tick launched, then the cooldown, capacity and failures.

    A round that errored during its preparation or startup is named with its
    reason among the failures.
    """
    facts = [_describe_launches(identifiers=record.launched_agent_work_identifiers)]
    if record.cooldown is not None:
        facts.append(
            f"global cooldown ends {describe_time(at=record.cooldown.ends, zone=zone)}"
        )
    if is_at_capacity:
        facts.append("agent capacity full")
    failures = [
        *record.failures,
        *(
            describe_round_launch_failure(
                agent_work_identifier=identifier,
                round_number=started_round.number,
                reason=started_round.launch_failure,
            )
            for identifier, started_round in record.started_rounds.items()
            if started_round.launch_failure is not None
        ),
    ]
    facts.extend(" ".join(failure.split()) for failure in failures)
    return "; ".join(facts)


def _describe_launches(*, identifiers: list[str]) -> str:
    if not identifiers:
        return "nothing launched"
    round_noun = "round" if len(identifiers) == 1 else "rounds"
    return f"launched {round_noun} for {', '.join(identifiers)}"
