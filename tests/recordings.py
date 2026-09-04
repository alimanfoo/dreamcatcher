"""The streams recorded from a real harness, and the feed they render as.

The recordings are the review surface for both the adapters and the round that
runs one, so both read them from here.
"""

from collections.abc import Iterable

from dreamcatcher.adapters import Adapter
from dreamcatcher.feed import Renderer


def rendered(adapter: Adapter, lines: Iterable[str], renderer: Renderer) -> str:
    """Return the feed the harness's lines render as, read through adapter."""
    return "".join(
        renderer.render(event) for line in lines for event in adapter.read(line)
    )
