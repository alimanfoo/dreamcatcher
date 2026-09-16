"""Work out the round that an assignment needs next.

An assignment lies dormant between its rounds, with no agent of its own running,
and four things wake it. A recorded assignment missing its first round finishes
its dispatch. A round that did not finish is recovered. A pull request that is
merged or closed calls for a wrap-up round. And a pull request the user has
posted on calls for a round that answers what the user said.

The most open work comes first, and that order is here. A recorded assignment
whose first round has not started finishes its dispatch before ordinary work.
Then an assignment part way through a round is recovered, a finished pull
request gets a wrap-up round, and an assignment answers the user's own posts.

Nothing here launches a round or writes anything down. A caller that has
decided asks for the wakeup and runs it.
"""

from dataclasses import dataclass

from dreamcatcher.agent_assignments import AgentAssignment
from dreamcatcher.agent_rounds import AgentRoundInput, AgentRoundPlan, RoundPurpose
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    Unknown,
    UserPost,
    read_pull_request,
)
from dreamcatcher.prompts import CARRY_ON_PROMPT, compose_inbox_prompt
from dreamcatcher.relay import list_undelivered_user_posts
from dreamcatcher.state import NO_ROUND_HAS_RUN, WaitingAgentAssignment
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class Wakeup:
    """The round that would wake a dormant assignment, ready to run.

    The plan carries the decisions and input that the round executes. The reason
    carries the evidence that a tick which could not launch this round writes
    down instead.
    """

    assignment: AgentAssignment
    plan: AgentRoundPlan
    reason: str
    prompt: str


# What a tick found about one assignment: the wakeup it needs, or what it is
# waiting on instead.
type Finding = Wakeup | WaitingAgentAssignment


# The order a tick takes wakeups in, the most open work first.
def sort_wakeups(*, found: list[Wakeup]) -> list[Wakeup]:
    """Return the wakeups with the most open work first.

    Two wakeups of one kind keep the order their assignments came in, which is
    by identifier, so a tick takes the same one every time it looks.
    """
    return sorted(found, key=_wakeup_priority)


def _wakeup_priority(wakeup: Wakeup, /) -> int:
    """Return the existing scheduling priority of one required round."""
    if not wakeup.assignment.rounds:
        return 0
    if wakeup.plan.is_recovery:
        return 1
    if wakeup.plan.purpose is RoundPurpose.WRAP_UP:
        return 2
    return 3


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

    An assignment whose last round did not finish is recovered before anything
    else is even read, so a tick spends no GitHub call on the case that needs
    none.

    An assignment that has run no round at all needs its first round. This can
    happen when assignment creation succeeded but that round could not start.
    """
    if not assignment.rounds:
        return compose_dispatch_wakeup(assignment=assignment)
    if assignment.is_complete:
        return None
    unfinished = assignment.describe_unfinished_round()
    return _judge_pull_request(
        repository=repository,
        account=account,
        assignment=assignment,
        recovery_reason=unfinished,
    )


def compose_dispatch_wakeup(*, assignment: AgentAssignment) -> Wakeup:
    """Return the first round a recorded assignment is waiting to run."""
    return Wakeup(
        assignment=assignment,
        plan=AgentRoundPlan(purpose=RoundPurpose.IMPLEMENT, is_recovery=False),
        reason=NO_ROUND_HAS_RUN,
        prompt=assignment.record.prompt,
    )


def _judge_pull_request(
    *,
    repository: str,
    account: str,
    assignment: AgentAssignment,
    recovery_reason: str | None,
) -> Finding | None:
    """Return what the assignment's pull request asks of it, if anything.

    Every read here biases toward doing nothing: a read that could not tell
    leaves the assignment waiting with what the read said, and the next tick asks
    again.

    A wrap-up round still carries whatever the user said before merging or closing
    the pull request.
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
    if recovery_reason is not None and is_open:
        return Wakeup(
            assignment=assignment,
            plan=AgentRoundPlan(
                purpose=_round_purpose(pull_request=pull_request),
                is_recovery=True,
            ),
            reason=recovery_reason,
            prompt=CARRY_ON_PROMPT,
        )
    posted = list_undelivered_user_posts(
        repository=repository,
        pull_request=pull_request.number,
        account=account,
        delivery_cursor=assignment.user_post_delivery_cursor,
    )
    if isinstance(posted, Unknown):
        return compose_wait(
            assignment=assignment,
            reason=f"cannot tell what the user posted: {posted.reason}",
        )
    if is_open and not posted:
        return None
    return _compose_resume(
        assignment=assignment,
        pull_request=pull_request,
        posted=posted,
        recovery_reason=recovery_reason,
    )


def _compose_resume(
    *,
    assignment: AgentAssignment,
    pull_request: PullRequest,
    posted: list[UserPost],
    recovery_reason: str | None,
) -> Wakeup:
    """Return the round that the pull request and the user's posts call for.

    The prompt names the file to which the round writes its input, and the state
    in that file tells the assignment whether to answer the user or to wind the
    assignment up. Both rounds therefore ask for the same thing in the same words.
    """
    is_open = pull_request.state is PullRequestState.OPEN
    return Wakeup(
        assignment=assignment,
        plan=AgentRoundPlan(
            purpose=_round_purpose(pull_request=pull_request),
            is_recovery=recovery_reason is not None,
            input=AgentRoundInput(state=pull_request.state, posts=posted),
        ),
        reason=(
            recovery_reason
            or (
                f"{describe_count(number=len(posted), noun='new post')} to answer"
                if is_open
                else f"the pull request is {pull_request.state.lower()}"
            )
        ),
        prompt=compose_inbox_prompt(
            pull_request=pull_request.number,
            inbox=assignment.round_paths(number=assignment.next_round_number).inbox,
        ),
    )


def _round_purpose(*, pull_request: PullRequest) -> RoundPurpose:
    """Return the work that the pull request currently asks a round to advance."""
    if pull_request.state is not PullRequestState.OPEN:
        return RoundPurpose.WRAP_UP
    if pull_request.is_draft:
        return RoundPurpose.IMPLEMENT
    return RoundPurpose.ADDRESS_FEEDBACK


def compose_wait(*, assignment: AgentAssignment, reason: str) -> WaitingAgentAssignment:
    """Return the assignment as waiting for a later tick to clear the reason."""
    return WaitingAgentAssignment(
        assignment=assignment.identifier,
        issue=assignment.record.issue,
        reason=reason,
    )
