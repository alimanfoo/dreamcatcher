"""Ask gh what GitHub knows about the repository dreamcatcher watches."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from dreamcatcher.commands import CommandError, run

# gh lists thirty of anything unless you tell it otherwise, and thirty issues is
# a number a busy repository passes. Asking for five hundred keeps the tool from
# dropping work it can see. Only the issue listing needs it: a branch has one
# pull request, near enough, and thirty is beyond any real count of blockers.
LISTING_LIMIT = "500"


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


REPOSITORY = TypeAdapter(Repository)
ACCOUNT = TypeAdapter(Account)
ISSUES = TypeAdapter(list[Issue])
PULL_REQUESTS = TypeAdapter(list[PullRequest])
BLOCKERS = TypeAdapter(list[Blocker])
LINKED = TypeAdapter(Linked)


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
