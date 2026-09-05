"""Carry what the user posts on a pull request into the session working on it.

The peek reads the pull request's posts, keeps the ones the user newly said
something in, and hands them back. It writes nothing.

A session keeps a watermark, which is the newest post it has been told about
already, and the peek reads by that. Moving the watermark on is the write, and
it happens when a round launches with a batch of posts as its inbox. So a
daemon that dies before that launch reads the same posts again on its next
tick, rather than losing them.

The user and the session post through one GitHub account, because that is the
account the harness CLI is signed in as. So the account alone cannot tell the
two apart, and the marker every prompt asks the session to end its posts with
is what does.
"""

from dreamcatcher.documents import Document
from dreamcatcher.github import AnyPost, Post, PullRequestState, Unknown, list_posts
from dreamcatcher.prompts import MARKER


class Inbox(Document):
    """The batch a round is woken with, as the session reads it.

    The state is where the pull request had got to when the tick looked at it.
    It is what tells a session whether to answer the user or to wrap the
    session up, so one prompt serves both kinds of round.

    The posts are what the user newly said, oldest first. A round that a merged
    or closed pull request woke carries whatever the user said last, and often
    nothing at all.

    A round writes this into its own directory before it starts, and it stays
    there, so whoever reads the session afterwards reads what each round was
    given.
    """

    state: PullRequestState
    posts: list[AnyPost]


def peek_new_posts(
    repository: str, pull_request: int, *, account: str, watermark: str
) -> list[AnyPost] | Unknown:
    """Return what the user posted since the watermark, oldest first.

    The account is the one gh is signed in as, which is the user's own.

    The watermark is the newest post the session has already been told about.
    No watermark at all is the beginning of time, so a session's first peek
    returns the pull request's whole history.

    Reading the posts can fail, and the failure travels, so a caller can say
    in one line why it relayed nothing.
    """
    found = list_posts(repository, pull_request)
    if isinstance(found, Unknown):
        return found
    return sorted(
        (post for post in found if _is_new_from_user(post, account, watermark)),
        key=lambda post: post.written_at,
    )


def _is_new_from_user(post: Post, account: str, watermark: str) -> bool:
    """Whether the peek returns this post.

    The post has to be newer than the watermark, or the session has already
    been told about it. GitHub sends each time as an ISO-8601 string ending in
    a Z, and one such string compares against another as text.

    Then the two rules. The post is the user's when the account that wrote it
    is the user's own and its body carries no marker, which is what leaves the
    session's own words, and anybody else's, where they are. And the post has
    to say something, so an empty review that GitHub wrapped around an inline
    comment never reads as the user asking for anything.
    """
    return (
        post.written_at > watermark
        and post.author == account
        and MARKER not in post.body
        and post.is_speaking
    )
