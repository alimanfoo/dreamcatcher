"""Operate on GitHub data through the gh command-line client."""

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
    field_validator,
    model_validator,
)

from dreamcatcher.commands import CommandError, run_command

# gh lists thirty of anything unless you tell it otherwise, and thirty issues is
# a number a busy repository passes. Asking for five hundred keeps the tool from
# dropping work it can see. Only the issue listing needs it: a branch has one
# pull request, near enough, and thirty is beyond any real count of blockers.
ISSUE_LISTING_LIMIT = "500"

# How many of a paginated list to ask GitHub for at a time. gh reads every page
# whatever the size, so the largest page GitHub allows is the fewest calls for
# the same answer.
GITHUB_PAGE_SIZE = "100"


@dataclass(frozen=True, kw_only=True)
class UnknownGitHubResponse:
    """Represent a GitHub read whose result is unknown.

    Every read biases the daemon toward doing nothing. A caller that gets this
    decides what not knowing means for its own check, and no read ever guesses
    on its behalf. The reason travels with it, so a tick can record why it could
    not tell.
    """

    reason: str


class GitHubResponseProjection(BaseModel):
    """Model the declared fields that Dreamcatcher reads from GitHub.

    GitHub owns the document, so a key we do not declare passes without
    complaint. That is the opposite of a DreamcatcherDocument, which refuses a
    key that it does not expect.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)


class PullRequestState(StrEnum):
    """List the pull request states that gh reports."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    MERGED = "MERGED"


class IssueState(StrEnum):
    """List the issue states that Dreamcatcher observes."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PullRequestReviewVerdict(StrEnum):
    """List the review verdicts that GitHub reports."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"


# The verdicts that say something on their own. A review carrying one of these
# is worth reading even with an empty body, and every other verdict leaves the
# body to do the talking.
SPEAKING_REVIEW_VERDICTS = frozenset(
    {
        PullRequestReviewVerdict.APPROVED,
        PullRequestReviewVerdict.CHANGES_REQUESTED,
    }
)


class GitHubRepository(GitHubResponseProjection):
    """Model the GitHub identity of a repository."""

    name_with_owner: str = Field(alias="nameWithOwner")


class GitHubUserAccount(GitHubResponseProjection):
    """Model a GitHub user account."""

    login: str


class GitHubIssueLabel(GitHubResponseProjection):
    """Model a label attached to an issue."""

    name: str


class Issue(GitHubResponseProjection):
    """Model the GitHub facts that scheduling observes about an issue."""

    number: int
    created_at: datetime = Field(alias="createdAt")
    state: IssueState
    assignees: list[GitHubUserAccount]
    labels: list[GitHubIssueLabel]


class PullRequest(GitHubResponseProjection):
    """Model a pull request and its current state."""

    number: int
    state: PullRequestState
    is_draft: bool = Field(alias="isDraft")


class BlockingIssue(GitHubResponseProjection):
    """Model an issue that blocks another issue."""

    number: int
    state: IssueState

    @field_validator("state", mode="before")
    @classmethod
    def _normalize_rest_state(cls, value: object, /) -> str:
        """Normalize the REST API's lower-case spelling at its boundary."""
        return str(value).upper()


class LinkedPullRequest(GitHubResponseProjection):
    """Model a pull request that GitHub links to an issue."""

    number: int


class LinkedPullRequestsResponse(GitHubResponseProjection):
    """Model the pull requests that GitHub links to an issue.

    GitHub lists pull requests in every state here, and counts both the ones that
    said they close the issue and the ones somebody linked by hand. The public
    read below checks their current state and returns only the open ones, so a
    declined assignment leaves its issue free to go again.
    """

    pull_requests: list[LinkedPullRequest] = Field(
        alias="closedByPullRequestsReferences"
    )


class _UserPostProjection(GitHubResponseProjection):
    """Model the fields shared by every kind of pull request post.

    A comment on the conversation, a review, and a comment on a line of the
    diff are one document each, and this is what the three have in common.
    Only the time differs in name: a review records when it was submitted, and
    a comment of either kind when it was created.

    The time stays as GitHub's ISO-8601 string. Every populated value ends in
    `Z`, so the relay can sort and compare values as text. An unsubmitted review
    has no time and therefore sorts before every delivery cursor.

    A post whose author GitHub no longer knows, one from a deleted account, is
    likewise authored by nobody, and so is nobody's to relay.

    Each concrete post names its kind because all three kinds are delivered in
    one serialized list.
    """

    id: int
    author: str = Field(default="", validation_alias=AliasPath("user", "login"))
    written_at: str = Field(
        default="", validation_alias=AliasChoices("created_at", "submitted_at")
    )
    body: str = ""

    @property
    def is_speaking(self) -> bool:
        """Whether the post has a body."""
        return bool(self.body)


class ConversationComment(_UserPostProjection):
    """Model a comment in the pull request conversation."""

    kind: Literal["comment"] = "comment"


