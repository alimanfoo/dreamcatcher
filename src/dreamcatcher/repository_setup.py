"""Prepare a repository's main checkout for a dreamcatcher daemon."""

from pathlib import Path

from dreamcatcher.commands import CommandError, locate_program, run_command
from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    DreamcatcherConfig,
    read_dreamcatcher_config,
    write_default_dreamcatcher_config_if_absent,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import (
    fetch_main,
    is_file_on_main,
    read_git_author_identity,
    require_main_checkout,
)
from dreamcatcher.github import (
    GitHubIdentity,
    can_push_to_repository,
    create_label,
    list_labels,
    require_github_identity,
    require_known_github_value,
)
from dreamcatcher.harnesses import HARNESS_ADAPTERS

# The plugin whose skills the default configuration's prompts invoke.
_DREAM_MARKETPLACE = "alimanfoo/dream"
_DREAM_PLUGIN = "dream@dream"

_ASSIGNMENT_LABEL_DESCRIPTION = "Start a dreamcatcher assignment"
_CONVERSATION_LABEL_DESCRIPTION = "Start a dreamcatcher issue conversation"


def set_up_repository(*, root: Path) -> None:
    """Check what a daemon run needs at root, and put in place what is missing.

    Each step prints a line once it is done, and the first step that fails
    raises ReportableError, so the lines show how far the setup got. Every step
    leaves alone what is already in place, so a second setup is safe. The setup
    installs the dream plugin for the user, outside the repository, and never
    commits or pushes.
    """
    require_main_checkout(root=root)
    _print_line(line=f"{root} is a main checkout.")
    identity = require_github_identity(root=root)
    _require_push_access(identity=identity)
    _print_line(
        line=f"gh is signed in as {identity.account}, "
        f"who can push to {identity.repository}."
    )
    author = read_git_author_identity(root=root)
    _print_line(line=f"Git commits here as {author}.")
    fetch_main(root=root)
    _print_line(line="Fetched origin/main.")
    installed = _require_installed_harnesses()
    is_config_new = write_default_dreamcatcher_config_if_absent(
        root=root, harnesses=installed
    )
    _print_line(
        line=f"Wrote the default {DREAMCATCHER_CONFIG_NAME}."
        if is_config_new
        else f"Left the existing {DREAMCATCHER_CONFIG_NAME} as it is."
    )
    config = read_dreamcatcher_config(root=root)
    missing = config.routed_harnesses - installed
    if missing:
        raise ReportableError(
            f"{DREAMCATCHER_CONFIG_NAME} routes work to {', '.join(sorted(missing))}, "
            "which is not on the PATH. Install it, or comment out its recipes."
        )
    for harness in sorted(config.routed_harnesses):
        _set_up_harness(harness=harness)
    _create_missing_labels(repository=identity.repository, config=config)
    _report_next_steps(
        account=identity.account,
        config=config,
        is_config_on_main=is_file_on_main(root=root, name=DREAMCATCHER_CONFIG_NAME),
    )


def _print_line(*, line: str) -> None:
    # A plugin installation takes a while, so each line shows as it is done.
    print(line, flush=True)


def _require_push_access(*, identity: GitHubIdentity) -> None:
    can_push = require_known_github_value(
        value=can_push_to_repository(repository=identity.repository),
        question=f"whether {identity.account} can push to {identity.repository}",
    )
    if not can_push:
        raise ReportableError(
            f"{identity.account} cannot push to {identity.repository}. Ask for "
            "write access, then run dreamcatcher init again."
        )


def _require_installed_harnesses() -> set[AgentHarness]:
    installed = set()
    for harness in AgentHarness:
        try:
            locate_program(program=HARNESS_ADAPTERS[harness].program)
        except CommandError as error:
            _print_line(line=str(error))
        else:
            installed.add(harness)
    if not installed:
        raise ReportableError(
            "Install Claude Code or Codex, then run dreamcatcher init again."
        )
    return installed


def _set_up_harness(*, harness: AgentHarness) -> None:
    """Refuse a harness that is signed out, then install the dream plugin for it."""
    adapter = HARNESS_ADAPTERS[harness]
    try:
        run_command(program=adapter.program, arguments=adapter.sign_in_check_arguments)
    except CommandError as error:
        raise ReportableError(
            f"{error} Sign in to {adapter.program}, then run dreamcatcher init again."
        ) from error
    for arguments in adapter.build_plugin_installation(
        marketplace=_DREAM_MARKETPLACE, plugin=_DREAM_PLUGIN
    ):
        run_command(program=adapter.program, arguments=arguments)
    _print_line(
        line=f"{adapter.program} is signed in, and has the dream plugin installed."
    )


def _create_missing_labels(*, repository: str, config: DreamcatcherConfig) -> None:
    """Create every route label that matches none of the repository's labels."""
    labels = require_known_github_value(
        value=list_labels(repository=repository),
        question=f"which labels {repository} has",
    )
    names = [label.name for label in labels]
    routed = {
        *config.identify_assignment_labels(labels=names),
        *(route.label for route in config.identify_conversation_routes(labels=names)),
    }
    descriptions = {
        **{route.label: _ASSIGNMENT_LABEL_DESCRIPTION for route in config.assignment},
        **{
            route.label: _CONVERSATION_LABEL_DESCRIPTION
            for route in config.conversation
        },
    }
    created = [label for label in descriptions if label not in routed]
    for label in created:
        create_label(repository=repository, name=label, description=descriptions[label])
    _print_line(
        line=f"Created the labels {', '.join(created)}."
        if created
        else "The repository has every label that the configuration routes."
    )


def _report_next_steps(
    *, account: str, config: DreamcatcherConfig, is_config_on_main: bool
) -> None:
    lines = ["", "dreamcatcher is ready. Next:"]
    if not is_config_on_main:
        lines += [
            f"  git add {DREAMCATCHER_CONFIG_NAME}",
            '  git commit -m "Configure dreamcatcher"',
            "  git push origin main",
        ]
    lines += [
        f"  Assign an issue to {account}, and label it {config.assignment[0].label}.",
        f"  dreamcatcher run --harness {min(config.routed_harnesses)}",
    ]
    for line in lines:
        _print_line(line=line)
