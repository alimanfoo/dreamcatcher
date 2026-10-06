"""Operate on GitHub data through the gh command-line client."""

import json
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
from dreamcatcher.errors import ReportableError

# gh lists thirty of anything unless you tell it otherwise, and thirty issues is
# a number a busy repository passes. Asking for five hundred keeps the tool from
# dropping work it can see. Only the issue listing needs it: a branch has one
# pull request, near enough.
_ISSUE_LISTING_LIMIT = "500"

# How many of a paginated list to ask GitHub for at a time. gh reads every page
# whatever the size, so the largest page GitHub allows is the fewest calls for
# the same answer.
_GITHUB_PAGE_SIZE = "100"


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
    """Model the declared fields that dreamcatcher reads from GitHub.

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
    """List the issue states that dreamcatcher observes."""

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
_SPEAKING_REVIEW_VERDICTS = frozenset(
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
    title: str
    body: str = ""
    created_at: datetime = Field(alias="createdAt")
    state: IssueState
    assignees: list[GitHubUserAccount]
    labels: list[GitHubIssueLabel]


_ISSUE_RESPONSE_FIELDS = ",".join(
    field.alias or name for name, field in Issue.model_fields.items()
)


class PullRequest(GitHubResponseProjection):
    """Model a pull request and its current state."""

    number: int
    state: PullRequestState
    is_draft: bool = Field(alias="isDraft")

    @property
    def is_open(self) -> bool:
        """Whether the pull request is open."""
        return self.state is PullRequestState.OPEN


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


class IssuePullRequestContext(GitHubResponseProjection):
    """Model the issue facts needed to reconcile or create a pull request.

    GitHub lists pull requests in every state here, and counts both the ones that
    said they close the issue and the ones somebody linked by hand. The public
    read below checks their current state and returns only the open ones, so a
    declined assignment leaves its issue free to go again.
    """

    issue: int = Field(alias="number")
    title: str
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
    has no time and therefore sorts before every delivery position.

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
    """Model an ordinary comment in an issue or pull request conversation."""

    kind: Literal["comment"] = "comment"


class PostedIssueComment(GitHubResponseProjection):
    """Identify an issue comment that GitHub accepted."""

    id: int


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
        return super().is_speaking or self.verdict in _SPEAKING_REVIEW_VERDICTS


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


_GITHUB_REPOSITORY_RESPONSE_ADAPTER = TypeAdapter(GitHubRepository)
_GITHUB_ACCOUNT_RESPONSE_ADAPTER = TypeAdapter(GitHubUserAccount)
_GITHUB_ISSUE_RESPONSE_ADAPTER = TypeAdapter(Issue)
_GITHUB_ISSUE_LIST_RESPONSE_ADAPTER = TypeAdapter(list[Issue])
_GITHUB_PULL_REQUEST_LIST_RESPONSE_ADAPTER = TypeAdapter(list[PullRequest])
_GITHUB_PULL_REQUEST_RESPONSE_ADAPTER = TypeAdapter(PullRequest)
_GITHUB_BLOCKING_ISSUE_LIST_RESPONSE_ADAPTER = TypeAdapter(list[list[BlockingIssue]])
_GITHUB_ISSUE_PULL_REQUEST_CONTEXT_RESPONSE_ADAPTER = TypeAdapter(
    IssuePullRequestContext
)
_GITHUB_CONVERSATION_COMMENT_PAGES_ADAPTER = TypeAdapter(
    list[list[ConversationComment]]
)
_GITHUB_POSTED_ISSUE_COMMENT_ADAPTER = TypeAdapter(PostedIssueComment)
_GITHUB_PULL_REQUEST_REVIEW_PAGES_ADAPTER = TypeAdapter(list[list[PullRequestReview]])
_GITHUB_INLINE_REVIEW_COMMENT_PAGES_ADAPTER = TypeAdapter(
    list[list[InlineReviewComment]]
)

# The three lists a pull request's posts arrive in: what each holds, the kind of
# thing GitHub keeps it under, and what it is called there. A pull request's own
# conversation is the conversation of the issue that shares its number, which is
# why that one is kept under the issues.
_GITHUB_USER_POST_ENDPOINTS = (
    (_GITHUB_CONVERSATION_COMMENT_PAGES_ADAPTER, "issues", "comments"),
    (_GITHUB_PULL_REQUEST_REVIEW_PAGES_ADAPTER, "pulls", "reviews"),
    (_GITHUB_INLINE_REVIEW_COMMENT_PAGES_ADAPTER, "pulls", "comments"),
)


def _identify_github_repository(*, root: Path) -> str | UnknownGitHubResponse:
    """Return the checkout's repository as owner/name.

    gh reads the repository from the checkout's own remote, so this asks from
    inside the checkout.
    """
    repository_response = _read_github_response(
        response_adapter=_GITHUB_REPOSITORY_RESPONSE_ADAPTER,
        arguments=["repo", "view", "--json", "nameWithOwner"],
        cwd=root,
    )
    if isinstance(repository_response, UnknownGitHubResponse):
        return repository_response
    return repository_response.name_with_owner


def _identify_github_account() -> str | UnknownGitHubResponse:
    """Return the login of the account gh is signed in as."""
    account_response = _read_github_response(
        response_adapter=_GITHUB_ACCOUNT_RESPONSE_ADAPTER,
        arguments=["api", "user"],
    )
    if isinstance(account_response, UnknownGitHubResponse):
        return account_response
    return account_response.login


@dataclass(frozen=True, kw_only=True)
class GitHubIdentity:
    """Name the checkout's repository and the account gh is signed in as."""

    repository: str
    account: str


