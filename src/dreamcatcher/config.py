"""Read dreamcatcher.toml, the configuration the repository agrees on."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Self

from pydantic import AfterValidator, Field, model_validator

from dreamcatcher.claude import ClaudeConfig
from dreamcatcher.codex import CodexConfig
from dreamcatcher.commands import refuse_unquotable
from dreamcatcher.documents import DreamcatcherDocument, read_toml

_DREAMCATCHER_CONFIG_NAME = "dreamcatcher.toml"

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


class DispatchRecipe(DreamcatcherDocument):
    """Describe how one harness runs one kind of agent work."""

    prompt: str
    model: QuotableText
    effort: QuotableText


class ClaudeRecipe(DispatchRecipe):
    """Describe how Claude runs one kind of agent work."""

    config: ClaudeConfig = Field(default_factory=dict)


class CodexRecipe(DispatchRecipe):
    """Describe how Codex runs one kind of agent work."""

    config: CodexConfig = Field(default_factory=dict)


class DispatchRoute(DreamcatcherDocument):
    """Map one dispatch label to its available dispatch recipes.

    The label is the route's identity, so no two routes carry the same one.
    """

    label: str
    claude: ClaudeRecipe | None = None
    codex: CodexRecipe | None = None

    @property
    def recipes(self) -> dict[AgentHarness, ClaudeRecipe | CodexRecipe]:
        """The recipe of each harness that can run this route.

        Each harness's recipe is the field that the harness's value names.
        """
        return {
            harness: recipe
            for harness in AgentHarness
            if (recipe := getattr(self, harness.value)) is not None
        }

    def choose_harness(self, *, requested_harness: AgentHarness) -> AgentHarness:
        """Return the harness that runs this label, given the preferred harness.

        A label carrying a recipe for the preferred harness runs on that one. There
        are two harnesses, so a label with no recipe for the preferred one carries
        a recipe for the other alone, and runs on that one whatever the preference.
        So which harnesses can run a label is already in the recipes that the
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
            raise ValueError(f"label {self.label} has no dispatch recipe")
        return self


class AssignmentRoute(DispatchRoute):
    """Map an assignment label to its available dispatch recipes."""


class ConversationRoute(DispatchRoute):
    """Map a conversation label to its available dispatch recipes."""


def _identify_routes[Route: DispatchRoute](
    *, labels: list[str], routes: list[Route]
) -> list[Route]:
    """Return configured routes matching the observed labels."""
    routes_by_identity = {route.label.casefold(): route for route in routes}
    identities = sorted(
        {label.casefold() for label in labels} & routes_by_identity.keys()
    )
    return [routes_by_identity[identity] for identity in identities]


class DreamcatcherConfig(DreamcatcherDocument):
    """Model a repository's agent-work configuration."""

    assignment: list[AssignmentRoute] = Field(min_length=1)
    conversation: list[ConversationRoute] = Field(default_factory=list)

    @property
    def assignment_routes(self) -> dict[str, AssignmentRoute]:
        """The assignment route for each configured label.

        The label is a route's identity, and no two routes carry the same one,
        so a label names one route here.
        """
        return {route.label: route for route in self.assignment}

    @property
    def routed_harnesses(self) -> set[AgentHarness]:
        """Every harness that any configured route can select.

        A route with one harness selects it regardless of the daemon's requested
        harness.
        """
        routes = [*self.assignment, *self.conversation]
        return {harness for route in routes for harness in route.recipes}

    def identify_assignment_labels(self, *, labels: list[str]) -> list[str]:
        """Return the configured assignment labels among the observed labels."""
        return [
            route.label
            for route in _identify_routes(labels=labels, routes=self.assignment)
        ]

    def identify_conversation_routes(
        self, *, labels: list[str]
    ) -> list[ConversationRoute]:
        """Return the conversation routes matching the observed labels."""
        return _identify_routes(labels=labels, routes=self.conversation)

    @model_validator(mode="after")
    def _require_one_route_per_label(self) -> Self:
        """Refuse two routes for one label, since the label is the identity."""
        route_groups = (
            ("assignment", self.assignment),
            ("conversation", self.conversation),
        )
        for name, routes in route_groups:
            identities = [route.label.casefold() for route in routes]
            repeated = sorted(
                {identity for identity in identities if identities.count(identity) > 1}
            )
            if repeated:
                repeated_label_names = ", ".join(repeated)
                raise ValueError(
                    f"more than one {name} entry uses the label {repeated_label_names}"
                )
        assignment_labels = {route.label.casefold() for route in self.assignment}
        conversation_labels = {route.label.casefold() for route in self.conversation}
        shared = sorted(assignment_labels & conversation_labels)
        if shared:
            shared_label_names = ", ".join(shared)
            raise ValueError(
                "assignment and conversation entries use the same label: "
                f"{shared_label_names}"
            )
        return self


def read_dreamcatcher_config(*, root: Path) -> DreamcatcherConfig:
    """Return the configuration the repository at root holds."""
    return read_toml(model=DreamcatcherConfig, path=root / _DREAMCATCHER_CONFIG_NAME)
