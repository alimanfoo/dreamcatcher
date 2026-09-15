"""Ask gh what GitHub knows about the repository dreamcatcher watches."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import chain
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


@dataclass(frozen=True, kw_only=True)
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
    assignment drops out, which is what leaves its issue free to go again.
    """

    pull_requests: list[LinkedPullRequest] = Field(
        alias="closedByPullRequestsReferences"
    )


class Post(Projection):
    """Something somebody wrote on a pull request, whichever way they wrote it.

    A comment on the conversation, a review, and a comment on a line of the
    diff are one document each, and this is what the three have in common.
    Only the time differs in name: a review records when it was submitted, and
    a comment of either kind when it was created.

    The time is the ISO-8601 string GitHub sent, kept as a string. Every such
    string ends in a Z, so one sorts against another as text, and the relay
    compares a post against its watermark without any date arithmetic. A review
    nobody has submitted yet records no time at all, which reads here as the
    beginning of time, so it is never newer than a watermark.

    A post whose author GitHub no longer knows, one from a deleted account, is
    likewise authored by nobody, and so is nobody's to relay.

    Each of the three kinds below is a class of its own, and no post is read as
    this base alone. Each also names its own kind, because the three reach a
    assignment as one list, written to a file where the class no longer says which
    is which.
    """

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

    kind: Literal["comment"] = "comment"


class Review(Post):
    """A review somebody submitted, and the verdict that it carried."""

    kind: Literal["review"] = "review"
    verdict: Verdict = Field(alias="state")

    @property
    def is_speaking(self) -> bool:
        """Whether the author said anything in this review.

        GitHub wraps every inline comment in a review of its own, and that
        wrapper has an empty body. So does the wrapper around an assignment's own
        reply on a line of the diff. A wrapper says nothing, and the comments
        it wrapped come through on their own, so an empty review with nothing
        but a COMMENTED verdict is worth nothing to the assignment. An approval or
        a request for changes is worth something on its own, body or no body.
        """
        return super().is_speaking or self.verdict in SPEAKING_VERDICTS


class InlineComment(Post):
    """A comment somebody left on a line of the pull request's diff.

    The lines are where the comment was written, and the hunk is the piece of
    the diff those lines sit in. So a comment on a range of lines reaches the
    assignment with the lines themselves, and not with their numbers alone, which
    is what a comment proposing a replacement for them needs.

    Somebody can comment on a whole file rather than on any line of it, and
    GitHub says `file` for that one and reports it against line 1 all the
    same. So the subject is what tells an assignment that the user picked the file
    and not that line. GitHub says `line` for every other comment, and an old
    comment that says nothing at all named a line, which is what it reads as.
    """

    kind: Literal["inlineComment"] = "inlineComment"
    path: str
    subject_type: str = "line"
    side: str
    line: int | None = None
    start_line: int | None = None
    diff_hunk: str

    @model_validator(mode="before")
    @classmethod
    def _fall_back_to_the_original_lines(cls, document: Any, /) -> Any:
        """Read the lines the comment was written against, wherever they are.

        A commit that lands after the comment can move the code it was written
        against, or take it away. GitHub then answers no line and keeps the
        original, which is the line the comment was written against and the one
        the assignment has to be told about.

        Anything that is not a document at all passes straight through, so
        pydantic is what says why it cannot be read.

        pydantic is also what calls this, and it passes the document
        positionally, so the parameter is positional-only.
        """
        if not isinstance(document, dict):
            return document
        return document | {
            "line": document.get("line") or document.get("original_line"),
            "start_line": document.get("start_line")
            or document.get("original_start_line"),
        }


# Every kind of post a pull request carries. The three read back as themselves,
# so a batch written to a round's inbox keeps what each one is.
type AnyPost = Comment | Review | InlineComment


REPOSITORY = TypeAdapter(Repository)
ACCOUNT = TypeAdapter(Account)
ISSUES = TypeAdapter(list[Issue])
PULL_REQUESTS = TypeAdapter(list[PullRequest])
PULL_REQUEST = TypeAdapter(PullRequest)
BLOCKERS = TypeAdapter(list[Blocker])
LINKED = TypeAdapter(Linked)
CONVERSATION = TypeAdapter(list[list[Comment]])
REVIEWS = TypeAdapter(list[list[Review]])
INLINE_COMMENTS = TypeAdapter(list[list[InlineComment]])

# The three lists a pull request's posts arrive in: what each holds, the kind of
# thing GitHub keeps it under, and what it is called there. A pull request's own
# conversation is the conversation of the issue that shares its number, which is
# why that one is kept under the issues.
POST_LISTS = (
    (CONVERSATION, "issues", "comments"),
    (REVIEWS, "pulls", "reviews"),
    (INLINE_COMMENTS, "pulls", "comments"),
)


def identify_repository(*, root: Path) -> str | Unknown:
    """Return the repository the checkout at root belongs to, as owner/name.

    gh reads the repository from the checkout's own remote, so this asks from
    inside the checkout.
    """
    answered = _read(
        shape=REPOSITORY,
        arguments=["repo", "view", "--json", "nameWithOwner"],
        cwd=root,
    )
    if isinstance(answered, Unknown):
        return answered
    return answered.name_with_owner


