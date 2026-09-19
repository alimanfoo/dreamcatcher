"""Carry what the user posts on a pull request into the assignment working on it.

The relay reads the pull request's posts, keeps the undelivered ones in which the
user said something, and hands them back. It writes nothing.

An assignment keeps a user-post delivery cursor, which identifies the newest post
delivered to it. Advancing the cursor is the write, and it happens after a round
starts with a batch of posts as its input. A daemon that dies before the cursor
advances therefore reads the same posts again on its next tick.

The user and the assignment post through one GitHub account, because that is the
account the harness CLI is signed in as. So the account alone cannot tell the
two apart, and the marker every prompt asks the assignment to end its posts with
is what does.
"""

from dreamcatcher.github import UnknownGitHubResponse, UserPost, list_user_posts
from dreamcatcher.prompts import AGENT_POST_MARKER


def list_undelivered_user_posts(
    *, repository: str, pull_request: int, account: str, delivery_cursor: str
) -> list[UserPost] | UnknownGitHubResponse:
    """Return what the user posted after the delivery cursor, oldest first.

    The account is the one gh is signed in as, which is the user's own.

    The delivery cursor is the newest post that the assignment has received. No
    cursor at all is the beginning of time, so an assignment's first relay returns
    the pull request's whole history.

    Reading the posts can fail, and the failure travels, so a caller can say
    in one line why it relayed nothing.
    """
    found = list_user_posts(repository=repository, pull_request=pull_request)
    if isinstance(found, UnknownGitHubResponse):
        return found
    return sorted(
        (
            post
            for post in found
            if _is_undelivered_user_post(
                post=post, account=account, delivery_cursor=delivery_cursor
            )
        ),
        key=lambda post: post.written_at,
    )


def _is_undelivered_user_post(
    *, post: UserPost, account: str, delivery_cursor: str
) -> bool:
    """Whether the relay returns this post.

    The post has to be newer than the delivery cursor, or the assignment has
    already received it. GitHub sends each time as an ISO-8601 string ending in a
    Z, and one such string compares against another as text.

    Then the two rules. The post is the user's when the account that wrote it
    is the user's own and its body carries no marker, which is what leaves the
    assignment's own words, and anybody else's, where they are. And the post has
    to say something, so an empty review that GitHub wrapped around an inline
    comment never reads as the user asking for anything.
    """
    return (
        post.written_at > delivery_cursor
        and post.author == account
        and AGENT_POST_MARKER not in post.body
        and post.is_speaking
    )
