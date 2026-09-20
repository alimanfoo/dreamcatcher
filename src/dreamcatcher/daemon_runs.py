"""Describe the facts fixed for one daemon run."""

from pydantic import Field, PositiveInt

from dreamcatcher.config import AgentHarness
from dreamcatcher.documents import DreamcatcherDocument


class DaemonRunRecord(DreamcatcherDocument):
    """Record the identity and capacity fixed for one daemon run."""

    pid: PositiveInt
    harness: AgentHarness
    version: str = Field(min_length=1)
    max_agents: PositiveInt
