"""Map configured harnesses to adapters and inspect their durable output.

The lookup sits here rather than in `harness_adapters.py`, because every adapter
imports `harness_adapters.py` itself. Both kinds of agent work also use the
lookup to find a harness session identifier in recorded raw output.
"""

from collections.abc import Iterable
from pathlib import Path

from dreamcatcher.claude import CLAUDE_ADAPTER
from dreamcatcher.codex import CODEX_ADAPTER
from dreamcatcher.commands import locate_program
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


def locate_harnesses(*, harnesses: Iterable[AgentHarness]) -> None:
    """Refuse when any of the harnesses is not on the PATH."""
    for harness in sorted(harnesses):
        locate_program(program=HARNESS_ADAPTERS[harness].program)


def find_harness_session_identifier(
    *,
    harness: AgentHarness,
    agent_work_identifier: str,
    recorded: HarnessSessionIdentifier | None,
    raw_outputs: Iterable[Path],
) -> HarnessSessionIdentifier | None:
    """Return the recorded identifier, or else the first the raw outputs hold.

    Pass the raw outputs newest round first, so that a recovered identifier is
    the one the latest round reported.
    """
    if recorded is not None:
        return recorded
    for raw_output in raw_outputs:
        identifier = _find_harness_session_identifier_in_output(
            harness=harness,
            agent_work_identifier=agent_work_identifier,
            raw_output=raw_output,
        )
        if identifier is not None:
            return identifier
    return None


def _find_harness_session_identifier_in_output(
    *,
    harness: AgentHarness,
    agent_work_identifier: str,
    raw_output: Path,
) -> HarnessSessionIdentifier | None:
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
