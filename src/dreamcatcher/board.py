"""What each assignment and each queued issue is doing, read off the disk.

The board answers "whose turn is it". Every assignment stands somewhere, and every
labelled issue the last tick weighed has a place in the queue.

Nothing here asks GitHub. What the daemon left behind is the whole story: the
lock says whether a daemon is running, the round records say what each assignment
has run, and `scheduler.json` says what the records alone cannot, which is
whatever the daemon had to ask GitHub to learn.

Nothing here renders anything either. A caller that has read the board shows
it.

Two things live here and they do different jobs. `_Look` reads and judges: it
takes one look at the directory and says where each assignment stands. `Board`,
`AgentAssignmentRow` and `QueuedIssue` are what it found, and they hold no directory
and read nothing, so a view renders one. That is why a look is not a board and
a board cannot refresh itself: a view that keeps up takes a new look, which is
one read of the lock and of the last tick and a fresh judgement of each assignment
against them.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dreamcatcher.agent_assignments import (
    AgentAssignment,
    read_agent_assignments,
    read_agent_assignments_for_issue,
)
from dreamcatcher.clock import now
from dreamcatcher.documents import read_json
from dreamcatcher.feed import Line, read_last_feed_line
from dreamcatcher.lock import read_daemon_pid
from dreamcatcher.scheduler import (
    NO_ROUND_HAS_RUN,
    AgentAssignmentObservation,
    IssueFactValue,
    SchedulerRecord,
    derive_assignment_fault,
    derive_issue_availability,
)
from dreamcatcher.state import (
    StateDirectory,
)
from dreamcatcher.words import describe_count, describe_span


class AgentAssignmentStanding(StrEnum):
    """Where an assignment stands: whether it is anyone's turn, and whose.

    The board sets its sections in these words, so the section a reader looks
    under and the standing an assignment is in are one thing. A view of one issue
    reads the standing rather than showing sections, and a following feed reads
    it to know when the assignment it is watching has nothing more to say.

    An assignment needs you when the daemon has nothing left to do for it: every
    round it has run finished, its pull request is open, and the agent has
    answered everything posted on it. The next move is the user's, and that
    move is to read the pull request.

    An assignment is working while a round of its own is running. It is waiting
    when it has a round to run that no daemon has launched yet. The board uses
    stuck as its temporary presentation of a fault after two consecutive
    errored rounds. A later global cooldown can clear that fault. An assignment
    is done once it has run the round that winds it up.
    """

    NEEDS_YOU = "needs you"
    WORKING = "agent working"
    WAITING = "waiting"
    STUCK = "stuck"
    DONE = "done"


@dataclass(frozen=True, kw_only=True)
class AgentAssignmentRow:
    """One assignment and what one look at the disk found it doing.

    The assignment is what the disk holds. The standing, the detail and the last
    output are what the look concluded about it, so a view shows them and
    nothing has to judge an assignment twice.

    The board holds one of these for every assignment, and a view of one issue
    holds one for each assignment at that issue. An issue dispatched three times
    has three assignments at one thing, and the newest of them reads first.

    The detail is what the row says beside the standing, in the words the disk
    put it in. A working assignment keeps its latest output separate so the view
    can set it apart from that status.
    """

    assignment: AgentAssignment
    standing: AgentAssignmentStanding
    detail: str
    last_output: str | None


@dataclass(frozen=True, kw_only=True)
class QueuedIssue:
    """A labelled issue the last tick weighed, and why it has not gone yet.

    An issue with nothing in its way is waiting its turn, and the reason is
    where in the queue that turn is.
    """

    issue: int
    label: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class Board:
    """Every assignment and every queued issue, as one look at the disk found them.

    The pid is the daemon holding this repo, and nothing holds it when no
    daemon is running. The tick is the last one a daemon wrote down, and a
    state directory none has ticked in has none.
    """

    at: datetime
    daemon_pid: int | None
    scheduler_record: SchedulerRecord | None
    rows: list[AgentAssignmentRow]
    queued: list[QueuedIssue]

    def list_rows_for_standing(
        self, *, standing: AgentAssignmentStanding
    ) -> list[AgentAssignmentRow]:
        """Return the rows standing there, in the order the board reads them.

        Work that is done reads by when its last round started, most recent
        first, since the last thing to run is the one you were waiting for.
        Everything else reads by issue, with the newest assignment at an issue
        ahead of the older ones.
        """
        found = [one for one in self.rows if one.standing is standing]
        if standing is AgentAssignmentStanding.DONE:
            return sorted(
                found, key=lambda one: one.assignment.rounds[-1].started, reverse=True
            )
        return found


def read_board(*, state: StateDirectory, clock: Callable[[], datetime] = now) -> Board:
    """Return what the state directory says every assignment and issue is doing."""
    return _Look(state=state, clock=clock).compose_board(
        assignments=read_agent_assignments(state=state)
    )


def read_rows_for_issue(
    *, state: StateDirectory, issue: int, clock: Callable[[], datetime] = now
) -> list[AgentAssignmentRow]:
    """Return a row for each assignment at the issue, the newest assignment first.

    A view of one issue reads this rather than the whole board. Judging a
    assignment reads what its running round last said, so a look at one issue
    then reads that issue's own feeds and not the feed of every assignment the
    repo has ever run, and a feed it cannot read is one belonging to the issue
    the reader asked about.

    An issue that no assignment here has reads as no rows at all, which is a
    thing for whoever asked to say rather than a failure.
    """
    look = _Look(state=state, clock=clock)
    return look.list_rows(
        assignments=read_agent_assignments_for_issue(state=state, issue=issue)
    )


class _Look:
    """One look at the state directory, and what it makes of what it read.

    A look is one read of the lock and of the last tick, so the time it read,
    the daemon it found and what that tick said travel together rather than
    down every call. Everything that judges an assignment hangs off it, because
    judging one is what those three answer.

    What a look found is a `Board`, and the look is what composes it. So the
    facts it read reach a board in one place, and nothing outside takes them
    out of a look to build one.
    """

    def __init__(self, *, state: StateDirectory, clock: Callable[[], datetime]) -> None:
        """Take one look at the state directory."""
        self.state = state
        self.at = clock()
        self.daemon_pid = read_daemon_pid(path=state.lock)
        self.scheduler_record = (
            read_json(model=SchedulerRecord, path=state.scheduler_record)
            if state.scheduler_record.exists()
            else None
        )
        self.assignment_observations: dict[str, AgentAssignmentObservation] = (
            {}
            if self.scheduler_record is None
            else {
                one.assignment: one
                for one in self.scheduler_record.assignment_observations
            }
        )

    def compose_board(self, *, assignments: list[AgentAssignment]) -> Board:
        """Return everything this look found, as the board view shows it."""
        return Board(
            at=self.at,
            daemon_pid=self.daemon_pid,
            scheduler_record=self.scheduler_record,
            rows=self.list_rows(assignments=assignments),
            queued=self._list_queued_issues(
                claimed={
                    assignment.record.issue
                    for assignment in assignments
                    if not assignment.is_complete
                }
            ),
        )

    def list_rows(
        self, *, assignments: list[AgentAssignment]
    ) -> list[AgentAssignmentRow]:
        """Return a row for every assignment, the newest assignment at an issue first.

        An assignment's identifier ends with the time the assignment was cut,
        so sorting by identifier backwards puts the newest assignment at an
        issue ahead of the older ones. Sorting that by issue keeps each issue's
        assignments in the order it left them, because a sort in Python holds
        what it does not reorder.
        """
        newest_first = sorted(assignments, key=lambda one: one.identifier, reverse=True)
        return [
            self._read_row(assignment=assignment)
            for assignment in sorted(newest_first, key=lambda one: one.record.issue)
        ]

    def _read_row(self, *, assignment: AgentAssignment) -> AgentAssignmentRow:
        """Return the assignment as one row of the board, where it stands."""
        standing, detail, last_output = self._judge_standing(assignment=assignment)
        return AgentAssignmentRow(
            assignment=assignment,
            standing=standing,
            detail=detail,
            last_output=last_output,
        )

    def _judge_standing(
        self, *, assignment: AgentAssignment
    ) -> tuple[AgentAssignmentStanding, str, str | None]:
        """Return where the assignment's own rounds put it, and what its row says.

        The records answer first, and they answer whatever the daemon is doing.
        A round that recorded no ending is running while a daemon is there to
        run it, and interrupted once that daemon has gone, because a round
        cannot outlive its daemon.
        """
        after = (
            None
            if self.scheduler_record is None
            else self.scheduler_record.most_recent_cooldown_ended
        )
        if derive_assignment_fault(assignment=assignment, after=after):
            return (
                AgentAssignmentStanding.STUCK,
                self._point_at_feed(
                    assignment=assignment, reason="two consecutive rounds failed"
                ),
                None,
            )
        unfinished = assignment.describe_unfinished_round()
        if unfinished is not None:
            if self.daemon_pid is not None and assignment.rounds[-1].ending is None:
                detail, last_output = self._describe_live_round(assignment=assignment)
                return AgentAssignmentStanding.WORKING, detail, last_output
            return AgentAssignmentStanding.WAITING, unfinished, None
        if assignment.is_complete:
            return (
                AgentAssignmentStanding.DONE,
                describe_count(number=len(assignment.rounds), noun="round"),
                None,
            )
        standing, detail = self._judge_wait(assignment=assignment)
        return standing, detail, None

    def _judge_wait(
        self, *, assignment: AgentAssignment
    ) -> tuple[AgentAssignmentStanding, str]:
        """Return what the last tick left an assignment its rounds say nothing about.

        Whether a pull request is open, and whether it carries anything new,
        are what the daemon had to ask GitHub, so the tick's own record is the
        only place they are written down. An assignment the tick wrote nothing
        about is one it found nothing to do for, which leaves it to the user.
        """
        observation = self.assignment_observations.get(assignment.identifier)
        if observation is None:
            if not assignment.rounds:
                return AgentAssignmentStanding.WAITING, NO_ROUND_HAS_RUN
            return AgentAssignmentStanding.NEEDS_YOU, self._describe_idle(
                assignment=assignment
            )
        if observation.is_fault:
            return AgentAssignmentStanding.STUCK, self._point_at_feed(
                assignment=assignment, reason=observation.reason
            )
        return AgentAssignmentStanding.WAITING, observation.reason

    def _describe_live_round(
        self, *, assignment: AgentAssignment
    ) -> tuple[str, str | None]:
        """Return how long the running round has been going, and its last line."""
        since_started = describe_span(span=self.at - assignment.rounds[-1].started)
        line = self._read_last_said(assignment=assignment)
        if line is None:
            return f"running {since_started}, has said nothing yet", None
        since_last_output = describe_span(span=self.at - line.at)
        return (
            f"running {since_started}, last output {since_last_output} ago",
            line.text.strip(),
        )

    def _describe_idle(self, *, assignment: AgentAssignment) -> str:
        """Return how long it is since the assignment last said anything."""
        line = self._read_last_said(assignment=assignment)
        if line is None:
            return "idle"
        return f"idle {describe_span(span=self.at - line.at)}"

    def _read_last_said(self, *, assignment: AgentAssignment) -> Line | None:
        """Return the last line the assignment's last round wrote to its feed."""
        return read_last_feed_line(
            path=assignment.round_paths(number=assignment.rounds[-1].number).feed
        )

    def _list_queued_issues(self, *, claimed: set[int]) -> list[QueuedIssue]:
        """Return the labelled issues the last tick weighed, in the order they go.

        An issue with an open assignment already has its own board row, so the
        queue does not repeat it.
        """
        if self.scheduler_record is None:
            return []
        queued = []
        ahead = 0
        for observation in self.scheduler_record.issue_observations:
            if observation.issue in claimed:
                continue
            availability = derive_issue_availability(observation=observation)
            if availability.value is IssueFactValue.TRUE:
                reason = _describe_place_in_queue(ahead=ahead)
                ahead += 1
            else:
                reason = availability.evidence or "availability is unknown"
            labels = observation.dispatch_labels or []
            if labels:
                queued.append(
                    QueuedIssue(
                        issue=observation.issue,
                        label=labels[0],
                        reason=reason,
                    )
                )
        return queued

    def _point_at_feed(self, *, assignment: AgentAssignment, reason: str) -> str:
        """Return what the assignment waits on, and where to read what it did.

        A fault stops ordinary recovery, so its row says where to read the
        rounds that produced it.
        """
        if not assignment.rounds:
            return reason
        feed = assignment.round_paths(number=assignment.rounds[-1].number).feed
        return f"{reason} ({self.state.describe_path(path=feed)})"


def _describe_place_in_queue(*, ahead: int) -> str:
    """Return where an issue with this many issues ahead of it stands.

    This reads nothing and judges nothing, so it sits outside a look: it is a
    count turned into the words for it.
    """
    if ahead == 0:
        return "next"
    return f"behind {describe_count(number=ahead, noun='other')}"
