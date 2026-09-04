"""Ask gh what GitHub knows about the repository dreamcatcher watches."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    AliasPath,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from dreamcatcher.commands import CommandError, run

# gh lists thirty of anything unless you tell it otherwise, and thirty issues is
# a number a busy repository passes. Asking for five hundred keeps the tool from
# dropping work it can see. Only the issue listing needs it: a branch has one
# pull request, near enough, and thirty is beyond any real count of blockers.
LISTING_LIMIT = "500"

# How many of a paginated list to ask GitHub for at a time. gh reads every page
# whatever the size, so the largest page GitHub allows is the fewest calls for
# the same answer.
PAGE_SIZE = "100"


@dataclass(frozen=True)
class Unknown:
    """What a read answers when it could not tell.

    Every read biases the daemon toward doing nothing. A caller that gets this
    decides what not knowing means for its own check, and no read ever guesses
    on its behalf. The reason travels with it, so a tick can record why it could
    not tell.
    """

    reason: str


class Projection(BaseModel):
    """The fields dreamcatcher reads out of a document GitHub owns.

    GitHub owns the document, so a key we do not declare passes without
    complaint. That is the opposite of a Document, which refuses a key that it
    does not expect.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)


class PullRequestState(StrEnum):
    """Where a pull request has got to. gh names these in capitals."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class BlockerState(StrEnum):
    """Whether a blocking issue is still open. The REST API uses lower case."""

    OPEN = "open"
    CLOSED = "closed"


class PostKind(StrEnum):
    """Which of the three places on a pull request a post was written in.

    The three arrive as one list, and nothing GitHub sends says which list a
    post came from, so each post carries its own kind.
    """

    COMMENT = "comment"
    REVIEW = "review"
    INLINE_COMMENT = "inline_comment"


class Verdict(StrEnum):
    """What a review said. GitHub names these in capitals."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"


# The verdicts that say something on their own. A review carrying one of these
# is worth reading even with an empty body, and every other verdict leaves the
# body to do the talking.
SPEAKING_VERDICTS = frozenset({Verdict.APPROVED, Verdict.CHANGES_REQUESTED})


class Repository(Projection):
    """The repository a checkout belongs to, as GitHub names it."""

    name_with_owner: str = Field(alias="nameWithOwner")


class Account(Projection):
    """The account gh is signed in as."""

    login: str


class Issue(Projection):
    """An open issue gh listed, and when it was filed."""

    number: int
    created_at: datetime = Field(alias="createdAt")


class PullRequest(Projection):
    """A pull request gh listed, and where it has got to."""

    number: int
    state: PullRequestState


class Blocker(Projection):
    """An issue that blocks another, and whether it is still open."""

    number: int
    state: BlockerState


class LinkedPullRequest(Projection):
    """A pull request GitHub links to an issue."""

    number: int


class Linked(Projection):
    """What GitHub links to one issue.

    GitHub lists only the open pull requests here, and counts both the ones that
    said they close the issue and the ones somebody linked by hand. A declined
    attempt drops out, which is what leaves its issue free to go again.
    """

    pull_requests: list[LinkedPullRequest] = Field(
        alias="closedByPullRequestsReferences"
    )


class Post(Projection):
    """Something somebody wrote on a pull request, whichever way they wrote it.

    The three sources are one document each, and this is what they have in
    common. Only the time differs in name: a review records when it was
    submitted, and a comment of either kind when it was created.

    The time is the ISO-8601 string GitHub sent, kept as a string. Every such
    string ends in a Z, so one sorts against another as text, and the relay
    compares a post against its watermark without any date arithmetic. A review
    nobody has submitted yet records no time at all, which reads here as the
    beginning of time, so it is never newer than a watermark.

    A post whose author GitHub no longer knows, one from a deleted account, is
    likewise authored by nobody, and so is nobody's to relay.

    Each of the three kinds below settles the kind for itself, and no post is
    read as this base alone.
    """

    kind: PostKind
    id: int
    author: str = Field(default="", validation_alias=AliasPath("user", "login"))
    written_at: str = Field(
        default="", validation_alias=AliasChoices("created_at", "submitted_at")
    )
    body: str = ""

    @property
    def is_speaking(self) -> bool:
        """Whether the author said anything in this post."""
        return bool(self.body)


