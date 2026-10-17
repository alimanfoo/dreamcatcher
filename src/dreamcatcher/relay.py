"""Select what is past a piece of agent work's cursor in its channel.

The relay returns the user posts and pull request signals past an assignment's
cursor, and the issue comments past a conversation's, without writing state.
The inputs of the rounds that took their turn record what each relayed. Posts
and comments written through the shared GitHub account are user input only when
they do not carry the agent marker.
"""

from dataclasses import dataclass

from dreamcatcher.agent_assignments import (
    is_check_failure_withheld,
    read_signal_relay_head,
)
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.github import (
    CheckResult,
    IssueComment,
    PullRequest,
    PullRequestSignal,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    list_issue_comments,
    list_user_posts,
)
from dreamcatcher.issue_conversations import IssueCommentCursor
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
    request's whole history. GitHub sends each time as an ISO-8601 string ending
    in a Z, so the cursor compares against it as text.

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
            if post.written_at > cursor and _is_eligible(post=post, account=account)
        ),
        key=lambda post: post.written_at,
    )


def list_issue_comments_past_cursor(
    *, repository: str, issue: int, account: str, cursor: IssueCommentCursor | None
) -> list[IssueComment] | UnknownGitHubResponse:
    """Return the eligible issue comments past the cursor, oldest first.

    No cursor is the beginning of time, so the first read considers every
    comment on the issue. Comments written in the same second are told apart by
    their ids, which GitHub gives in the order they were written.

    Reading the comments can fail, and the failure travels, so a caller can say
    in one line why it relayed nothing.
    """
    comments = list_issue_comments(repository=repository, issue=issue)
    if isinstance(comments, UnknownGitHubResponse):
        return comments
    after = (cursor.written_at, cursor.id) if cursor is not None else ("", 0)
    return sorted(
        (
            comment
            for comment in comments
            if (comment.written_at, comment.id) > after
            and _is_eligible(post=comment, account=account)
        ),
        key=lambda comment: (comment.written_at, comment.id),
    )


def _is_eligible(*, post: UserPost, account: str) -> bool:
    """Return whether the post is the user's to relay.

    The author must be the signed-in user, the body must not carry the agent
    marker, and the post must say something.
    """
    return (
        post.is_written_by(account=account)
        and AGENT_POST_MARKER not in post.body
        and post.is_speaking
    )
