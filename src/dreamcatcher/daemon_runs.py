"""Describe the facts fixed for one daemon run."""

from pydantic import AwareDatetime, Field, PositiveInt

from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import DreamcatcherDocument, ReadOnlyList
from dreamcatcher.harness_adapters import AgentWorkKind


class RecordedRoute(DreamcatcherDocument):
    """Record one dispatch route a daemon run loaded, as its label and its kind."""

    label: str
    kind: AgentWorkKind


class DaemonRunRecord(DreamcatcherDocument):
    """Record the identity, capacity and routes fixed for one daemon run.

    The routes are the ones the daemon loaded at startup, so a reader learns
    which labels start work without opening a configuration that may have
    changed since. The start time tells a scheduler record that this daemon
    run wrote from one that an earlier run left.
    """

    pid: PositiveInt
    started: AwareDatetime
    preferred_harness: AgentHarness
    version: str = Field(min_length=1)
    max_agents: PositiveInt
    interval_seconds: PositiveInt
    routes: ReadOnlyList[RecordedRoute]

    def list_labels(self, *, kind: AgentWorkKind) -> tuple[str, ...]:
        """Return the routed labels of one kind, sorted case-insensitively."""
        return tuple(
            sorted(
                (route.label for route in self.routes if route.kind is kind),
                key=str.casefold,
            )
        )
