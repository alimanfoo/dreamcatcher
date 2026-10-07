"""Run the foreground daemon for one dreamcatcher instance."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from time import sleep
from typing import TYPE_CHECKING

from dreamcatcher import teardown
from dreamcatcher.agent_assignments import read_assignments
from dreamcatcher.agent_rounds import (
    record_agent_round_interruption,
    record_agent_round_stop,
)
from dreamcatcher.clock import WaitForSeconds, read_current_time
from dreamcatcher.config import AgentHarness, read_dreamcatcher_config
from dreamcatcher.daemon_runs import DaemonRunRecord
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import require_main_checkout
from dreamcatcher.github import require_github_identity
from dreamcatcher.harnesses import locate_harnesses
from dreamcatcher.issue_conversations import read_conversations
from dreamcatcher.lock import hold_daemon_lock
from dreamcatcher.scheduler import (
    DEFAULT_MAX_AGENTS,
    AssignmentScheduler,
    ConversationScheduler,
    InvalidSchedulerRecordError,
    Scheduler,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.version import DREAMCATCHER_VERSION
from dreamcatcher.words import describe_time

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime, tzinfo
    from pathlib import Path

    from dreamcatcher.agent_rounds import AgentRound
    from dreamcatcher.scheduler import SchedulerRecord

DEFAULT_INTERVAL_SECONDS = 120


def _write_output(*, line: str) -> None:
    """Write and flush one line, escaped for the stream that receives it."""
    try:
        encoding = sys.stdout.encoding or "utf-8"
        safe_line = line.encode(encoding, errors="backslashreplace").decode(encoding)
        print(safe_line, flush=True)
    except (OSError, UnicodeError) as error:
        raise ReportableError("Could not write daemon output.") from error


class DreamcatcherDaemon:
    """Run the foreground process that watches one repository.

    The clock and the wait are the daemon's own, so a test can pin the time and
    end the loop.
    """

    def __init__(
        self,
        *,
        root: Path,
        harness: AgentHarness,
        interval: int = DEFAULT_INTERVAL_SECONDS,
        max_agents: int = DEFAULT_MAX_AGENTS,
        zone: tzinfo | None = None,
    ) -> None:
        """Configure the daemon for the main checkout at root.

        Report times use the machine's local zone when zone is None.
        """
        require_main_checkout(root=root)
        self.harness = harness
        self.interval = interval
        self.max_agents = max_agents
        self.zone = zone
        self.config = read_dreamcatcher_config(root=root)
        self.state = StateDirectory(root=root)
        self.clock: Callable[[], datetime] = read_current_time
        self.wait: WaitForSeconds = sleep
        # The rounds this daemon is running, by their assignment or conversation
        # identifier. They are what the cap counts, and what the daemon ends as it
        # goes down.
        self.rounds: dict[str, AgentRound] = {}

    def run(self) -> None:
        """Hold the daemon lock and run scheduler cycles until interrupted.

        Everything a daemon run cannot do without is settled before the loop: the
        harness CLIs, the state directory, the repository's name, the account
        gh is signed in as, the lock, and the assignments the sweep reads. A daemon
        run refuses when any of those will not answer, rather than starting a loop
        that could never dispatch. Once the loop is going, a tick that fails
        reports the failure and the next tick tries again. An invalid scheduler
        record ends the daemon run because retrying cannot change the document it reads.
        A lost daemon lock ends it too, because another daemon may then hold the
        checkout.

        The repository and signed-in account are fixed for the daemon run. The account
        identifies user posts before the marker excludes the assignment's own
        posts.
        """
        # A label carrying one dispatch recipe runs on that harness whatever the
        # preference, so every harness a route can settle a label on must be there.
        locate_harnesses(harnesses={self.harness, *self.config.routed_harnesses})
        with hold_daemon_lock(path=self.state.lock) as daemon_lock:
            self.state.bootstrap()
            write_json(
                document=DaemonRunRecord(
                    pid=os.getpid(),
                    harness=self.harness,
                    version=DREAMCATCHER_VERSION,
                    max_agents=self.max_agents,
                    interval_seconds=self.interval,
                ),
                path=self.state.daemon_run_record,
            )
            identity = require_github_identity(root=self.state.root)
            write_text(text=f"{identity.repository}\n", path=self.state.repository)
            assignments = AssignmentScheduler(
                repository=identity.repository,
                account=identity.account,
                config=self.config,
                state=self.state,
                requested_harness=self.harness,
                clock=self.clock,
            )
            conversations = ConversationScheduler(
                repository=identity.repository,
                account=identity.account,
                config=self.config,
                state=self.state,
                requested_harness=self.harness,
                clock=self.clock,
            )
            scheduler = Scheduler(
                state=self.state,
                assignments=assignments,
                conversations=conversations,
                rounds=self.rounds,
                max_agents=self.max_agents,
            )
            self._sweep_orphans()
            at = self.clock()
            _write_output(
                line=f"{describe_time(at=at, zone=self.zone)}  dreamcatcher is running"
            )
            try:
                with suppress(KeyboardInterrupt):
                    while True:
                        self.run_scheduler_cycle(scheduler=scheduler, at=at)
                        self.wait(self.interval)
                        daemon_lock.ensure_held()
                        at = self.clock()
            finally:
                # Rounds die with the daemon by design, so this happens however
                # the daemon run ends: on the user's interrupt, and on a failure the
                # daemon could not carry on from. A round that already ended
                # keeps the ending it recorded for itself.
                for agent_round in self.rounds.values():
                    agent_round.end_for_daemon_shutdown()

    def run_scheduler_cycle(self, *, scheduler: Scheduler, at: datetime) -> None:
        """Run one scheduler tick, then persist and report its result.

        A failed tick reports the error and leaves the last complete scheduler
        record in place so that the next cycle can try again.

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
        marked interrupted so that a later scheduler cycle can recover it.

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
        agent_work = [
            *read_assignments(state=self.state),
            *read_conversations(state=self.state),
        ]
        for owner in agent_work:
            for record in owner.rounds:
                if record.ending is None:
                    teardown.end_process_tree(pid=record.pid)
                    paths = owner.compose_round_paths(number=record.number)
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
    """Say what the tick launched, then the cooldown, capacity and failures."""
    facts = [_describe_launches(identifiers=record.launched_agent_work_identifiers)]
    if record.cooldown is not None:
        facts.append(
            f"global cooldown ends {describe_time(at=record.cooldown.ends, zone=zone)}"
        )
    if is_at_capacity:
        facts.append("agent capacity full")
    facts.extend(" ".join(failure.split()) for failure in record.failures)
    return "; ".join(facts)


def _describe_launches(*, identifiers: list[str]) -> str:
    if not identifiers:
        return "nothing launched"
    round_noun = "round" if len(identifiers) == 1 else "rounds"
    return f"launched {round_noun} for {', '.join(identifiers)}"
