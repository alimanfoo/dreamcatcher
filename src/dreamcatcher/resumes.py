"""Work out the round that a session needs next.

A session sleeps between rounds, and three things wake it. A round that did not
finish is carried on. A pull request that is merged or closed calls for one
last round. And a pull request the user has posted on calls for a round that
answers what the user said.

The most open work comes first, and that order is here. A session part way
through a round is carried on before anything else. Then a finished pull
request, whose session has one round left to run. Then the user's own posts.

Nothing here launches a round or writes anything down. A caller that has
decided asks for the resume and runs it.
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
from dreamcatcher.state import Waiting


@dataclass(frozen=True)
class Resume:
    """The round a session needs next, ready to run.

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


# What a tick found about one session: the round it needs next, or what it is
# waiting on instead.
type Finding = Resume | Waiting


# The order a tick takes resumes in, the most open work first.
PRIORITY = (Cause.CARRY_ON, Cause.FINAL, Cause.POSTS)


def sort_resumes(found: list[Resume]) -> list[Resume]:
    """Return the resumes with the most open work first.

    Two resumes of one kind keep the order their sessions came in, which is by
    key, so a tick takes the same one every time it looks.
    """
    return sorted(found, key=lambda resume: PRIORITY.index(resume.cause))


def list_waiting(found: list[Finding]) -> list[Waiting]:
    """Return what each of these findings says its session is waiting on.

    A resume that no round ran is a session waiting for a later tick, and the
    resume's own reason is what it is waiting on.
    """
    return [
        one if isinstance(one, Waiting) else _wait(one.session, one.reason)
        for one in found
    ]


def judge_session(repository: str, account: str, session: Session) -> Finding | None:
    """Return what the session needs next, or nothing when it needs nothing.

    A session that needs a round comes back as the resume that runs it, and one
    that needs something this tick cannot give comes back as the wait it is in.

    A session whose last round did not finish is carried on before anything
    else is even read, so a tick spends no GitHub call on the case that needs
    none.

    A session that has run no round at all is waiting rather than resuming.
    Its dispatch cut the session and never started the first round, so no
    harness session exists to carry on, and only a person can take it from
    here.
    """
    if not session.rounds:
        return _wait(session, "no round has run yet")
    unfinished = _check_last_round(session)
    if unfinished is not None:
        return Resume(
            session=session,
            cause=Cause.CARRY_ON,
            reason=unfinished,
            prompt=CARRY_ON_PROMPT,
        )
    return _judge_pull_request(repository, account, session)


def _check_last_round(session: Session) -> str | None:
    """Return what the session's most recent round left unfinished, or nothing.

    A record with no ending is a round the daemon stopped or outlived, and a
    round that ended with a failing status stopped short of its own accord.
    Both leave the work part done, so both are carried on from where they
    stopped.
    """
    ending = session.rounds[-1].ending
    if ending is None:
        return "the last round was interrupted"
    if ending.is_failed:
        return f"the last round failed (exit {ending.status})"
    return None


def _judge_pull_request(
    repository: str, account: str, session: Session
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
    found = list_pull_requests(repository, session.record.branch)
    if isinstance(found, Unknown):
        return _wait(session, f"cannot tell which pull request it has: {found.reason}")
    pull_request = _choose_pull_request(found)
    if pull_request is None:
        return _wait(session, "no pull request has been opened on it")
    is_open = pull_request.state is PullRequestState.OPEN
    if not is_open and _has_run_final_round(session):
        return None
    posted = peek_new_posts(
        repository,
        pull_request.number,
        account=account,
        watermark=session.watermark,
    )
    if isinstance(posted, Unknown):
        return _wait(session, f"cannot tell what the user posted: {posted.reason}")
    if is_open and not posted:
        return None
    return _compose_resume(session, pull_request, posted)


def _choose_pull_request(found: list[PullRequest]) -> PullRequest | None:
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


def _has_run_final_round(session: Session) -> bool:
    """Whether the session has already run the round that winds it up.

    Only a session whose last round finished reaches this, so a final round
    among its rounds is a final round that completed. One that was interrupted
    or that failed is carried on first, and the carry-on finishes what the
    final round started.
    """
    return any(record.cause is Cause.FINAL for record in session.rounds)


def _compose_resume(
    session: Session, pull_request: PullRequest, posted: list[AnyPost]
) -> Resume:
    """Return the round that the pull request and the user's posts call for.

    The prompt names the file the launch writes the inbox to, and the state in
    that file is what tells the session whether to answer the user or to wind
    the session up. So both rounds ask for the same thing in the same words.
    """
    is_open = pull_request.state is PullRequestState.OPEN
    return Resume(
        session=session,
        cause=Cause.POSTS if is_open else Cause.FINAL,
        reason=(
            f"{_count_posts(posted)} to answer"
            if is_open
            else f"the pull request is {pull_request.state.lower()}"
        ),
        prompt=compose_inbox_prompt(pull_request.number, session.next_workspace.inbox),
        inbox=Inbox(state=pull_request.state, posts=posted),
    )


def _count_posts(posted: list[AnyPost]) -> str:
    """Return how many posts these are, in words that read for one or for many."""
    if len(posted) == 1:
        return "1 new post"
    return f"{len(posted)} new posts"


def _wait(session: Session, reason: str) -> Waiting:
    """Return the session as one waiting on what this reason says."""
    return Waiting(session=session.key, issue=session.record.issue, reason=reason)
