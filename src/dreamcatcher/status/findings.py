"""Word what a scheduler tick found, once for every status that shows it."""

from dreamcatcher.words import describe_count


def describe_comments_to_answer(*, count: int) -> str:
    """Say how many issue comments wait to be answered."""
    return f"{describe_count(number=count, noun='comment')} to answer"


def describe_conflicting_labels(*, labels: list[str]) -> str:
    """Name the labels of one kind that an issue carries together."""
    return "conflicting labels " + ", ".join(labels)


def describe_read_failure(*, reason: str) -> str:
    """Say why the tick could not tell what it needed."""
    return f"cannot tell: {reason}"
