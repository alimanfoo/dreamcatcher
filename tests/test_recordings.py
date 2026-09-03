"""Read each recorded stream through the adapter that made it, and the feed.

An agent session recorded every stream here in the same throwaway repository,
running the command that adapter's `first_round` builds.

Claude's recordings sit under `tests/fixtures/claude/`.

- `round.jsonl` is a round that listed a directory, read a file that was not
  there, and sent a subagent to count the files.
- `failed-round.jsonl` is a round asked for a model that does not exist.
- `background-command.jsonl` is a round that ran one command in the background.
  Its notification carries no token usage, which is what keeps it out of the
  feed as a subagent's report.
- `rate-limited.jsonl` is the one Claude recording not made against Claude's own
  API. The CLI ran against a local endpoint answering every request with the 429
  an exhausted rate limit returns, since a real limit is not something a session
  can arrange. It records how Claude retries and then gives up: ten retries over
  about three minutes, then a round that exits non-zero.

Codex's recordings sit under `tests/fixtures/codex/`.

- `round.jsonl` is a round that listed the directory, read a file that was not
  there, wrote a file, and searched the web.
- `resumed-round.jsonl` is the round after it, resumed with `--last`. It deleted
  the file the first round wrote. Both rounds carry the same thread id, so the
  resume found the session by the directory it ran in.
- `failed-round.jsonl` is a round asked for a model that does not exist.
- `rate-limited.jsonl` came the way Claude's did. The CLI ran against a local
  endpoint answering every request with a 429. Codex spends no retries on it:
  the round fails on the first answer and exits non-zero.

The golden beside each recording is the review surface: read it as the user of
`scry` would, and judge the feed by it.
"""

from pathlib import PurePosixPath

import pytest
from clocks import Ticking
from recordings import FIXTURES, rendered

from dreamcatcher.claude import CLAUDE
from dreamcatcher.codex import CODEX
from dreamcatcher.feed import Renderer

RECORDED_IN = PurePosixPath("/private/tmp/dreamcatcher-recording")

# The directory under FIXTURES holding each adapter's recordings. Every stream in
# it is that adapter's, and the golden feed sits beside it under the same name.
# So the directory says which recordings there are, and this needs no list of its
# own that a new recording could be left out of.
RECORDINGS = ((CLAUDE, "claude"), (CODEX, "codex"))


@pytest.mark.parametrize(
    ("adapter", "recording"),
    [
        pytest.param(adapter, recording, id=f"{directory}/{recording.stem}")
        for adapter, directory in RECORDINGS
        for recording in sorted((FIXTURES / directory).glob("*.jsonl"))
    ],
)
def test_a_recorded_stream_renders_as_its_golden_feed(adapter, recording):
    feed = rendered(
        adapter,
        recording.read_text(encoding="utf-8").splitlines(),
        Renderer(RECORDED_IN, clock=Ticking()),
    )

    assert feed == recording.with_suffix(".feed.txt").read_text(encoding="utf-8")
