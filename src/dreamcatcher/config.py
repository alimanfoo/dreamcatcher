"""Read dreamcatcher.toml, the configuration the repository agrees on."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import AfterValidator, ConfigDict, Field, model_validator

from dreamcatcher.commands import refuse_unquotable
from dreamcatcher.documents import DreamcatcherDocument, read_toml

DREAMCATCHER_CONFIG_NAME = "dreamcatcher.toml"

# Text that quoting can carry to a harness's own command line. Windows runs a
# harness that npm installed as a batch file, so the text meets cmd.exe on the
# way. Refusing it as the config is read is what lets the message name the
# setting that holds it.
#
# A prompt is not one of these. A round writes its prompt to a file for the
# harness to read, so no command line ever carries it, and it can hold anything
# and run to any length.
QuotableText = Annotated[str, AfterValidator(refuse_unquotable)]


class AgentHarness(StrEnum):
    """List the agent harnesses that Dreamcatcher can run."""

    CLAUDE = "claude"
    CODEX = "codex"


def refuse_unsupported_issue_conversation_harness(
    harness: AgentHarness, /
) -> AgentHarness:
    """Return the conversation harness supported in this stage, or refuse it."""
    if harness is not AgentHarness.CLAUDE:
        raise ValueError("Codex issue conversations are not supported yet")
    return harness


IssueConversationHarness = Annotated[
    AgentHarness, AfterValidator(refuse_unsupported_issue_conversation_harness)
]


class AgentRecipe(DreamcatcherDocument):
    """Describe how one harness runs one kind of agent work."""

    prompt: str
    model: QuotableText
    effort: QuotableText


class IssueConversationConfig(DreamcatcherDocument):
    """Configure one repository's issue-conversation partner."""

    label: str
    harness: IssueConversationHarness
    prompt: str
    model: QuotableText
    effort: QuotableText


class _AgentHarnessRoute(DreamcatcherDocument):
    """Map one agent-work label to its available harness recipes.

    The label is the route's identity, so no two routes carry the same one.

    Harness blocks sit beside the label as extra keys. Their declared key type
    is `AgentHarness`, so an unknown harness is a validation error.
    """

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[AgentHarness, AgentRecipe]

    label: str

    @property
    def recipes(self) -> dict[AgentHarness, AgentRecipe]:
        """The recipe of each harness that can run this route."""
        return self.__pydantic_extra__

    def choose_harness(self, *, requested_harness: AgentHarness) -> AgentHarness:
        """Return the harness that runs this label, given what the run named.

        A label carrying a block for the named harness runs on that one. There
        are two harnesses, so a label with no block for the named one carries a
        block for the other alone, and runs on that one whatever the run named.
        So which harnesses can run a label is already in the blocks that the
        label carries, and the config needs no pin of its own.
        """
        recipes = self.recipes
        return (
            requested_harness if requested_harness in recipes else next(iter(recipes))
        )

    @model_validator(mode="after")
    def _require_recipe(self) -> Self:
        """Refuse a label with no harness able to run it."""
        if not self.recipes:
            raise ValueError(f"label {self.label} has no harness block")
        return self


class DispatchRoute(_AgentHarnessRoute):
    """Map a dispatch label to its available harness recipes."""


class DreamcatcherConfig(DreamcatcherDocument):
    """Model a repository's agent-assignment configuration."""

    assignee: str = "@me"
    dispatch: list[DispatchRoute] = Field(min_length=1)
    conversation: IssueConversationConfig | None = None

    @property
    def dispatch_routes(self) -> dict[str, DispatchRoute]:
        """The dispatch route for each configured label.

        The label is a route's identity, and no two routes carry the same one,
        so a label names one route here.
        """
        return {route.label: route for route in self.dispatch}

    @property
    def routed_harnesses(self) -> set[AgentHarness]:
        """Every harness that any configured route can select.

        A route with one harness selects it regardless of the daemon's requested
        harness.
        """
        harnesses = {harness for route in self.dispatch for harness in route.recipes}
        if self.conversation is not None:
            harnesses.add(self.conversation.harness)
        return harnesses

    def identify_dispatch_labels(self, *, labels: list[str]) -> list[str]:
        """Return the configured dispatch labels among the observed labels."""
        configured = {label.casefold(): label for label in self.dispatch_routes}
        return sorted(
            {
                configured[label.casefold()]
                for label in labels
                if label.casefold() in configured
            },
            key=str.casefold,
        )

    @model_validator(mode="after")
    def _require_one_route_per_label(self) -> Self:
        """Refuse two routes for one label, since the label is the identity."""
        labels = [route.label for route in self.dispatch]
        identities = [label.casefold() for label in labels]
        repeated = sorted(
            {identity for identity in identities if identities.count(identity) > 1}
        )
        if repeated:
            repeated_label_names = ", ".join(repeated)
            raise ValueError(
                f"more than one dispatch entry uses the label {repeated_label_names}"
            )
        return self


def read_dreamcatcher_config(*, root: Path) -> DreamcatcherConfig:
    """Return the configuration the repository at root holds."""
    return read_toml(model=DreamcatcherConfig, path=root / DREAMCATCHER_CONFIG_NAME)
