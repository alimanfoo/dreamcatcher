"""Read dreamcatcher.toml, the configuration the repo agrees on."""

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, PositiveInt, model_validator

from dreamcatcher.documents import Document, read_toml

CONFIG_NAME = "dreamcatcher.toml"


class Harness(StrEnum):
    """A coding agent dreamcatcher can run a round with."""

    CLAUDE = "claude"
    CODEX = "codex"


class HarnessSettings(Document):
    """How one harness runs a round for one label."""

    prompt: str
    model: str
    effort: str


class DispatchMapping(Document):
    """A label, and the settings each harness needs to run it.

    The label is the mapping's identity, so no two mappings carry the same one.
    """

    label: str
    claude: HarnessSettings | None = None
    codex: HarnessSettings | None = None

    @model_validator(mode="after")
    def _carries_a_block(self) -> Self:
        """Refuse a label with no harness able to run it."""
        if self.claude is None and self.codex is None:
            raise ValueError(f"label {self.label} has no claude or codex block")
        return self


class Config(Document):
    """What the repo agrees on about dispatching its labelled issues."""

    interval: PositiveInt = 120
    max_agents: PositiveInt = 1
    assignee: str = "@me"
    dispatch: list[DispatchMapping] = Field(min_length=1)

    @model_validator(mode="after")
    def _each_label_maps_once(self) -> Self:
        """Refuse two mappings for one label, since the label is the identity."""
        labels = [mapping.label for mapping in self.dispatch]
        repeated = sorted({label for label in labels if labels.count(label) > 1})
        if repeated:
            named = ", ".join(repeated)
            raise ValueError(f"more than one dispatch entry uses the label {named}")
        return self


def read_config(root: Path) -> Config:
    """Return the configuration the repo at root holds."""
    return read_toml(Config, root / CONFIG_NAME)
