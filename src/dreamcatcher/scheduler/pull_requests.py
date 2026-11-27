"""Read the channel and start-time answers for pull request work."""

from collections.abc import Sequence
from dataclasses import dataclass

from dreamcatcher.agent_work import AgentWork
from dreamcatcher.github import (
    PullRequest,
    PullRequestState,
    UnknownGitHubResponse,
    UserPost,
    read_issue_pull_request_context,
    read_pull_request,
)
from dreamcatcher.pull_request_work import is_wrap_up_relayed, read_user_post_cursor
from dreamcatcher.relay import find_pull_request_signals, list_user_posts_past_cursor
from dreamcatcher.scheduler.blockers import list_open_blocking_issues
from dreamcatcher.scheduler.faults import is_last_round_unfinished
from dreamcatcher.scheduler.inspection import SchedulingContext
from dreamcatcher.scheduler.models import (
    PullRequestFinding,
    ReadFailureFinding,
    StartTimeFinding,
)


@dataclass(frozen=True, kw_only=True)
class PullRequestActivity:
    """Hold a pull request observation and the input it can give a round."""

    pull_request: PullRequest
    posts: Sequence[UserPost]
    finding: PullRequestFinding

    def is_round_due(self, *, work: AgentWork) -> bool:
        """Return whether the channel or an unfinished round calls for a round."""
        return bool(
            self.posts
            or self.finding.new_pull_request_signals
            or self.finding.is_wrap_up_due
            or is_last_round_unfinished(rounds=work.rounds, is_daemon_running=True)
        )


def read_pull_request_activity(
    *, context: SchedulingContext, work: AgentWork, pull_request: int
) -> PullRequestActivity | ReadFailureFinding:
    """Read the pull request and the posts and signals past the work's cursor."""
    read = read_pull_request(repository=context.repository, pull_request=pull_request)
    if isinstance(read, UnknownGitHubResponse):
        return ReadFailureFinding(reason=read.reason)
    posts = list_user_posts_past_cursor(
        repository=context.repository,
        pull_request=read.number,
        account=context.account,
        cursor=read_user_post_cursor(assignment=work),
    )
    if isinstance(posts, UnknownGitHubResponse):
        return ReadFailureFinding(reason=posts.reason)
    found = find_pull_request_signals(assignment=work, pull_request=read)
    finding = PullRequestFinding(
        number=read.number,
        state=read.state,
        is_draft=read.is_draft,
        merge_state=read.merge_state,
        head=read.head,
        check_result=read.check_result,
        has_running_checks=read.has_running_checks,
        new_posts=len(posts),
        new_pull_request_signals=found.new_pull_request_signals,
        is_check_failure_withheld=found.is_check_failure_withheld,
        is_wrap_up_due=(
            read.state is not PullRequestState.OPEN
            and not is_wrap_up_relayed(assignment=work)
        ),
    )
    return PullRequestActivity(pull_request=read, posts=posts, finding=finding)


def ask_start_time_questions(
    *, context: SchedulingContext, issue: int
) -> StartTimeFinding | ReadFailureFinding:
    """Return the open pull requests claiming the issue and open issues blocking it."""
    pull_request_context = read_issue_pull_request_context(
        repository=context.repository, issue=issue
    )
    if isinstance(pull_request_context, UnknownGitHubResponse):
        return ReadFailureFinding(reason=pull_request_context.reason)
    blocking = list_open_blocking_issues(context=context, issue=issue)
    if isinstance(blocking, ReadFailureFinding):
        return blocking
    return StartTimeFinding(
        linked_pull_requests=[
            pull_request.number for pull_request in pull_request_context.pull_requests
        ],
        blocking_issues=blocking,
    )
