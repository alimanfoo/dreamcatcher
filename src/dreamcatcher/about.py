"""Compose the briefing for an agent that works with the user."""

import json
from pathlib import Path
from string import Template

from dreamcatcher.config import (
    DREAMCATCHER_CONFIG_NAME,
    DreamcatcherConfig,
    read_default_dreamcatcher_config,
    read_dreamcatcher_config,
)
from dreamcatcher.documents import read_text
from dreamcatcher.lock import is_daemon_lock_held
from dreamcatcher.state import StateDirectory

_BRIEFING_TEMPLATE = Path(__file__).with_name("about.md")


def compose_agent_briefing(*, root: Path) -> str:
    """Compose the agent briefing for the checkout at root.

    Use the checkout's routes when it carries a configuration, and otherwise
    describe the packaged defaults. Report whether a daemon holds this
    checkout's lock now.
    """
    config_path = root / DREAMCATCHER_CONFIG_NAME
    is_configured = config_path.exists()
    config = (
        read_dreamcatcher_config(root=root)
        if is_configured
        else read_default_dreamcatcher_config()
    )
    state = StateDirectory(root=root)
    template_text = read_text(path=_BRIEFING_TEMPLATE, is_replaceable=False)
    template = Template(template_text.replace("\r\n", "\n"))
    return template.substitute(
        configuration=_describe_configuration(is_configured=is_configured),
        daemon=_describe_daemon(is_running=is_daemon_lock_held(path=state.lock)),
        routes=_compose_routes(config=config),
    )


def _describe_configuration(*, is_configured: bool) -> str:
    if is_configured:
        return "The routes below come from this checkout's `dreamcatcher.toml`."
    return (
        "This directory has no `dreamcatcher.toml`. The routes below are the "
        "packaged defaults, not configuration for this directory."
    )


def _describe_daemon(*, is_running: bool) -> str:
    if is_running:
        return "A dreamcatcher daemon is running here."
    return "No dreamcatcher daemon is running here."


def _compose_routes(*, config: DreamcatcherConfig) -> str:
    routes = "\n".join(
        f"- {json.dumps(route.label, ensure_ascii=False)} starts {route.kind} work. "
        + "; ".join(
            f"{harness.value} starts with "
            f"{json.dumps(recipe.prompt, ensure_ascii=False)}, using "
            f"{json.dumps(recipe.model, ensure_ascii=False)} at "
            f"{json.dumps(recipe.effort, ensure_ascii=False)} effort"
            for harness, recipe in route.recipes.items()
        )
        + "."
        for route in config.routes
    )
    return routes or (
        "No dispatch routes are configured. Ask the developer to configure one "
        "and restart the daemon before you dispatch work."
    )
