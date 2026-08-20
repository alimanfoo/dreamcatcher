"""The boundary a harness sits behind.

Everything else in the tool names a harness only to pick its adapter. What the
CLI is called, which flags keep it from stalling, and what its stream means all
stop here.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from dreamcatcher.commands import locate
from dreamcatcher.feed import Event


@dataclass(frozen=True)
class Launch:
    """What one round starts with.

    The session's name, and the model and effort it was dispatched with, hold
    for every round of that session. The prompt is this round's own.
    """

    session: str
    model: str
    effort: str
    prompt: str


class Adapter(ABC):
    """One harness, as everything outside its own module sees it."""

    program: ClassVar[str]

    def installed(self) -> None:
        """Raise CommandError when the harness's CLI is not on the PATH."""
        locate(self.program)

    @abstractmethod
    def first_round(self, launch: Launch) -> list[str]:
        """Return the command that runs a session's first round."""

    @abstractmethod
    def resume(self, launch: Launch) -> list[str]:
        """Return the command that resumes the session with launch's prompt."""

    @abstractmethod
    def read(self, line: str) -> list[Event]:
        """Return the feed events one line of the harness's stream carries."""
