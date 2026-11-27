"""Word what a scheduler tick found, once for every status that shows it."""

from collections.abc import Sequence
from dataclasses import dataclass

from dreamcatcher.github import (
    CheckResult,
    IssueState,
    PullRequestMergeState,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import (
    CampaignPullRequestUnavailableFinding,
    HoldFinding,
    IssueCommentsFinding,
    IssueReference,
    LabelAppliedByOtherFinding,
    PauseCause,
    PausedFinding,
    PullRequestFinding,
    RequestConsumedFinding,
    RequestFinding,
)
from dreamcatcher.words import describe_count

# What GitHub says of an issue whose work the user paused, and what resumes it.
_PAUSE_WORDS = {
    PauseCause.LABEL_REMOVED: ("label removed", "put the label back to resume"),
    PauseCause.ISSUE_UNASSIGNED: (
        "unassigned",
        "assign the issue to yourself to resume",
    ),
}

# What each signal says, wherever a status names what woke or will wake a round.
_SIGNAL_WORDS = {
    PullRequestSignal.OUT_OF_DATE: "out of date",
    PullRequestSignal.CHECK_FAILURE: "checks failed",
}


@dataclass(frozen=True, kw_only=True)
class IssueFact:
    """Say one thing that GitHub holds about an issue that _dreamcatcher_ acts on.

    A fact names the pull requests it refers to as numbers, and the issues
    by references that name another repository where one holds the issue.
    """

    words: str
    issues: Sequence[IssueReference] = ()
    pull_requests: Sequence[int] = ()


def describe_hold(
    *,
    finding: HoldFinding,
    kind: AgentWorkKind,
) -> tuple[IssueFact, str | None]:
    """Say what holds work back and give any advice for the user.

    An empty applier is an account that GitHub does not name.
    """
    if isinstance(finding, PausedFinding):
        words, advice = _PAUSE_WORDS[finding.cause]
        return IssueFact(words=words), advice
    if isinstance(finding, LabelAppliedByOtherFinding):
        applier = finding.applier or "an unknown account"
        return (
            IssueFact(words=f"labelled by {applier}"),
            "remove and re-add the label yourself",
        )
    if isinstance(finding, RequestConsumedFinding):
        return (
            IssueFact(words="label's request already used"),
            "remove and re-add the label for another attempt",
        )
    if isinstance(finding, CampaignPullRequestUnavailableFinding):
        return (
            IssueFact(
                words="no campaign pull request available for", issues=(finding.parent,)
            ),
            None,
        )
    return (
        IssueFact(words=f"multiple {kind} labels"),
        "remove all but one: " + ", ".join(finding.labels),
    )


def describe_comments_to_answer(*, count: int) -> str:
    """Say how many issue comments wait to be answered."""
    return f"{describe_count(number=count, noun='comment')} to answer"


def describe_changed_children(*, count: int) -> str:
    """Say how many of a campaign's children changed in ways the lead hears of."""
    return f"{describe_count(number=count, noun='sub-issue')} changed"


def describe_issue_state(*, state: IssueState) -> str:
    """Say whether an issue is open or closed."""
    return state.lower()


def describe_signal(*, signal: PullRequestSignal) -> str:
    """Say what a status calls a pull request signal that woke or will wake a round."""
    return _SIGNAL_WORDS[signal]


def describe_pull_request(*, finding: PullRequestFinding) -> str:
    """Say where a pull request stands.

    An open one is draft or ready, followed by how its base prevents a merge and
    whether its checks are running or failing. Any other names its state alone.
    """
    if finding.state is not PullRequestState.OPEN:
        return finding.state.lower()
    words = ["ready" if finding.is_ready_for_review else "draft"]
    if finding.merge_state is PullRequestMergeState.BEHIND:
        words.append("behind")
    elif finding.merge_state is PullRequestMergeState.DIRTY:
        words.append("conflicts")
    if finding.check_result in {CheckResult.RUNNING, CheckResult.FAILING}:
        words.append(f"checks {finding.check_result}")
    return ", ".join(words)


def describe_idle_pull_request(
    *, finding: PullRequestFinding, kind: AgentWorkKind
) -> str:
    """Say where a pull request that raised nothing new has got to.

    A coordinating lead waits for feedback or sub-issue changes. A draft
    assignment needs feedback. A ready pull request names a check failure that
    the relay rule withheld and is ready for review otherwise.
    """
    if finding.state is not PullRequestState.OPEN:
        return finding.state.lower()
    if _is_coordinating_campaign(finding=finding, kind=kind):
        return "awaiting feedback or sub-issue changes"
    if finding.is_draft:
        return "needs feedback"
    if finding.is_check_failure_withheld:
        return "checks failing after two attempts"
    return "ready for review"


def describe_new_input(
    *, finding: RequestFinding | None, kind: AgentWorkKind
) -> str | None:
    """Describe what the latest tick found that makes a round due.

    A merged or closed pull request awaits its wrap-up round before any other
    news.
    """
    if isinstance(finding, IssueCommentsFinding) and finding.new_comments:
        return describe_comments_to_answer(count=finding.new_comments)
    if not isinstance(finding, PullRequestFinding):
        return None
    if finding.is_wrap_up_due:
        return "awaiting wrap-up"
    words = [
        describe_signal(signal=signal) for signal in finding.new_pull_request_signals
    ]
    if finding.new_posts:
        posts = describe_count(number=finding.new_posts, noun="new post")
        action = (
            "for the lead"
            if _is_coordinating_campaign(finding=finding, kind=kind)
            else "to answer"
        )
        words.insert(0, f"{posts} {action}")
    if finding.changed_children:
        words.append(describe_changed_children(count=finding.changed_children))
    return ", ".join(words) or None


def _is_coordinating_campaign(
    *, finding: PullRequestFinding, kind: AgentWorkKind
) -> bool:
    return (
        kind is AgentWorkKind.CAMPAIGN
        and finding.state is PullRequestState.OPEN
        and finding.is_draft
    )
