"""Which adapter runs each harness.

Everything outside an adapter names a harness by the word that the config uses.
This is the one place that turns that word into the adapter which runs it, so
nothing else has to know how many harnesses there are or what they are called.

The lookup sits here rather than in `adapters.py`, because every adapter
imports `adapters.py` itself.
"""

from dreamcatcher.adapters import Adapter
from dreamcatcher.claude import CLAUDE
from dreamcatcher.codex import CODEX
from dreamcatcher.config import Harness

ADAPTERS: dict[Harness, Adapter] = {
    Harness.CLAUDE: CLAUDE,
    Harness.CODEX: CODEX,
}