def require_github_identity(*, root: Path) -> GitHubIdentity:
    """Return the identity of the checkout at root, or refuse saying what is unknown.

    Nothing can be done for a repository that gh cannot name, or as an account
    gh is not signed in as, so not knowing either one is a ReportableError.
    """
    repository = _identify_github_repository(root=root)
    if isinstance(repository, UnknownGitHubResponse):
        raise ReportableError(
            f"dreamcatcher cannot tell which repository this is: {repository.reason}"
        )
    account = _identify_github_account()
    if isinstance(account, UnknownGitHubResponse):
        raise ReportableError(
            "dreamcatcher cannot tell which account gh is signed in as: "
            f"{account.reason}"
        )
    return GitHubIdentity(repository=repository, account=account)


def list_issues(
    *, repository: str, label: str, assignee: str
) -> list[Issue] | UnknownGitHubResponse:
    """Return the repository's open issues carrying label and assigned to assignee."""
    return _read_github_response(
        response_adapter=_GITHUB_ISSUE_LIST_RESPONSE_ADAPTER,
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
            _ISSUE_LISTING_LIMIT,
            "--json",
            _ISSUE_RESPONSE_FIELDS,
        ],
    )


def read_issue(*, repository: str, issue: int) -> Issue | UnknownGitHubResponse:
    """Return the current GitHub facts for one issue."""
    return _read_github_response(
        response_adapter=_GITHUB_ISSUE_RESPONSE_ADAPTER,
        arguments=[
            "issue",
            "view",
            str(issue),
            "--repo",
            repository,
            "--json",
            _ISSUE_RESPONSE_FIELDS,
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
        response_adapter=_GITHUB_PULL_REQUEST_LIST_RESPONSE_ADAPTER,
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
    *, repository: str, branch: str, context: IssuePullRequestContext
) -> PullRequest | UnknownGitHubResponse:
    """Open the branch's linked draft pull request and return its identity.

    An unknown response means that creation succeeded but the pull request's
    identity could not be read.
    """
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
            context.title,
            "--body",
            f"Closes #{context.issue}",
        ],
    ).strip()
    pull_request = _read_pull_request(repository=repository, reference=reference)
    if isinstance(pull_request, UnknownGitHubResponse):
        return UnknownGitHubResponse(
            reason=f"created the pull request for {branch} but cannot read it: "
            f"{pull_request.reason}"
        )
    return pull_request


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
        response_adapter=_GITHUB_PULL_REQUEST_RESPONSE_ADAPTER,
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


def read_issue_pull_request_context(
    *, repository: str, issue: int
) -> IssuePullRequestContext | UnknownGitHubResponse:
    """Return the issue title and its open linked pull requests.

    This is how the tool knows an issue is claimed when no worktree here says
    so, which is the state a second checkout of the same repository is always
    in.
    """
    linked_response = _read_github_response(
        response_adapter=_GITHUB_ISSUE_PULL_REQUEST_CONTEXT_RESPONSE_ADAPTER,
        arguments=[
            "issue",
            "view",
            str(issue),
            "--repo",
            repository,
            "--json",
            "number,title,closedByPullRequestsReferences",
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
    return linked_response.model_copy(update={"pull_requests": open_pull_requests})


def list_blocking_issues(
    *, repository: str, issue: int
) -> list[BlockingIssue] | UnknownGitHubResponse:
    """Return the issues that block this issue, including their states."""
    return _read_github_pages(
        response_adapter=_GITHUB_BLOCKING_ISSUE_LIST_RESPONSE_ADAPTER,
        endpoint=f"repos/{repository}/issues/{issue}/dependencies/blocked_by",
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
    for response_adapter, resource_kind, collection_name in _GITHUB_USER_POST_ENDPOINTS:
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


def list_issue_comments(
    *, repository: str, issue: int
) -> list[ConversationComment] | UnknownGitHubResponse:
    """Return every ordinary comment on one issue."""
    return _read_github_pages(
        response_adapter=_GITHUB_CONVERSATION_COMMENT_PAGES_ADAPTER,
        endpoint=f"repos/{repository}/issues/{issue}/comments",
    )


def post_issue_comment(
    *, repository: str, issue: int, body: str
) -> PostedIssueComment | UnknownGitHubResponse:
    """Post one comment on an issue and return its GitHub identity."""
    return _read_github_response(
        response_adapter=_GITHUB_POSTED_ISSUE_COMMENT_ADAPTER,
        arguments=[
            "api",
            f"repos/{repository}/issues/{issue}/comments",
            "--method",
            "POST",
            "--input",
            "-",
        ],
        stdin=json.dumps({"body": body}),
    )


def _read_github_pages[ItemT](
    *, response_adapter: TypeAdapter[list[list[ItemT]]], endpoint: str
) -> list[ItemT] | UnknownGitHubResponse:
    """Return every item from the paginated endpoint, or an unknown response.

    gh reads every page for us, and answers with one array for each page it
    read, so the pages join back into one list here.
    """
    page_response = _read_github_response(
        response_adapter=response_adapter,
        arguments=[
            "api",
            f"{endpoint}?per_page={_GITHUB_PAGE_SIZE}",
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
    stdin: str | None = None,
) -> ReadT | UnknownGitHubResponse:
    """Return validated gh output, or an unknown response when the read fails.

    A read fails in two ways: gh itself fails, or it answers something the
    response adapter cannot hold. Both answer UnknownGitHubResponse, so neither
    reaches a caller as data.
    """
    try:
        raw_response = run_command(
            program="gh", arguments=arguments, cwd=cwd, stdin=stdin
        )
    except CommandError as error:
        return UnknownGitHubResponse(reason=str(error))
    try:
        return response_adapter.validate_json(raw_response)
    except ValidationError as error:
        return UnknownGitHubResponse(
            reason=f"gh answered what dreamcatcher cannot read: {error}"
        )
