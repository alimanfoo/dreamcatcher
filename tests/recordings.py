"""The streams recorded from a real harness, and the feed they render as.

The recordings are the review surface for both the adapters and the round that
runs one, so both read them from here.
"""

from collections.abc import Iterable

from dreamcatcher.feed import FeedRenderer
from dreamcatcher.harness_adapters import HarnessAdapter


def rendered(
    *, adapter: HarnessAdapter, lines: Iterable[str], renderer: FeedRenderer
) -> str:
    """Return the feed the harness's lines render as, read through adapter."""
    return "".join(
        renderer.render(event=event)
        for line in lines
        for event in adapter.read(line=line)
    )
