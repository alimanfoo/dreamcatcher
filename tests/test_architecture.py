from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "src" / "dreamcatcher"

PRESENTATION = {"tui", "web"}
# Operations and record types a presentation module must not name, because
# status already derives the fact they would be used to rediscover.
DOMAIN_NAMES_PRESENTATION_MUST_NOT_USE = [
    "ErroredAgentRoundEnding",
    "HARNESS_ADAPTERS",
    "InterruptedAgentRoundEnding",
    "find_harness_session_identifier",
]


@pytest.mark.parametrize("boundary", sorted(PRESENTATION))
@pytest.mark.parametrize("name", DOMAIN_NAMES_PRESENTATION_MUST_NOT_USE)
def test_presentation_does_not_rediscover_what_status_derives(boundary, name):
    for path in (SOURCE / boundary).rglob("*.py"):
        assert name not in path.read_text(encoding="utf-8")
