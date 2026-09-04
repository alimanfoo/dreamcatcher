from dreamcatcher.claude import CLAUDE
from dreamcatcher.codex import CODEX
from dreamcatcher.config import Harness
from dreamcatcher.harnesses import ADAPTERS


def test_every_harness_the_config_names_is_run_by_its_own_adapter():
    assert ADAPTERS.keys() == set(Harness)
    assert ADAPTERS[Harness.CLAUDE] is CLAUDE
    assert ADAPTERS[Harness.CODEX] is CODEX