def identify_account() -> str | Unknown:
    """Return the login of the account gh is signed in as."""
    answered = _read(shape=ACCOUNT, arguments=["api", "user"])
    if isinstance(answered, Unknown):
        return answered
    return answered.login


def list_issues(*, repository: str, label: str, assignee: str) -> list[Issue] | Unknown:
    """Return the repository's open issues carrying label and assigned to assignee."""
    return _read(
        shape=ISSUES,
        arguments=[
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
        ],
    )


def list_pull_requests(*, repository: str, branch: str) -> list[PullRequest] | Unknown:
    """Return the pull requests branch is the head of, whatever state each is in.

    A branch usually has one, and an empty list means it has none. Which of
    several counts is the caller's rule, not this read's.
    """
    return _read(
        shape=PULL_REQUESTS,
        arguments=[
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
        ],
    )


def create_pull_request(
    *, repository: str, branch: str, issue: int
) -> PullRequest | Unknown:
    """Open the branch's linked draft pull request and return its identity."""
    reference = run(
        program="gh",
        arguments=[
            "pr",
            "create",
            "--repo",
            repository,
            "--base",
            "main",
            "--head",
            branch,
            "--draft",
            "--title",
            f"GH{issue}",
            "--body",
            f"Closes #{issue}",
        ],
    ).strip()
    return _read_pull_request(repository=repository, reference=reference)


def read_pull_request(*, repository: str, pull_request: int) -> PullRequest | Unknown:
    """Return the pull request with this persisted identity."""
    return _read_pull_request(repository=repository, reference=str(pull_request))


def _read_pull_request(*, repository: str, reference: str) -> PullRequest | Unknown:
    """Return one pull request named by a number or URL."""
    return _read(
        shape=PULL_REQUEST,
        arguments=[
            "pr",
            "view",
            reference,
            "--repo",
            repository,
            "--json",
            "number,state",
        ],
    )


def list_linked_pull_requests(
    *, repository: str, issue: int
) -> list[LinkedPullRequest] | Unknown:
    """Return the open pull requests GitHub links to this issue.

    This is how the tool knows an issue is claimed when no worktree here says
    so, which is the state a second checkout of the same repository is always
    in.
    """
    answered = _read(
        shape=LINKED,
        arguments=[
            "issue",
            "view",
            str(issue),
            "--repo",
            repository,
            "--json",
            "closedByPullRequestsReferences",
        ],
    )
    if isinstance(answered, Unknown):
        return answered
    return answered.pull_requests


def list_blockers(*, repository: str, issue: int) -> list[Blocker] | Unknown:
    """Return the issues blocking this one, each with its own state.

    This reads the one page GitHub answers with, so an issue with more than
    thirty blockers would keep the rest out of view.
    """
    return _read(
        shape=BLOCKERS,
        arguments=[
            "api",
            f"repos/{repository}/issues/{issue}/dependencies/blocked_by",
        ],
    )


def list_posts(*, repository: str, pull_request: int) -> list[AnyPost] | Unknown:
    """Return everything anybody posted on the pull request, from all three places.

    The three come back as one list, because somebody reading a pull request
    reads what was written on it and not three lists to reconcile. Nothing is
    left out: whose post it is, and whether the assignment has heard it already,
    is the relay's rule and none of this read's business.

    A source the tool could not read answers unknown for the whole pull
    request, since the source it cannot see is the one that might hold the post
    the user is waiting for an answer to.
    """
    found: list[AnyPost] = []
    for shape, under, listed in POST_LISTS:
        path = f"repos/{repository}/{under}/{pull_request}/{listed}"
        answered = _read_pages(shape=shape, path=path)
        if isinstance(answered, Unknown):
            return answered
        found.extend(answered)
    return found


def _read_pages[PostT: AnyPost](
    *, shape: TypeAdapter[list[list[PostT]]], path: str
) -> list[AnyPost] | Unknown:
    """Return every post the paginated list at path holds, or Unknown.

    gh reads every page for us, and answers with one array for each page it
    read, so the pages join back into one list here.
    """
    answered = _read(
        shape=shape,
        arguments=["api", f"{path}?per_page={PAGE_SIZE}", "--paginate", "--slurp"],
    )
    if isinstance(answered, Unknown):
        return answered
    found: list[AnyPost] = list(chain.from_iterable(answered))
    return found


def _read[ReadT](
    *,
    shape: TypeAdapter[ReadT],
    arguments: Sequence[str],
    cwd: Path | None = None,
) -> ReadT | Unknown:
    """Return what gh answered, read into shape, or Unknown when the read failed.

    A read fails in two ways: gh itself fails, or it answers something the shape
    cannot hold. Both answer Unknown, so neither reaches a caller as data.
    """
    try:
        answered = run(program="gh", arguments=arguments, cwd=cwd)
    except CommandError as error:
        return Unknown(reason=str(error))
    try:
        return shape.validate_json(answered)
    except ValidationError as error:
        return Unknown(reason=f"gh answered what dreamcatcher cannot read: {error}")
