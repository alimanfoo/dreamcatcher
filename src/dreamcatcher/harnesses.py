"""Map each configured harness to its adapter.

The lookup sits here rather than in `harness_adapters.py`, because every adapter
imports `harness_adapters.py` itself.
"""

from pathlib import Path

from dreamcatcher.claude import CLAUDE_ADAPTER
from dreamcatcher.codex import CODEX_ADAPTER
from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import read_lines_from
from dreamcatcher.harness_adapters import (
    HarnessAdapter,
    HarnessSessionIdentifier,
    refuse_reportable_harness_session_identifier,
)

HARNESS_ADAPTERS: dict[AgentHarness, HarnessAdapter] = {
    AgentHarness.CLAUDE: CLAUDE_ADAPTER,
    AgentHarness.CODEX: CODEX_ADAPTER,
}


def find_harness_session_identifier_in_output(
    *,
    harness: AgentHarness,
    agent_work_identifier: str,
    raw_output: Path,
) -> HarnessSessionIdentifier | None:
    """Return the first harness session identifier in durable raw output."""
    lines, _ = read_lines_from(path=raw_output, position=0)
    adapter = HARNESS_ADAPTERS[harness]
    for line in lines:
        identifier = adapter.read_output(line=line).harness_session_identifier
        if identifier is not None:
            return refuse_reportable_harness_session_identifier(
                agent_work_identifier=agent_work_identifier,
                identifier=identifier,
            )
    return None