class Comment(Post):
    """A comment on the pull request's own conversation."""

    kind: Literal[PostKind.COMMENT] = PostKind.COMMENT


class Review(Post):
    """A review somebody submitted, and the verdict that it carried."""

    kind: Literal[PostKind.REVIEW] = PostKind.REVIEW
    verdict: Verdict = Field(alias="state")

    @property
    def is_speaking(self) -> bool:
        """Whether the author said anything in this review.

        GitHub wraps every inline comment in a review of its own, and that
        wrapper has an empty body. So does the wrapper around a session's own
        reply on a line of the diff. A wrapper says nothing, and the comments
        it wrapped come through on their own, so an empty review with nothing
        but a COMMENTED verdict is worth nothing to the session. An approval or
        a request for changes is worth something on its own, body or no body.
        """
        return super().is_speaking or self.verdict in SPEAKING_VERDICTS


class InlineComment(Post):
    """A comment somebody left on a line of the pull request's diff.

    The lines are where the comment was written, and the hunk is the diff it
    was written against, so a suggestion over a range reaches the session with
    the text that it replaces. A comment on a whole file names no line at all.
    """

    kind: Literal[PostKind.INLINE_COMMENT] = PostKind.INLINE_COMMENT
    path: str
    side: str
    line: int | None = None
    start_line: int | None = None
    diff_hunk: str

    @model_validator(mode="before")
    @classmethod
    def _fall_back_to_the_original_lines(cls, document: Any) -> Any:
        """Read the lines the comment was written against, wherever they are.

        A commit that lands after the comment can move the code it was written
        against, or take it away. GitHub then answers no line and keeps the
        original, which is the line the comment was written against and the one
        the session has to be told about.
        """
        return document | {
            "line": document.get("line") or document.get("original_line"),
            "start_line": document.get("start_line")
            or document.get("original_start_line"),
        }


REPOSITORY = TypeAdapter(Repository)
ACCOUNT = TypeAdapter(Account)
ISSUES = TypeAdapter(list[Issue])
PULL_REQUESTS = TypeAdapter(list[PullRequest])
BLOCKERS = TypeAdapter(list[Blocker])
LINKED = TypeAdapter(Linked)
CONVERSATION = TypeAdapter(list[list[Comment]])
REVIEWS = TypeAdapter(list[list[Review]])
INLINE_COMMENTS = TypeAdapter(list[list[InlineComment]])


def identify(root: Path) -> str | Unknown:
    """Return the repository the checkout at root belongs to, as owner/name.

    gh reads the repository from the checkout's own remote, so this asks from
    inside the checkout.
    """
    answered = _read(REPOSITORY, "repo", "view", "--json", "nameWithOwner", cwd=root)
    if isinstance(answered, Unknown):
        return answered
    return answered.name_with_owner


def login() -> str | Unknown:
    """Return the login of the account gh is signed in as."""
    answered = _read(ACCOUNT, "api", "user")
    if isinstance(answered, Unknown):
        return answered
    return answered.login


def issues(repository: str, *, label: str, assignee: str) -> list[Issue] | Unknown:
    """Return the repository's open issues carrying label and assigned to assignee."""
    return _read(
        ISSUES,
        "issue",
        "list",
        "--repo",
        repository,
        "--assignee",
        assignee,
        "--label",
        label,
        "--state",
        "open",
        "--limit",
        LISTING_LIMIT,
        "--json",
        "number,createdAt",
    )