class PullRequestReview(_UserPostProjection):
    """Model a pull request review."""

    kind: Literal["review"] = "review"
    verdict: PullRequestReviewVerdict = Field(validation_alias="state")

    @property
    def is_speaking(self) -> bool:
        """Whether the review has a body or a meaningful verdict.

        GitHub wraps every inline comment in a review of its own, and that
        wrapper has an empty body. The wrapped comments arrive separately, so a
        COMMENTED wrapper is silent. An approval or request for changes speaks
        even when its body is empty.
        """
        return super().is_speaking or self.verdict in SPEAKING_REVIEW_VERDICTS


class InlineReviewComment(_UserPostProjection):
    """Model a comment on a line, range, or file in the pull request diff.

    The diff hunk carries the commented code as well as its line numbers.

    Somebody can comment on a whole file rather than on any line of it, and
    GitHub says `file` for that one and reports it against line 1 all the
    same. The subject distinguishes that case from a comment on line 1. Older
    comments that omit the subject are line comments.
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
        """Restore the original line positions when current positions are absent.

        A commit that lands after the comment can move the code it was written
        against, or take it away. GitHub then answers no line and keeps the
        original, which is the line the comment was written against and the one
        the assignment has to be told about.

        Non-mapping input passes through so that Pydantic reports its shape.

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


type UserPost = ConversationComment | PullRequestReview | InlineReviewComment


GITHUB_REPOSITORY_RESPONSE_ADAPTER = TypeAdapter(GitHubRepository)
GITHUB_ACCOUNT_RESPONSE_ADAPTER = TypeAdapter(GitHubUserAccount)
GITHUB_ISSUE_RESPONSE_ADAPTER = TypeAdapter(Issue)
GITHUB_ISSUE_LIST_RESPONSE_ADAPTER = TypeAdapter(list[Issue])
GITHUB_PULL_REQUEST_LIST_RESPONSE_ADAPTER = TypeAdapter(list[PullRequest])
GITHUB_PULL_REQUEST_RESPONSE_ADAPTER = TypeAdapter(PullRequest)
GITHUB_BLOCKING_ISSUE_LIST_RESPONSE_ADAPTER = TypeAdapter(list[BlockingIssue])
GITHUB_LINKED_PULL_REQUESTS_RESPONSE_ADAPTER = TypeAdapter(LinkedPullRequestsResponse)
GITHUB_CONVERSATION_COMMENT_PAGES_ADAPTER = TypeAdapter(list[list[ConversationComment]])
GITHUB_PULL_REQUEST_REVIEW_PAGES_ADAPTER = TypeAdapter(list[list[PullRequestReview]])
GITHUB_INLINE_REVIEW_COMMENT_PAGES_ADAPTER = TypeAdapter(
    list[list[InlineReviewComment]]
)

# The three lists a pull request's posts arrive in: what each holds, the kind of
# thing GitHub keeps it under, and what it is called there. A pull request's own
# conversation is the conversation of the issue that shares its number, which is
# why that one is kept under the issues.
GITHUB_USER_POST_ENDPOINTS = (
    (GITHUB_CONVERSATION_COMMENT_PAGES_ADAPTER, "issues", "comments"),
    (GITHUB_PULL_REQUEST_REVIEW_PAGES_ADAPTER, "pulls", "reviews"),
    (GITHUB_INLINE_REVIEW_COMMENT_PAGES_ADAPTER, "pulls", "comments"),
)


def identify_github_repository(*, root: Path) -> str | UnknownGitHubResponse:
    """Return the checkout's repository as owner/name.

    gh reads the repository from the checkout's own remote, so this asks from
    inside the checkout.
    """
    repository_response = _read_github_response(
        response_adapter=GITHUB_REPOSITORY_RESPONSE_ADAPTER,
        arguments=["repo", "view", "--json", "nameWithOwner"],
        cwd=root,
    )
    if isinstance(repository_response, UnknownGitHubResponse):
        return repository_response
    return repository_response.name_with_owner


def identify_github_account() -> str | UnknownGitHubResponse:
    """Return the login of the account gh is signed in as."""
    account_response = _read_github_response(
        response_adapter=GITHUB_ACCOUNT_RESPONSE_ADAPTER,
        arguments=["api", "user"],
    )
    if isinstance(account_response, UnknownGitHubResponse):
        return account_response
    return account_response.login


def list_issues(
    *, repository: str, label: str, assignee: str
) -> list[Issue] | UnknownGitHubResponse:
    """Return the repository's open issues carrying label and assigned to assignee."""
    return _read_github_response(
        response_adapter=GITHUB_ISSUE_LIST_RESPONSE_ADAPTER,
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
            ISSUE_LISTING_LIMIT,
            "--json",
            "number,createdAt,state,assignees,labels",
        ],
    )


def read_issue(*, repository: str, issue: int) -> Issue | UnknownGitHubResponse:
    """Return the current GitHub facts for one issue."""
    return _read_github_response(
        response_adapter=GITHUB_ISSUE_RESPONSE_ADAPTER,
        arguments=[
            "issue",
            "view",
            str(issue),
            "--repo",
            repository,
            "--json",
            "number,createdAt,state,assignees,labels",
        ],
    )


