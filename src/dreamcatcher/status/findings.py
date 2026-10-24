"""Word what a scheduler tick found, once for every status that shows it."""

from collections.abc import Sequence

from dreamcatcher.github import (
    CheckResult,
    PullRequestMergeState,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import PullRequestFinding
from dreamcatcher.words import describe_count

# What each signal says, wherever a status names what woke or will wake a round.
_SIGNAL_WORDS = {
    PullRequestSignal.OUT_OF_DATE: "main moved",
    PullRequestSignal.CHECK_FAILURE: "checks failed",
}


def describe_comments_to_answer(*, count: int) -> str:
    """Say how many issue comments wait to be answered."""
    return f"{describe_count(number=count, noun='comment')} to answer"


def describe_changed_children(*, count: int) -> str:
    """Say how many of a campaign's children changed in ways the lead hears of."""
    return f"{describe_count(number=count, noun='sub-issue')} changed"


def describe_conflicting_labels(*, kind: AgentWorkKind, labels: Sequence[str]) -> str:
    """Name the labels of one kind that an issue carries together."""
    return f"multiple {kind} labels: " + ", ".join(labels)


def describe_pause(*, cause: str) -> str:
    """Say why work at an issue is paused until the cause is removed."""
    return f"paused, {cause}"


def describe_read_failure(*, reason: str) -> str:
    """Say why the tick could not tell what it needed."""
    return f"cannot tell: {reason}"


def describe_signal(*, signal: PullRequestSignal) -> str:
    """Say what a status calls a pull request signal that woke or will wake a round."""
    return _SIGNAL_WORDS[signal]


def describe_pull_request(*, finding: PullRequestFinding) -> str:
    """Say where a pull request stands.

    An open one is draft or ready, followed by how main prevents a merge and
    whether its checks are running or failing. Any other names its state alone.
    """
    if finding.state is not PullRequestState.OPEN:
        return finding.state.lower()
    words = ["ready" if finding.is_ready_for_review else "draft"]
    if finding.merge_state is PullRequestMergeState.BEHIND:
        words.append("behind main")
    elif finding.merge_state is PullRequestMergeState.DIRTY:
        words.append("conflicts with main")
    if finding.check_result in {CheckResult.RUNNING, CheckResult.FAILING}:
        words.append(f"checks {finding.check_result}")
    return ", ".join(words)


def describe_idle_pull_request(*, finding: PullRequestFinding) -> str:
    """Say where a pull request that raised nothing new has got to.

    A draft needs the user's feedback, because the agent ended its round without
    marking it ready. A ready pull request names a check failure that the relay
    rule withheld and is ready for review otherwise.
    """
    if finding.state is not PullRequestState.OPEN:
        return finding.state.lower()
    if not finding.is_ready_for_review:
        return "needs feedback"
    if finding.is_check_failure_withheld:
        return "checks failing after two attempts"
    return "ready for review"