def pull_requests(repository: str, branch: str) -> list[PullRequest] | Unknown:
    """Return the pull requests branch is the head of, whatever state each is in.

    A branch usually has one, and an empty list means it has none. Which of
    several counts is the caller's rule, not this read's.
    """
    return _read(
        PULL_REQUESTS,
        "pr",
        "list",
        "--repo",
        repository,
        "--head",
        branch,
        "--state",
        "all",
        "--json",
        "number,state",
    )


def linked_pull_requests(
    repository: str, issue: int
) -> list[LinkedPullRequest] | Unknown:
    """Return the open pull requests GitHub links to this issue.

    This is how the tool knows an issue is claimed when no worktree here says
    so, which is the state a second checkout of the same repository is always
    in.
    """
    answered = _read(
        LINKED,
        "issue",
        "view",
        str(issue),
        "--repo",
        repository,
        "--json",
        "closedByPullRequestsReferences",
    )
    if isinstance(answered, Unknown):
        return answered
    return answered.pull_requests


def blockers(repository: str, issue: int) -> list[Blocker] | Unknown:
    """Return the issues blocking this one, each with its own state.

    This reads the one page GitHub answers with, so an issue with more than
    thirty blockers would keep the rest out of view.
    """
    return _read(
        BLOCKERS, "api", f"repos/{repository}/issues/{issue}/dependencies/blocked_by"
    )


def posts(repository: str, pull_request: int) -> list[Post] | Unknown:
    """Return everything anybody posted on the pull request, from all three places.

    The three come back as one list, because somebody reading a pull request
    reads what was written on it and not three lists to reconcile. Nothing is
    left out: whose post it is, and whether it says anything, is the relay's
    rule and none of this read's business.

    A source the tool could not read answers unknown for the whole pull
    request, since the source it cannot see is the one that might hold the post
    the user is waiting for an answer to.
    """
    found: list[Post] = []
    for read_source in (_read_conversation, _read_reviews, _read_inline_comments):
        answered = read_source(repository, pull_request)
        if isinstance(answered, Unknown):
            return answered
        found.extend(answered)
    return found


def _read_conversation(repository: str, pull_request: int) -> list[Post] | Unknown:
    """Return the comments on the pull request's own conversation.

    A pull request's conversation is the conversation of the issue that shares
    its number, which is the endpoint this asks.
    """
    return _read_pages(
        CONVERSATION, f"repos/{repository}/issues/{pull_request}/comments"
    )


def _read_reviews(repository: str, pull_request: int) -> list[Post] | Unknown:
    """Return the reviews somebody submitted on the pull request."""
    return _read_pages(REVIEWS, f"repos/{repository}/pulls/{pull_request}/reviews")


def _read_inline_comments(repository: str, pull_request: int) -> list[Post] | Unknown:
    """Return the comments somebody left on a line of the pull request's diff."""
    return _read_pages(
        INLINE_COMMENTS, f"repos/{repository}/pulls/{pull_request}/comments"
    )


def _read_pages[PostT: Post](
    shape: TypeAdapter[list[list[PostT]]], path: str
) -> list[Post] | Unknown:
    """Return every post the paginated list at path holds, or Unknown.

    gh reads every page for us, and answers with one array for each page it
    read, so the pages join back into one list here.
    """
    answered = _read(
        shape, "api", f"{path}?per_page={PAGE_SIZE}", "--paginate", "--slurp"
    )
    if isinstance(answered, Unknown):
        return answered
    found: list[Post] = []
    for page in answered:
        found.extend(page)
    return found


def _read[ReadT](
    shape: TypeAdapter[ReadT], *arguments: str, cwd: Path | None = None
) -> ReadT | Unknown:
    """Return what gh answered, read into shape, or Unknown when the read failed.

    A read fails in two ways: gh itself fails, or it answers something the shape
    cannot hold. Both answer Unknown, so neither reaches a caller as data.
    """
    try:
        answered = run("gh", *arguments, cwd=cwd)
    except CommandError as error:
        return Unknown(str(error))
    try:
        return shape.validate_json(answered)
    except ValidationError as error:
        return Unknown(f"gh answered what dreamcatcher cannot read: {error}")
