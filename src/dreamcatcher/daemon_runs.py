"""Describe the facts fixed for one daemon run."""

from pydantic import Field, PositiveInt

from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import DreamcatcherDocument
from dreamcatcher.harness_adapters import AgentWorkKind


class RoutedLabel(DreamcatcherDocument):
    """Record one dispatch label that a daemon run routes, and its kind of work."""

    label: str
    kind: AgentWorkKind


class DaemonRunRecord(DreamcatcherDocument):
    """Record the identity, capacity and routed labels fixed for one daemon run.

    The routed labels are those of the routes the daemon loaded at startup, so a
    reader learns which labels start work without opening a configuration that
    may have changed since.
    """

    pid: PositiveInt
    harness: AgentHarness
    version: str = Field(min_length=1)
    max_agents: PositiveInt
    interval_seconds: PositiveInt
    routed_labels: list[RoutedLabel]

    def list_labels(self, *, kind: AgentWorkKind) -> tuple[str, ...]:
        """Return the routed labels of one kind, sorted case-insensitively."""
        return tuple(
            sorted(
                (route.label for route in self.routed_labels if route.kind is kind),
                key=str.casefold,
            )
        )
