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


class AssignmentRecipe(Document):
    """How one harness runs an assignment for one dispatch label."""

    prompt: str
    model: QuotableText
    effort: QuotableText


class DispatchRoute(Document):
    """A dispatch label and the recipe that each harness uses for it.

    The label is the route's identity, so no two routes carry the same one.

    A harness block sits beside the label rather than under a key of its own,
    as `[dispatch.claude]` does, so pydantic meets it as an extra key. Those
    extra keys carry a declared type, Harness, so the set of harnesses stays in
    one home. A key that names no harness is then a named error, so the route
    keeps the guarantee that every document makes.
    """

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[Harness, AssignmentRecipe]

    label: str

    @property
    def assignment_recipes(self) -> dict[Harness, AssignmentRecipe]:
        """The recipe of each harness that can run this route."""
        return self.__pydantic_extra__

    def choose_harness(self, *, named: Harness) -> Harness:
        """Return the harness that runs this label, given what the run named.

        A label carrying a block for the named harness runs on that one. There
        are two harnesses, so a label with no block for the named one carries a
        block for the other alone, and runs on that one whatever the run named.
        So which harnesses can run a label is already in the blocks that the
        label carries, and the config needs no pin of its own.
        """
        recipes = self.assignment_recipes
        return named if named in recipes else next(iter(recipes))

    @model_validator(mode="after")
    def _carries_a_block(self) -> Self:
        """Refuse a label with no harness able to run it."""
        if not self.assignment_recipes:
            raise ValueError(f"label {self.label} has no harness block")
        return self


class Config(Document):
    """What the repo agrees on about dispatching its labelled issues."""

    interval: PositiveInt = 120
    max_agents: PositiveInt = 1
    assignee: str = "@me"
    dispatch: list[DispatchRoute] = Field(min_length=1)

    @property
    def dispatch_routes(self) -> dict[str, DispatchRoute]:
        """The dispatch route for each configured label.

        The label is a route's identity, and no two routes carry the same one,
        so a label names one route here.
        """
        return {route.label: route for route in self.dispatch}

    @property
    def routed_harnesses(self) -> set[Harness]:
        """Every harness that a route here could settle one of its labels on.

        A label carrying one harness block runs on that harness whatever a run
        named, so this is wider than the harness the run gave, and a run has to
        reach every one of them.
        """
        return {
            harness for route in self.dispatch for harness in route.assignment_recipes
        }

    def identify_dispatch_labels(self, *, labels: list[str]) -> list[str]:
        """Return the configured dispatch labels among the observed labels."""
        configured = self.dispatch_routes.keys()
        return sorted(set(labels).intersection(configured))

    @model_validator(mode="after")
    def _each_label_has_one_route(self) -> Self:
        """Refuse two routes for one label, since the label is the identity."""
        labels = [route.label for route in self.dispatch]
        repeated = sorted({label for label in labels if labels.count(label) > 1})
        if repeated:
            named = ", ".join(repeated)
            raise ValueError(f"more than one dispatch entry uses the label {named}")
        return self


def read_config(*, root: Path) -> Config:
    """Return the configuration the repo at root holds."""
    return read_toml(model=Config, path=root / CONFIG_NAME)
