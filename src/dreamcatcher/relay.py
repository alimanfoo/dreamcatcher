"""Select what is past an agent assignment's cursor in its pull request.

The relay returns user posts and pull request signals without writing state.
The inputs of the rounds that took their turn record what each relayed. Posts
written through the shared GitHub account are user input only when they do not
carry the agent marker.
"""

from dataclasses import dataclass

from dreamcatcher.agent_assignments import (
    is_check_failure_withheld,
    read_signal_relay_head,
)
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.github import (
    CheckResult,
    PullRequest,
    PullRequestSignal,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    list_user_posts,
)
from dreamcatcher.prompts import AGENT_POST_MARKER


@dataclass(frozen=True, kw_only=True)
class PullRequestSignals:
    """Hold the pull request signals past an assignment's cursor.

    A check failure the relay rule withholds is left out, and flagged.
    """

    new_pull_request_signals: list[PullRequestSignal]
    is_check_failure_withheld: bool


def find_pull_request_signals(
    *, assignment: AgentWork, pull_request: PullRequest
) -> PullRequestSignals:
    """Return the pull request signals raised at a head not yet relayed.

    Only an open pull request that is ready for review raises one, because a
    draft means that the agent has not finished. A check failure that the relay
    rule withholds is not new.
    """
    if pull_request.state is not PullRequestState.OPEN or pull_request.is_draft:
        return PullRequestSignals(
            new_pull_request_signals=[], is_check_failure_withheld=False
        )
    raised = [
        signal
        for signal, is_raised in (
            (PullRequestSignal.OUT_OF_DATE, pull_request.merge_state.is_out_of_date),
            (
                PullRequestSignal.CHECK_FAILURE,
                pull_request.check_result is CheckResult.FAILING,
            ),
        )
        if is_raised
        and read_signal_relay_head(assignment=assignment, signal=signal)
        != pull_request.head
    ]
    is_withheld = PullRequestSignal.CHECK_FAILURE in raised and (
        is_check_failure_withheld(assignment=assignment)
    )
    if is_withheld:
        raised.remove(PullRequestSignal.CHECK_FAILURE)
    return PullRequestSignals(
        new_pull_request_signals=raised, is_check_failure_withheld=is_withheld
    )


def list_user_posts_past_cursor(
    *, repository: str, pull_request: int, account: str, cursor: str
) -> list[UserPost] | UnknownGitHubResponse:
    """Return user posts past the cursor, oldest first.

    The account is the one gh is signed in as, which is the user's own.

    An empty cursor is the beginning of time, so the first read considers the pull
    request's whole history.

    Reading the posts can fail, and the failure travels, so a caller can say
    in one line why it relayed nothing.
    """
    user_posts = list_user_posts(repository=repository, pull_request=pull_request)
    if isinstance(user_posts, UnknownGitHubResponse):
        return user_posts
    return sorted(
        (
            post
            for post in user_posts
            if _is_user_post_past_cursor(post=post, account=account, cursor=cursor)
        ),
        key=lambda post: post.written_at,
    )


def _is_user_post_past_cursor(*, post: UserPost, account: str, cursor: str) -> bool:
    """Return whether the post is past the cursor and the user's to relay.

    The post has to be newer than the cursor, or the assignment has
    already received it. GitHub sends each time as an ISO-8601 string ending in a
    Z, and one such string compares against another as text.

    The author must be the signed-in user, the body must not carry the agent
    marker, and the post must say something.
    """
    return (
        post.written_at > cursor
        and post.is_written_by(account=account)
        and AGENT_POST_MARKER not in post.body
        and post.is_speaking
    )
