"""Read each recorded Claude stream through the adapter and the feed.

An agent session recorded the streams under `tests/fixtures/claude/`, running
the command `Claude.first_round` builds in `/private/tmp/dreamcatcher-recording`.
`round.jsonl` is a round that listed a directory, read a file that was not
there, and sent a subagent to count the files. `failed-round.jsonl` is a round
asked for a model that does not exist. `background-command.jsonl` is a round
that ran one command in the background: its notification carries no token usage,
which is what keeps it out of the feed as a subagent's report.

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

from dreamcatcher.claude import CLAUDE
from dreamcatcher.feed import Renderer

FIXTURES = Path(__file__).parent / "fixtures" / "claude"

RECORDED_IN = PurePosixPath("/private/tmp/dreamcatcher-recording")


def rendered(recording: Path) -> str:
    """Return the feed the whole recording renders as."""
    renderer = Renderer(RECORDED_IN, clock=Ticking())
    return "".join(
        renderer.render(event)
        for line in recording.read_text(encoding="utf-8").splitlines()
        for event in CLAUDE.read(line)
    )


@pytest.mark.parametrize("recording", ["round", "failed-round", "background-command"])
def test_a_recorded_stream_renders_as_its_golden_feed(recording):
    feed = rendered(FIXTURES / f"{recording}.jsonl")

    assert feed == (FIXTURES / f"{recording}.feed.txt").read_text(encoding="utf-8")
