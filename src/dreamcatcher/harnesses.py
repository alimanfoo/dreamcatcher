"""Which adapter runs each harness.

Everything outside an adapter names a harness by the word that the config uses.
This is the one place that turns that word into the adapter which runs it, so
nothing else has to know how many harnesses there are or what they are called.

The lookup sits here rather than in `harness_adapters.py`, because every adapter
imports `harness_adapters.py` itself.
"""

from dreamcatcher.claude import CLAUDE
from dreamcatcher.codex import CODEX
from dreamcatcher.config import Harness
from dreamcatcher.harness_adapters import HarnessAdapter

HARNESS_ADAPTERS: dict[Harness, HarnessAdapter] = {
    Harness.CLAUDE: CLAUDE,
    Harness.CODEX: CODEX,
}
