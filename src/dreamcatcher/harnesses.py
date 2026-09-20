"""Map each configured harness to its adapter.

The lookup sits here rather than in `harness_adapters.py`, because every adapter
imports `harness_adapters.py` itself.
"""

from dreamcatcher.claude import CLAUDE_ADAPTER
from dreamcatcher.codex import CODEX_ADAPTER
from dreamcatcher.config import AgentHarness
from dreamcatcher.harness_adapters import HarnessAdapter

HARNESS_ADAPTERS: dict[AgentHarness, HarnessAdapter] = {
    AgentHarness.CLAUDE: CLAUDE_ADAPTER,
    AgentHarness.CODEX: CODEX_ADAPTER,
}
