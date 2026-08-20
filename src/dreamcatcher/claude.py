"""Run Claude Code, and read what it streams back."""

import json
from collections.abc import Callable
from typing import ClassVar

from dreamcatcher.adapters import Adapter, Launch
from dreamcatcher.feed import Event, Note, Prose

# What an unattended round may write, and nothing else. The round runs under
# `--permission-mode auto`, so this list is Claude's whole answer to never
# stalling for a human. It is the port's list.
WRITES = (
    "Bash(gh pr create:*)",
    "Bash(gh pr comment:*)",
    "Bash(gh pr edit:*)",
    "Bash(gh pr ready:*)",
    "Bash(gh pr close:*)",
    "Bash(gh issue create:*)",
    "Bash(gh issue comment:*)",
    "Bash(git commit:*)",
    "Bash(git push:*)",
)

# The inputs that say most about a tool call, most telling first. The whole
# input comes last, so a tool none of these names still says something.
TELLING = ("command", "file_path", "pattern", "url", "skill", "description", "prompt")


class Claude(Adapter):
    """Claude Code as one round of a session runs it."""

    program: ClassVar[str] = "claude"

    def first_round(self, launch: Launch) -> list[str]:
        """Return the command that runs a session's first round."""
        return [
            *self._base(launch),
            "--model",
            launch.model,
            "--effort",
            launch.effort,
            launch.prompt,
        ]

    def resume(self, launch: Launch) -> list[str]:
        """Return the command that continues the session in this directory.

        Claude recovers the model and the effort itself, so a resume replays
        neither.
        """
        return [*self._base(launch), "--continue", launch.prompt]

    def read(self, line: str) -> list[Event]:
        """Return the feed events one line of the stream carries.

        A line this cannot read reaches the feed unchanged. So a warning the CLI
        prints, or an event shaped in a way this does not expect, costs one line
        and never the round's story.
        """
        try:
            streamed = json.loads(line)
            return _events(streamed) if isinstance(streamed, dict) else [Prose(line)]
        except Exception:
            return [Prose(line)]

    def _base(self, launch: Launch) -> list[str]:
        """Return the part of the command every round shares."""
        return [
            self.program,
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "auto",
            "--allowedTools",
            " ".join(WRITES),
            "--name",
            launch.session,
        ]


CLAUDE = Claude()


def _events(streamed: dict) -> list[Event]:
    """Return what one stream event carries, or nothing when it carries no story."""
    subagent = streamed.get("parent_tool_use_id") is not None
    kind = streamed["type"]
    if kind == "system":
        return _system(streamed)
    if kind == "assistant":
        return _blocks(streamed, _spoken, subagent)
    if kind == "user":
        return _blocks(streamed, _failure, subagent)
    if kind == "result":
        return _closing(streamed)
    return []


def _system(streamed: dict) -> list[Event]:
    """Return what a system event carries: the session, a report, or nothing."""
    subtype = streamed["subtype"]
    if subtype == "init":
        return [
            Note("session", f"model {streamed['model']}, id {streamed['session_id']}")
        ]
    # A subagent reports its token usage as it finishes, and a background
    # command does not, so the usage is what tells the two events apart.
    if subtype == "task_notification" and streamed.get("usage") is not None:
        return [
            Note("report", streamed["status"], subagent=True),
            Prose(streamed["summary"], subagent=True),
        ]
    return []


def _blocks(
    streamed: dict, read: Callable[[dict, bool], list[Event]], subagent: bool
) -> list[Event]:
    """Return what every block of one message carries."""
    return [
        event
        for block in streamed["message"]["content"]
        for event in read(block, subagent)
    ]


def _spoken(block: dict, subagent: bool) -> list[Event]:
    """Return what one block of an assistant message carries."""
    kind = block["type"]
    if kind == "text":
        # A subagent's own words reach the feed as its report, so the feed does
        # not carry them twice.
        return [] if subagent else [Prose(block["text"])]
    if kind == "thinking":
        # Claude streams the block without the thinking in it, so the feed says
        # the agent thought and cannot say what it thought.
        return [Note("thinking", subagent=subagent)]
    if kind == "tool_use":
        return [Note(block["name"], _telling(block["input"]), subagent=subagent)]
    return []


def _failure(block: dict, subagent: bool) -> list[Event]:
    """Return the failure one block of a user message carries, if it failed."""
    if block["type"] == "tool_result" and block.get("is_error"):
        return [Note("failed", str(block["content"]), subagent=subagent)]
    return []


def _closing(streamed: dict) -> list[Event]:
    """Return the line that closes the round.

    The subtype reads "success" even on a round that failed, so the event's own
    error flag is what the feed reports.
    """
    if streamed.get("is_error"):
        return [Note("failed", str(streamed["result"]))]
    return [Note("result", streamed["subtype"])]


def _telling(given: dict) -> str:
    """Return the one input that says what a tool call is about."""
    for name in TELLING:
        if given.get(name):
            return str(given[name])
    return json.dumps(given)
