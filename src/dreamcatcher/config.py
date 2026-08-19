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
    """A label, and how to dispatch an issue that carries it.

    The label is the mapping's identity. The harness pin, when it is there, says
    this label always goes to that harness, whatever the run was started with.
    """

    label: str
    harness: Harness | None = None
    claude: HarnessSettings | None = None
    codex: HarnessSettings | None = None

    @property
    def settings(self) -> dict[Harness, HarnessSettings]:
        """The settings block this mapping carries per harness."""
        blocks = {Harness.CLAUDE: self.claude, Harness.CODEX: self.codex}
        return {
            harness: block for harness, block in blocks.items() if block is not None
        }

    def settings_for(self, run_harness: Harness) -> HarnessSettings:
        """Return the settings a dispatch of this label uses."""
        return self.settings[self.harness or run_harness]

    @model_validator(mode="after")
    def _carries_every_block_it_can_dispatch_with(self) -> Self:
        """Refuse a mapping a run could reach with no settings to dispatch on."""
        reachable = [self.harness] if self.harness else list(Harness)
        missing = [harness for harness in reachable if harness not in self.settings]
        if missing:
            named = ", ".join(missing)
            raise ValueError(f"label {self.label} has no {named} block")
        return self


class Config(Document):
    """What the repo agrees on about dispatching its labelled issues."""

    interval: PositiveInt
    harness: Harness
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
