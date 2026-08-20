"""Read each recorded stream through the adapter that made it, and the feed.

An agent session recorded every stream here in the same throwaway repository,
running the command that adapter's `first_round` builds.

Claude's, under `tests/fixtures/claude/`: `round.jsonl` is a round that listed a
directory, read a file that was not there, and sent a subagent to count the
files. `failed-round.jsonl` is a round asked for a model that does not exist.
`background-command.jsonl` is a round that ran one command in the background:
its notification carries no token usage, which is what keeps it out of the feed
as a subagent's report.

`rate-limited.jsonl` is the one recording not made against Claude's own API. The
CLI ran against a local endpoint answering every request with the 429 an
exhausted rate limit returns, since a real limit is not something a session can
arrange. Claude's own retry and failure handling is what it records: ten retries
over about three minutes, then a round that exits non-zero.

The golden beside each recording is the review surface: read it as the user of
`scry` would, and judge the feed by it.
"""

from pathlib import Path, PurePosixPath

import pytest
from clocks import Ticking

from dreamcatcher.adapters import Adapter
from dreamcatcher.claude import CLAUDE
from dreamcatcher.feed import Renderer

FIXTURES = Path(__file__).parent / "fixtures"

RECORDED_IN = PurePosixPath("/private/tmp/dreamcatcher-recording")

# What each adapter recorded: the directory under FIXTURES holding its streams,
# and the name of every recording in it. The golden feed sits beside the
# recording, under the same name.
RECORDINGS = ((CLAUDE, "claude", ("round", "failed-round", "background-command")),)


def rendered(adapter: Adapter, recording: Path) -> str:
    """Return the feed the whole recording renders as."""
    renderer = Renderer(RECORDED_IN, clock=Ticking())
    return "".join(
        renderer.render(event)
        for line in recording.read_text(encoding="utf-8").splitlines()
        for event in adapter.read(line)
    )


@pytest.mark.parametrize(
    ("adapter", "recording"),
    [
        pytest.param(adapter, FIXTURES / directory / name, id=f"{directory}/{name}")
        for adapter, directory, names in RECORDINGS
        for name in names
    ],
)
def test_a_recorded_stream_renders_as_its_golden_feed(adapter, recording):
    feed = rendered(adapter, recording.with_suffix(".jsonl"))

    assert feed == recording.with_suffix(".feed.txt").read_text(encoding="utf-8")
