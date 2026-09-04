"""Read dreamcatcher.toml, the configuration the repo agrees on."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import AfterValidator, ConfigDict, Field, PositiveInt, model_validator

from dreamcatcher.commands import refuse_unquotable
from dreamcatcher.documents import Document, read_toml

CONFIG_NAME = "dreamcatcher.toml"

# Text that quoting can carry to a harness's own command line. Windows runs a
# harness that npm installed as a batch file, so the text meets cmd.exe on the
# way. Refusing it as the config is read is what lets the message name the
# setting that holds it.
#
# A prompt is not one of these. A round writes its prompt to a file for the
# harness to read, so no command line ever carries it, and it can hold anything
# and run to any length.
QuotableText = Annotated[str, AfterValidator(refuse_unquotable)]


class Harness(StrEnum):
    """A coding agent dreamcatcher can run a round with."""

    CLAUDE = "claude"
    CODEX = "codex"


class HarnessSettings(Document):
    """How one harness runs a round for one label."""

    prompt: str
    model: QuotableText
    effort: QuotableText


class DispatchMapping(Document):
    """A label, and the settings that each harness needs to run it.

    The label is the mapping's identity, so no two mappings carry the same one.

    A harness block sits beside the label rather than under a key of its own,
    as `[dispatch.claude]` does, so pydantic meets it as an extra key. Those
    extra keys carry a declared type, Harness, so the set of harnesses stays in
    one home. A key that names no harness is then a named error, so the mapping
    keeps the guarantee that every document makes.
    """

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[Harness, HarnessSettings]

    label: str

    @property
    def harness_settings(self) -> dict[Harness, HarnessSettings]:
        """The settings block of each harness that can run the label."""
        return self.__pydantic_extra__

    def choose_harness(self, named: Harness) -> Harness:
        """Return the harness that runs this label, given what the run named.

        A label carrying a block for the named harness runs on that one. There
        are two harnesses, so a label with no block for the named one carries a
        block for the other alone, and runs on that one whatever the run named.
        So which harnesses can run a label is already in the blocks that the
        label carries, and the config needs no pin of its own.
        """
        settings = self.harness_settings
        return named if named in settings else next(iter(settings))

    @model_validator(mode="after")
    def _carries_a_block(self) -> Self:
        """Refuse a label with no harness able to run it."""
        if not self.harness_settings:
            raise ValueError(f"label {self.label} has no harness block")
        return self


class Config(Document):
    """What the repo agrees on about dispatching its labelled issues."""

    interval: PositiveInt = 120
    max_agents: PositiveInt = 1
    assignee: str = "@me"
    dispatch: list[DispatchMapping] = Field(min_length=1)

    @property
    def label_mappings(self) -> dict[str, DispatchMapping]:
        """Each mapped label's own dispatch mapping.

        The label is a mapping's identity, and no two mappings carry the same
        one, so a label names one mapping here.
        """
        return {mapping.label: mapping for mapping in self.dispatch}

    @property
    def mapped_harnesses(self) -> set[Harness]:
        """Every harness that a mapping here could settle one of its labels on.

        A label carrying one harness block runs on that harness whatever a run
        named, so this is wider than the harness the run gave, and a run has to
        reach every one of them.
        """
        return {
            harness for mapping in self.dispatch for harness in mapping.harness_settings
        }

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
