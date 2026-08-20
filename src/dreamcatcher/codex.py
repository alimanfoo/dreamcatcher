"""Run Codex, and read what it streams back."""

from typing import ClassVar

from dreamcatcher.adapters import Adapter, Launch
from dreamcatcher.feed import Event, Note, Prose

# Let the round reach the network from inside its sandbox, so it can talk to
# GitHub.
NETWORK_ACCESS = "sandbox_workspace_write.network_access=true"

# What an unattended round may do without being asked. The first round says it
# with `--approve-for-me`, which routes every approval to Codex's own reviewer
# and brings the workspace-write sandbox with it. A resume keeps none of that, so
# it says the same stance again as settings. These are the port's settings, and
# they are Codex's whole answer to never stalling for a human.
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
        replays both. Codex filters its own session store by the directory a
        round runs in. That directory is what makes `--last` pick this session.
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

    def _events(self, streamed: dict) -> list[Event]:
        """Return what one stream event carries, or nothing when it has no story.

        An event this does not name carries no story. The feed's own line for the
        round already says a turn has started. An item Codex has started or
        changed reaches the feed when it completes, which is when it says the
        most.
        """
        kind = streamed["type"]
        if kind == "thread.started":
            return [Note("session", f"id {streamed['thread_id']}")]
        if kind == "item.completed":
            return _item(streamed["item"])
        if kind == "turn.completed":
            return [_spend(streamed["usage"])]
        # Codex says a failure twice, first on its own and then as the turn's
        # ending. The ending is the one the feed keeps, so the failure reads once.
        if kind == "turn.failed":
            return [Note("failed", streamed["error"]["message"])]
        return []


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


def _item(item: dict) -> list[Event]:
    """Return what one completed item carries, in Codex's own words.

    An item the agent acted on becomes an action line: Codex's word for what the
    agent did, and the one thing it did it to. An error item is Codex speaking
    for itself rather than the agent acting, so it reads as what it is.

    An item this does not name carries no story. A todo list is the one such item
    a round really streams. It arrives complete as the round ends, so it says
    nothing about what the round is doing.
    """
    kind = item["type"]
    if kind == "agent_message":
        return [Prose(item["text"])]
    if kind == "command_execution":
        return _command(item)
    if kind == "file_change":
        # Codex reports every file of one patch together, so this is a line each.
        # What the patch did to a file is the label, which leaves the path as the
        # whole detail. The feed can then strip the round's own directory off it.
        return [Note(change["kind"], change["path"]) for change in item["changes"]]
    if kind == "web_search":
        return [Note(kind, item["query"])]
    if kind == "error":
        return [Note(kind, item["message"])]
    return []


def _command(item: dict) -> list[Event]:
    """Return the command the agent ran, and how that went.

    A command that completed needs no second line. One that did not gets its
    status as the label. A command the reviewer declined then reads as declined,
    and one that failed reads as failed, without the feed deciding which Codex
    meant.
    """
    ran = Note(item["type"], item["command"])
    status = item["status"]
    if status == "completed":
        return [ran]
    return [ran, Note(status, item["aggregated_output"])]


def _spend(usage: dict) -> Note:
    """Return what the round spent, in the tokens Codex counts.

    Codex prices nothing for us, so the feed reports tokens alone. Each count is
    the one the event names. Codex charges a different rate for a cached input
    token than for a fresh one, so adding the counts together would say less.
    Reasoning gets its own count because nothing else in the feed shows it.
    """
    return Note(
        "usage",
        f"{usage['output_tokens']} output, "
        f"{usage['reasoning_output_tokens']} reasoning, "
        f"{usage['input_tokens']} input, "
        f"{usage['cached_input_tokens']} cache read, "
        f"{usage['cache_write_input_tokens']} cache write",
    )
