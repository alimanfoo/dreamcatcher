"""Work out the round that a session needs next.

A session lies dormant between its rounds, with no agent of its own running,
and three things wake it. A round that did not finish is carried on. A pull
request that is merged or closed calls for one last round. And a pull request
the user has posted on calls for a round that answers what the user said.

The most open work comes first, and that order is here. A session part way
through a round is carried on before anything else. Then a finished pull
request, whose session has one round left to run. Then the user's own posts.

Nothing here launches a round or writes anything down. A caller that has
decided asks for the wakeup and runs it.
"""

from dataclasses import dataclass

from dreamcatcher.github import (
    AnyPost,
    PullRequest,
    PullRequestState,
    Unknown,
    list_pull_requests,
)
from dreamcatcher.prompts import CARRY_ON_PROMPT, compose_inbox_prompt
from dreamcatcher.relay import Inbox, peek_new_posts
from dreamcatcher.rounds import Cause
from dreamcatcher.sessions import Session
from dreamcatcher.state import NO_ROUND_HAS_RUN, WaitingSession
from dreamcatcher.words import describe_count


@dataclass(frozen=True, kw_only=True)
class Wakeup:
    """The round that would wake a dormant session, ready to run.

    The cause is what the round's own record keeps. The reason is the same
    thing in words and with the evidence, which a tick that could not launch
    this round writes down instead.

    The inbox is the batch the round is woken with. A carry-on has none: the
    transcript that the harness resumes carries that work already.
    """

    session: Session
    cause: Cause
    reason: str
    prompt: str
    inbox: Inbox | None = None

    @property
    def newest_post(self) -> str:
        """When the newest post this round is woken with was written.

        A round woken by nothing the user said has no such post, and answers
        with the beginning of time, so a launch knows to leave the session's
        watermark where it is.
        """
        if self.inbox is None or not self.inbox.posts:
            return ""
        return self.inbox.posts[-1].written_at


# What a tick found about one session: the wakeup it needs, or what it is
# waiting on instead.
type Finding = Wakeup | WaitingSession


# The order a tick takes wakeups in, the most open work first.
PRIORITY = (Cause.CARRY_ON, Cause.FINAL, Cause.POSTS)


def sort_wakeups(*, found: list[Wakeup]) -> list[Wakeup]:
    """Return the wakeups with the most open work first.

    Two wakeups of one kind keep the order their sessions came in, which is by
    key, so a tick takes the same one every time it looks.
    """
    return sorted(found, key=lambda resume: PRIORITY.index(resume.cause))


def list_waiting(*, found: list[Finding]) -> list[WaitingSession]:
    """Return what each of these findings says its session is waiting on.

    A wakeup that no round ran is a session waiting for a later tick, and the
    wakeup's own reason is what it is waiting on.
    """
    return [
        one
        if isinstance(one, WaitingSession)
        else compose_wait(session=one.session, reason=one.reason)
        for one in found
    ]


def judge_session(*, repository: str, account: str, session: Session) -> Finding | None:
    """Return what the session needs next, or nothing when it needs nothing.

    A session that needs a round comes back as the wakeup that runs it, and one
    that needs something this tick cannot give comes back as the wait it is in.

    A session whose last round did not finish is carried on before anything
    else is even read, so a tick spends no GitHub call on the case that needs
    none.

    A session that has run no round at all is waiting rather than waking.
    Its dispatch cut the session and never started the first round, so no
    harness session exists to carry on, and only a person can take it from
    here.
    """
    if not session.rounds:
        return compose_wait(session=session, reason=NO_ROUND_HAS_RUN, is_stuck=True)
    unfinished = session.describe_unfinished_round()
    if unfinished is not None:
        return Wakeup(
            session=session,
            cause=Cause.CARRY_ON,
            reason=unfinished,
            prompt=CARRY_ON_PROMPT,
        )
    return _judge_pull_request(repository=repository, account=account, session=session)


def _judge_pull_request(
    *, repository: str, account: str, session: Session
) -> Finding | None:
    """Return what the session's pull request asks of it, if anything.

    Every read here biases toward doing nothing: a read that could not tell
    leaves the session waiting with what the read said, and the next tick asks
    again.

    The peek runs whatever state the pull request is in, so the last round of a
    merged pull request still carries whatever the user said before merging it.
    A session that has already run that last round is done, and is not peeked
    at again.
    """
    found = list_pull_requests(repository=repository, branch=session.record.branch)
    if isinstance(found, Unknown):
        return compose_wait(
            session=session,
            reason=f"cannot tell which pull request it has: {found.reason}",
        )
    pull_request = _choose_pull_request(found=found)
    if pull_request is None:
        return compose_wait(
            session=session,
            reason="no pull request has been opened on it",
            is_stuck=True,
        )
    is_open = pull_request.state is PullRequestState.OPEN
    if not is_open and session.has_run_final_round:
        return None
    posted = peek_new_posts(
        repository=repository,
        pull_request=pull_request.number,
        account=account,
        watermark=session.watermark,
    )
    if isinstance(posted, Unknown):
        return compose_wait(
            session=session, reason=f"cannot tell what the user posted: {posted.reason}"
        )
    if is_open and not posted:
        return None
    return _compose_resume(session=session, pull_request=pull_request, posted=posted)


def _choose_pull_request(*, found: list[PullRequest]) -> PullRequest | None:
    """Return the pull request that says where the session's work has got to.

    A branch has one pull request, near enough. Where it has more, an open one
    is the session's live channel and outranks the rest, and the newest of
    equals is the one whose story is still going.
    """
    if not found:
        return None
    return max(
        found,
        key=lambda pull_request: (
            pull_request.state is PullRequestState.OPEN,
            pull_request.number,
        ),
    )


def _compose_resume(
    *, session: Session, pull_request: PullRequest, posted: list[AnyPost]
) -> Wakeup:
    """Return the round that the pull request and the user's posts call for.

    The prompt names the file the launch writes the inbox to, and the state in
    that file is what tells the session whether to answer the user or to wind
    the session up. So both rounds ask for the same thing in the same words.
    """
    is_open = pull_request.state is PullRequestState.OPEN
    return Wakeup(
        session=session,
        cause=Cause.POSTS if is_open else Cause.FINAL,
        reason=(
            f"{describe_count(number=len(posted), noun='new post')} to answer"
            if is_open
            else f"the pull request is {pull_request.state.lower()}"
        ),
        prompt=compose_inbox_prompt(
            pull_request=pull_request.number, inbox=session.next_workspace.inbox
        ),
        inbox=Inbox(state=pull_request.state, posts=posted),
    )


def compose_wait(
    *, session: Session, reason: str, is_stuck: bool = False
) -> WaitingSession:
    """Return the session as one waiting on what this reason says.

    A wait is stuck when no later tick clears it: the dispatch never started
    the session's first round, or a round ended cleanly and opened no pull
    request. Every other wait clears by itself, so a stuck one is the one that
    has to reach a person.
    """
    return WaitingSession(
        session=session.key,
        issue=session.record.issue,
        reason=reason,
        is_stuck=is_stuck,
    )
