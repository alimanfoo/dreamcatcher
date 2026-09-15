"""Work out the round that an assignment needs next.

An assignment lies dormant between its rounds, with no agent of its own running,
and three things wake it. A round that did not finish is carried on. A pull
request that is merged or closed calls for one last round. And a pull request
the user has posted on calls for a round that answers what the user said.

The most open work comes first, and that order is here. A complete assignment
whose first round has not started finishes its dispatch before ordinary work.
Then an assignment part way through a round is carried on, a finished pull
request gets its final round, and an assignment answers the user's own posts.

Nothing here launches a round or writes anything down. A caller that has
decided asks for the wakeup and runs it.
"""

from dataclasses import dataclass

from dreamcatcher.agent_assignments import AgentAssignment
from dreamcatcher.github import (
    AnyPost,
    PullRequest,
    PullRequestState,
    Unknown,
    read_pull_request,
)
from dreamcatcher.prompts import CARRY_ON_PROMPT, compose_inbox_prompt
from dreamcatcher.relay import Inbox, peek_new_posts
from dreamcatcher.rounds import Cause
from dreamcatcher.state import NO_ROUND_HAS_RUN, WaitingAgentAssignment
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class Wakeup:
    """The round that would wake a dormant assignment, ready to run.

    The cause is what the round's own record keeps. The reason is the same
    thing in words and with the evidence, which a tick that could not launch
    this round writes down instead.

    The inbox is the batch the round is woken with. A carry-on has none: the
    transcript that the harness resumes carries that work already.
    """

    assignment: AgentAssignment
    cause: Cause
    reason: str
    prompt: str
    inbox: Inbox | None = None

    @property
    def newest_post(self) -> str:
        """When the newest post this round is woken with was written.

        A round woken by nothing the user said has no such post, and answers
        with the beginning of time, so a launch knows to leave the assignment's
        watermark where it is.
        """
        if self.inbox is None or not self.inbox.posts:
            return ""
        return self.inbox.posts[-1].written_at


# What a tick found about one assignment: the wakeup it needs, or what it is
# waiting on instead.
type Finding = Wakeup | WaitingAgentAssignment


# The order a tick takes wakeups in, the most open work first.
PRIORITY = (Cause.DISPATCH, Cause.CARRY_ON, Cause.FINAL, Cause.POSTS)


def sort_wakeups(*, found: list[Wakeup]) -> list[Wakeup]:
    """Return the wakeups with the most open work first.

    Two wakeups of one kind keep the order their assignments came in, which is
    by identifier, so a tick takes the same one every time it looks.
    """
    return sorted(found, key=lambda resume: PRIORITY.index(resume.cause))


def list_waiting(*, found: list[Finding]) -> list[WaitingAgentAssignment]:
    """Return what each of these findings says its assignment is waiting on.

    A wakeup that no round ran is an assignment waiting for a later tick, and the
    wakeup's own reason is what it is waiting on.
    """
    return [
        one
        if isinstance(one, WaitingAgentAssignment)
        else compose_wait(assignment=one.assignment, reason=one.reason)
        for one in found
    ]


def judge_assignment(
    *, repository: str, account: str, assignment: AgentAssignment
) -> Finding | None:
    """Return what the assignment needs next, or nothing when it needs nothing.

    An assignment that needs a round comes back as the wakeup that runs it, and one
    that needs something this tick cannot give comes back as the wait it is in.

    An assignment whose last round did not finish is carried on before anything
    else is even read, so a tick spends no GitHub call on the case that needs
    none.

    An assignment that has run no round at all needs its first round. This can
    happen when assignment creation succeeded but that round could not start.
    """
    if not assignment.rounds:
        return compose_dispatch_wakeup(assignment=assignment)
    unfinished = assignment.describe_unfinished_round()
    if unfinished is not None:
        return Wakeup(
            assignment=assignment,
            cause=Cause.CARRY_ON,
            reason=unfinished,
            prompt=CARRY_ON_PROMPT,
        )
    return _judge_pull_request(
        repository=repository, account=account, assignment=assignment
    )


def compose_dispatch_wakeup(*, assignment: AgentAssignment) -> Wakeup:
    """Return the first round a complete assignment is waiting to run."""
    return Wakeup(
        assignment=assignment,
        cause=Cause.DISPATCH,
        reason=NO_ROUND_HAS_RUN,
        prompt=assignment.record.prompt,
    )


def _judge_pull_request(
    *, repository: str, account: str, assignment: AgentAssignment
) -> Finding | None:
    """Return what the assignment's pull request asks of it, if anything.

    Every read here biases toward doing nothing: a read that could not tell
    leaves the assignment waiting with what the read said, and the next tick asks
    again.

    The peek runs whatever state the pull request is in, so the last round of a
    merged pull request still carries whatever the user said before merging it.
    An assignment that has already run that last round is done, and is not peeked
    at again.
    """
    pull_request = read_pull_request(
        repository=repository, pull_request=assignment.record.pull_request
    )
    if isinstance(pull_request, Unknown):
        return compose_wait(
            assignment=assignment,
            reason=f"cannot read its pull request: {pull_request.reason}",
        )
    is_open = pull_request.state is PullRequestState.OPEN
    if not is_open and assignment.has_run_final_round:
        return None
    posted = peek_new_posts(
        repository=repository,
        pull_request=pull_request.number,
        account=account,
        watermark=assignment.watermark,
    )
    if isinstance(posted, Unknown):
        return compose_wait(
            assignment=assignment,
            reason=f"cannot tell what the user posted: {posted.reason}",
        )
    if is_open and not posted:
        return None
    return _compose_resume(
        assignment=assignment, pull_request=pull_request, posted=posted
    )


def _compose_resume(
    *, assignment: AgentAssignment, pull_request: PullRequest, posted: list[AnyPost]
) -> Wakeup:
    """Return the round that the pull request and the user's posts call for.

    The prompt names the file the launch writes the inbox to, and the state in
    that file is what tells the assignment whether to answer the user or to wind
    the assignment up. So both rounds ask for the same thing in the same words.
    """
    is_open = pull_request.state is PullRequestState.OPEN
    return Wakeup(
        assignment=assignment,
        cause=Cause.POSTS if is_open else Cause.FINAL,
        reason=(
            f"{describe_count(number=len(posted), noun='new post')} to answer"
            if is_open
            else f"the pull request is {pull_request.state.lower()}"
        ),
        prompt=compose_inbox_prompt(
            pull_request=pull_request.number, inbox=assignment.next_workspace.inbox
        ),
        inbox=Inbox(state=pull_request.state, posts=posted),
    )


def compose_wait(
    *, assignment: AgentAssignment, reason: str, is_stuck: bool = False
) -> WaitingAgentAssignment:
    """Return the assignment as one waiting on what this reason says.

    Every current wait can clear on a later tick. The `is_stuck` field remains
    for the current status model until that model is replaced.
    """
    return WaitingAgentAssignment(
        assignment=assignment.identifier,
        issue=assignment.record.issue,
        reason=reason,
        is_stuck=is_stuck,
    )