def list_pull_requests(
    *, repository: str, branch: str
) -> list[PullRequest] | UnknownGitHubResponse:
    """Return pull requests whose head is the branch, within gh's result limit.

    A branch usually has one, and an empty list means it has none. Which of
    several counts is the caller's rule, not this read's.
    """
    return _read_github_response(
        response_adapter=GITHUB_PULL_REQUEST_LIST_RESPONSE_ADAPTER,
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
            "number,state,isDraft",
        ],
    )


def create_pull_request(
    *, repository: str, branch: str, issue: int
) -> PullRequest | UnknownGitHubResponse:
    """Open the branch's linked draft pull request and return its identity."""
    reference = run_command(
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


def read_pull_request(
    *, repository: str, pull_request: int
) -> PullRequest | UnknownGitHubResponse:
    """Return the pull request with this persisted identity."""
    return _read_pull_request(repository=repository, reference=str(pull_request))


def _read_pull_request(
    *, repository: str, reference: str
) -> PullRequest | UnknownGitHubResponse:
    """Return one pull request named by a number or URL."""
    return _read_github_response(
        response_adapter=GITHUB_PULL_REQUEST_RESPONSE_ADAPTER,
        arguments=[
            "pr",
            "view",
            reference,
            "--repo",
            repository,
            "--json",
            "number,state,isDraft",
        ],
    )


def list_linked_pull_requests(
    *, repository: str, issue: int
) -> list[LinkedPullRequest] | UnknownGitHubResponse:
    """Return the open pull requests that GitHub links to the issue.

    This is how the tool knows an issue is claimed when no worktree here says
    so, which is the state a second checkout of the same repository is always
    in.
    """
    linked_response = _read_github_response(
        response_adapter=GITHUB_LINKED_PULL_REQUESTS_RESPONSE_ADAPTER,
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
    if isinstance(linked_response, UnknownGitHubResponse):
        return linked_response
    open_pull_requests = []
    for linked_pull_request in linked_response.pull_requests:
        pull_request = read_pull_request(
            repository=repository, pull_request=linked_pull_request.number
        )
        if isinstance(pull_request, UnknownGitHubResponse):
            return pull_request
        if pull_request.state is PullRequestState.OPEN:
            open_pull_requests.append(linked_pull_request)
    return open_pull_requests


def list_blocking_issues(
    *, repository: str, issue: int
) -> list[BlockingIssue] | UnknownGitHubResponse:
    """Return the issues that block this issue, including their states.

    This reads the one page GitHub answers with, so an issue with more than
    thirty blockers would keep the rest out of view.
    """
    return _read_github_response(
        response_adapter=GITHUB_BLOCKING_ISSUE_LIST_RESPONSE_ADAPTER,
        arguments=[
            "api",
            f"repos/{repository}/issues/{issue}/dependencies/blocked_by",
        ],
    )


def list_user_posts(
    *, repository: str, pull_request: int
) -> list[UserPost] | UnknownGitHubResponse:
    """Return every conversation comment, review, and inline comment.

    The relay decides which posts from the combined list to deliver.

    A source the tool could not read answers unknown for the whole pull
    request, since the source it cannot see is the one that might hold the post
    the user is waiting for an answer to.
    """
    user_posts: list[UserPost] = []
    for response_adapter, resource_kind, collection_name in GITHUB_USER_POST_ENDPOINTS:
        endpoint = (
            f"repos/{repository}/{resource_kind}/{pull_request}/{collection_name}"
        )
        page_response = _read_github_pages(
            response_adapter=response_adapter, endpoint=endpoint
        )
        if isinstance(page_response, UnknownGitHubResponse):
            return page_response
        user_posts.extend(page_response)
    return user_posts


def _read_github_pages[PostT: UserPost](
    *, response_adapter: TypeAdapter[list[list[PostT]]], endpoint: str
) -> list[UserPost] | UnknownGitHubResponse:
    """Return every post from the paginated endpoint, or an unknown response.

    gh reads every page for us, and answers with one array for each page it
    read, so the pages join back into one list here.
    """
    page_response = _read_github_response(
        response_adapter=response_adapter,
        arguments=[
            "api",
            f"{endpoint}?per_page={GITHUB_PAGE_SIZE}",
            "--paginate",
            "--slurp",
        ],
    )
    if isinstance(page_response, UnknownGitHubResponse):
        return page_response
    return list(chain.from_iterable(page_response))


def _read_github_response[ReadT](
    *,
    response_adapter: TypeAdapter[ReadT],
    arguments: Sequence[str],
    cwd: Path | None = None,
) -> ReadT | UnknownGitHubResponse:
    """Return validated gh output, or an unknown response when the read fails.

    A read fails in two ways: gh itself fails, or it answers something the
    response adapter cannot hold. Both answer UnknownGitHubResponse, so neither
    reaches a caller as data.
    """
    try:
        raw_response = run_command(program="gh", arguments=arguments, cwd=cwd)
    except CommandError as error:
        return UnknownGitHubResponse(reason=str(error))
    try:
        return response_adapter.validate_json(raw_response)
    except ValidationError as error:
        return UnknownGitHubResponse(
            reason=f"gh answered what dreamcatcher cannot read: {error}"
        )
