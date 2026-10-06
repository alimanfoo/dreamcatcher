"""Prepare a repository's main checkout for a dreamcatcher daemon."""

from pathlib import Path

from dreamcatcher.commands import CommandError, locate_program, run_command
from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    AgentHarness,
    DreamcatcherConfig,
    read_dreamcatcher_config,
    write_default_dreamcatcher_config,
)
from dreamcatcher.errors import ReportableError
from dreamcatcher.git import fetch_main, read_git_author_identity, require_main_checkout
from dreamcatcher.github import (
    GitHubIdentity,
    UnknownGitHubResponse,
    can_push_to_repository,
    create_label,
    list_labels,
    require_github_identity,
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
    _report_step(line=f"{root} is a main checkout.")
    identity = require_github_identity(root=root)
    _require_push_access(identity=identity)
    _report_step(
        line=f"gh is signed in as {identity.account}, "
        f"who can push to {identity.repository}."
    )
    author = read_git_author_identity(root=root)
    _report_step(line=f"Git commits here as {author}.")
    fetch_main(root=root)
    _report_step(line="Fetched origin/main.")
    installed = _find_installed_harnesses()
    is_config_new = write_default_dreamcatcher_config(root=root, harnesses=installed)
    _report_step(
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
        account=identity.account, config=config, is_config_new=is_config_new
    )


def _report_step(*, line: str) -> None:
    # A plugin installation takes a while, so each line shows as it is done.
    print(line, flush=True)


def _require_push_access(*, identity: GitHubIdentity) -> None:
    can_push = can_push_to_repository(repository=identity.repository)
    if isinstance(can_push, UnknownGitHubResponse):
        raise ReportableError(
            f"dreamcatcher cannot tell whether {identity.account} can push to "
            f"{identity.repository}: {can_push.reason}"
        )
    if not can_push:
        raise ReportableError(
            f"{identity.account} cannot push to {identity.repository}. Ask for "
            "write access, then run dreamcatcher init again."
        )


def _find_installed_harnesses() -> set[AgentHarness]:
    """Return every harness on the PATH, or refuse when there is none."""
    installed = set()
    for harness in AgentHarness:
        try:
            locate_program(program=HARNESS_ADAPTERS[harness].program)
        except CommandError as error:
            _report_step(line=str(error))
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
            f"{adapter.program} is not signed in. Sign in to {adapter.program}, "
            "then run dreamcatcher init again."
        ) from error
    for arguments in adapter.build_plugin_installation(
        marketplace=_DREAM_MARKETPLACE, plugin=_DREAM_PLUGIN
    ):
        run_command(program=adapter.program, arguments=arguments)
    _report_step(
        line=f"{adapter.program} is signed in, and has the dream plugin installed."
    )


def _create_missing_labels(*, repository: str, config: DreamcatcherConfig) -> None:
    """Create every route label the repository lacks, matching as routing does."""
    labels = list_labels(repository=repository)
    if isinstance(labels, UnknownGitHubResponse):
        raise ReportableError(
            f"dreamcatcher cannot read the labels of {repository}: {labels.reason}"
        )
    existing = {label.name.casefold() for label in labels}
    descriptions = {
        **{route.label: _ASSIGNMENT_LABEL_DESCRIPTION for route in config.assignment},
        **{
            route.label: _CONVERSATION_LABEL_DESCRIPTION
            for route in config.conversation
        },
    }
    created = [label for label in descriptions if label.casefold() not in existing]
    for label in created:
        create_label(repository=repository, name=label, description=descriptions[label])
    _report_step(
        line=f"Created the labels {', '.join(created)}."
        if created
        else "The repository has every label that the configuration routes."
    )


def _report_next_steps(
    *, account: str, config: DreamcatcherConfig, is_config_new: bool
) -> None:
    """Say what the user does next, which the setup leaves to them."""
    lines = ["", "dreamcatcher is ready. Next:"]
    if is_config_new:
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
        _report_step(line=line)
