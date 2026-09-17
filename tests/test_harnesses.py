from dreamcatcher.claude import CLAUDE
from dreamcatcher.codex import CODEX
from dreamcatcher.config import Harness
from dreamcatcher.harnesses import HARNESS_ADAPTERS


def test_every_harness_the_config_names_is_run_by_its_own_adapter():
    assert HARNESS_ADAPTERS.keys() == set(Harness)
    assert HARNESS_ADAPTERS[Harness.CLAUDE] is CLAUDE
    assert HARNESS_ADAPTERS[Harness.CODEX] is CODEX
