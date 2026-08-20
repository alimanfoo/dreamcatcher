"""Run Codex, and read what it streams back."""

import json
from typing import ClassVar

from dreamcatcher.adapters import Adapter, Launch
from dreamcatcher.feed import Event, Note, Prose

# Let the round reach the network from inside its sandbox, so it can talk to
# GitHub.
NETWORK_ACCESS = "sandbox_workspace_write.network_access=true"

# What an unattended round may do without being asked. The first round says it
# with `--approve-for-me`, which routes every approval to Codex's own reviewer
# and brings the workspace-write sandbox with it. A resume keeps none of that, so
# it spells the same stance out again. These are the port's settings, and they
# are Codex's whole answer to never stalling for a human.
RESUME_PERMISSIONS = (
    'sandbox_mode="workspace-write"',
    NETWORK_ACCESS,
    'approval_policy="on-request"',
    'approvals_reviewer="auto_review"',
)


class Codex(Adapter):
    """Codex as one round of a session runs it."""

    program: ClassVar[str] = "codex"

    def first_round(self, launch: Launch) -> list[str]:
        """Return the command that runs a session's first round.

        The round runs in the session's worktree, so the command names no
        directory of its own.
        """
        return [
            self.program,
            "exec",
            "--json",
            "--approve-for-me",
            *_settings(launch),
            *_overrides(NETWORK_ACCESS),
            launch.prompt,
        ]

    def resume(self, launch: Launch) -> list[str]:
        """Return the command that resumes the session in this directory.

        Codex forgets the model and the effort when it resumes, so a resume
        replays both. Which session `--last` picks comes from the directory the
        round runs in, which Codex filters its own session store by.
        """
        return [
            self.program,
            "exec",
            "resume",
            "--last",
            "--json",
            *_settings(launch),
            *_overrides(*RESUME_PERMISSIONS),
            launch.prompt,
        ]

    def read(self, line: str) -> list[Event]:
        """Return the feed events one line of the stream carries.

        Not every line is an event. The CLI prints a warning now and then, and
        an event can arrive in a shape this does not expect. Either way the line
        goes to the feed as it is. So a line this cannot read costs one line of
        the feed, and never the round's story.
        """
        try:
            streamed = json.loads(line)
            return _events(streamed) if isinstance(streamed, dict) else [Prose(line)]
        except Exception:
            return [Prose(line)]


CODEX = Codex()


def _settings(launch: Launch) -> list[str]:
    """Return the model and the effort, which every round of a session names."""
    return [
        "--model",
        launch.model,
        *_overrides(f'model_reasoning_effort="{launch.effort}"'),
    ]


def _overrides(*settings: str) -> list[str]:
    """Return the settings as the pairs Codex takes an override as."""
    return [part for setting in settings for part in ("-c", setting)]


def _events(streamed: dict) -> list[Event]:
    """Return what one stream event carries, or nothing when it carries no story.

    An event this does not name carries no story. A turn starting says nothing
    the round's own boundary line does not, and an item starting or changing
    says nothing its completion will not say better.
    """
    kind = streamed["type"]
    if kind == "thread.started":
        return [Note("session", f"id {streamed['thread_id']}")]
    if kind == "item.completed":
        return _item(streamed["item"])
    if kind == "turn.completed":
        return [_spend(streamed["usage"])]
    # A failed turn is announced twice, first on its own and then as the turn's
    # ending. The ending is the one the feed keeps, so the failure reads once.
    if kind == "turn.failed":
        return [Note("failed", streamed["error"]["message"])]
    return []


def _item(item: dict) -> list[Event]:
    """Return what one completed item carries, labelled as Codex names it.

    An item this does not name carries no story. A todo list is the one such
    item a round really streams, and it arrives complete as the round ends, so
    it says nothing about what the round is doing.
    """
    kind = item["type"]
    if kind == "agent_message":
        return [Prose(item["text"])]
    if kind == "command_execution":
        return _command(item)
    if kind == "file_change":
        return [Note(kind, _changed(item["changes"]))]
    if kind == "web_search":
        return [Note(kind, item["query"])]
    if kind == "error":
        return [Note("failed", item["message"])]
    return []


def _command(item: dict) -> list[Event]:
    """Return the command the agent ran, and how it went unless it completed.

    The status is the label, so a command the reviewer declined reads as
    declined and one that failed reads as failed, without the feed deciding
    which of those Codex meant.
    """
    ran = Note(item["type"], item["command"])
    status = item["status"]
    if status == "completed":
        return [ran]
    return [ran, Note(status, item["aggregated_output"])]


def _changed(changes: list[dict]) -> str:
    """Return what one patch did to each file it touched.

    Codex reports every file of one patch together, so the line names each of
    them. What it did to a file is part of the story: a deletion is not an edit.
    """
    return ", ".join(f"{change['kind']} {change['path']}" for change in changes)


def _spend(usage: dict) -> Note:
    """Return what the round spent, in the tokens Codex counts.

    Codex prices nothing for us, so the feed reports tokens alone. Each count is
    the one the event names, because a cached input token is priced differently
    from a fresh one, and reasoning is the part of the output nothing else in the
    feed shows.
    """
    return Note(
        "usage",
        f"{usage['output_tokens']} output, "
        f"{usage['reasoning_output_tokens']} reasoning, "
        f"{usage['input_tokens']} input, "
        f"{usage['cached_input_tokens']} cache read, "
        f"{usage['cache_write_input_tokens']} cache write",
    )
