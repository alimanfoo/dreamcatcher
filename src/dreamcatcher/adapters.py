"""The boundary a harness sits behind.

Everything else in the tool names a harness only to pick its adapter. The
adapter knows what the CLI is called, which flags keep it from stalling, and
what its stream means. Nothing else does.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from dreamcatcher.feed import Event


@dataclass(frozen=True)
class Launch:
    """What one round starts with.

    The dispatch fixes the session's name, its model, and its effort. Every
    round of that session runs with them. The prompt is this round's own.
    """

    session: str
    model: str
    effort: str
    prompt: str


class Adapter(ABC):
    """One harness, as everything outside its own module sees it.

    The program is the name of the harness's CLI. Asking the adapter for it is
    how anything else reaches the CLI without knowing which harness it is.
    """

    program: ClassVar[str]

    @abstractmethod
    def first_round(self, launch: Launch) -> list[str]:
        """Return the command that runs a session's first round."""

    @abstractmethod
    def resume(self, launch: Launch) -> list[str]:
        """Return the command that resumes the session with launch's prompt."""

    @abstractmethod
    def read(self, line: str) -> list[Event]:
        """Return the feed events one line of the harness's stream carries."""
