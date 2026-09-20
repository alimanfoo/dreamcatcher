"""Select new user posts for delivery to an agent assignment.

The relay returns posts without writing state. The assignment's delivery cursor
records the newest delivered post after a round starts. Posts written through
the shared GitHub account are user input only when they do not carry the agent
marker.
"""

from dreamcatcher.github import UnknownGitHubResponse, UserPost, list_user_posts
from dreamcatcher.prompts import AGENT_POST_MARKER


def list_undelivered_user_posts(
    *, repository: str, pull_request: int, account: str, delivery_cursor: str
) -> list[UserPost] | UnknownGitHubResponse:
    """Return user posts after the delivery cursor, oldest first.

    The account is the one gh is signed in as, which is the user's own.

    An empty cursor is the beginning of time, so the first read considers the
    pull request's whole history.

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
            if _is_undelivered_user_post(
                post=post, account=account, delivery_cursor=delivery_cursor
            )
        ),
        key=lambda post: post.written_at,
    )


def _is_undelivered_user_post(
    *, post: UserPost, account: str, delivery_cursor: str
) -> bool:
    """Return whether the relay should deliver the post.

    The post has to be newer than the delivery cursor, or the assignment has
    already received it. GitHub sends each time as an ISO-8601 string ending in a
    Z, and one such string compares against another as text.

    The author must be the signed-in user, the body must not carry the agent
    marker, and the post must say something.
    """
    return (
        post.written_at > delivery_cursor
        and post.author == account
        and AGENT_POST_MARKER not in post.body
        and post.is_speaking
    )
