from dreamcatcher.claude import CLAUDE_ADAPTER
from dreamcatcher.codex import CODEX_ADAPTER
from dreamcatcher.config import AgentHarness
from dreamcatcher.harnesses import HARNESS_ADAPTERS


def test_every_harness_the_config_names_is_run_by_its_own_adapter():
    assert HARNESS_ADAPTERS.keys() == set(AgentHarness)
    assert HARNESS_ADAPTERS[AgentHarness.CLAUDE] is CLAUDE_ADAPTER
    assert HARNESS_ADAPTERS[AgentHarness.CODEX] is CODEX_ADAPTER
