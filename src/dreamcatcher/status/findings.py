"""Word what a scheduler tick found, once for every status that shows it."""

from dreamcatcher.github import (
    CheckResult,
    PullRequestSignal,
    PullRequestState,
)
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import PullRequestFinding
from dreamcatcher.words import describe_count

# What each signal says, wherever a status names what woke or will wake a round.
_SIGNAL_WORDS = {
    PullRequestSignal.OUT_OF_DATE: "out of date",
    PullRequestSignal.CHECK_FAILURE: "checks failed",
}


def describe_comments_to_answer(*, count: int) -> str:
    """Say how many issue comments wait to be answered."""
    return f"{describe_count(number=count, noun='comment')} to answer"


def describe_conflicting_labels(*, kind: AgentWorkKind, labels: list[str]) -> str:
    """Name the labels of one kind that an issue carries together."""
    return f"multiple {kind} labels: " + ", ".join(labels)


def describe_pause(*, cause: str) -> str:
    """Say why a conversation is paused until the cause is removed."""
    return f"paused, {cause}"


def describe_read_failure(*, reason: str) -> str:
    """Say why the tick could not tell what it needed."""
    return f"cannot tell: {reason}"


def describe_signal(*, signal: PullRequestSignal) -> str:
    """Say what a pull request signal tells the agent."""
    return _SIGNAL_WORDS[signal]


def describe_pull_request(*, finding: PullRequestFinding) -> str:
    """Say where a pull request stands.

    An open one is draft or ready, followed by whether it is out of date and
    whether its checks are running or failing. Any other names its state alone.
    """
    if finding.state is not PullRequestState.OPEN:
        return finding.state.lower()
    words = ["draft" if finding.is_draft else "ready"]
    if finding.merge_state.is_out_of_date:
        words.append("out of date")
    if finding.check_result in {CheckResult.RUNNING, CheckResult.FAILING}:
        words.append(f"checks {finding.check_result}")
    return ", ".join(words)


def describe_idle_pull_request(*, finding: PullRequestFinding) -> str:
    """Say where a pull request that raised nothing new has got to.

    A ready pull request names the first that holds of a check failure that the
    relay rule withheld, out of date, failing checks and running checks, and is
    ready for review otherwise.
    """
    if finding.state is not PullRequestState.OPEN:
        return finding.state.lower()
    if finding.is_draft:
        return "draft"
    return next(
        words
        for holds, words in (
            (finding.is_check_failure_withheld, "checks failing after two attempts"),
            (finding.merge_state.is_out_of_date, "out of date"),
            (finding.check_result is CheckResult.FAILING, "checks failing"),
            (finding.check_result is CheckResult.RUNNING, "checks running"),
            (True, "ready for review"),
        )
        if holds
    )
