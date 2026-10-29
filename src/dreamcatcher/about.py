"""Compose the briefing that explains dreamcatcher to the user's agent."""

from pathlib import Path
from string import Template

from dreamcatcher.config import DREAMCATCHER_CONFIG_NAME
from dreamcatcher.documents import read_text
from dreamcatcher.lock import is_daemon_lock_held
from dreamcatcher.state import StateDirectory

_BRIEFING_TEMPLATE = Path(__file__).with_name("about.md")


def compose_agent_briefing(*, root: Path) -> str:
    """Compose the briefing for the checkout at root.

    Say whether the checkout has a configuration, and whether a daemon holds
    this checkout's lock now.
    """
    template_text = read_text(path=_BRIEFING_TEMPLATE, is_replaceable=False)
    template = Template(template_text.replace("\r\n", "\n"))
    return template.substitute(
        configuration=_describe_configuration(
            is_configured=(root / DREAMCATCHER_CONFIG_NAME).exists()
        ),
        daemon=_describe_daemon(
            is_running=is_daemon_lock_held(path=StateDirectory(root=root).lock)
        ),
    )


def _describe_configuration(*, is_configured: bool) -> str:
    if is_configured:
        return "You can read this checkout's routes in its `dreamcatcher.toml`."
    return "This directory has no `dreamcatcher.toml`, so it has no routes yet."


def _describe_daemon(*, is_running: bool) -> str:
    if is_running:
        return "A dreamcatcher daemon is running here."
    return "No dreamcatcher daemon is running here."
