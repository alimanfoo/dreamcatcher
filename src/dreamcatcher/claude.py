"""Run Claude Code, and read what it streams back."""

import json
from collections.abc import Callable
from typing import ClassVar

from dreamcatcher.adapters import Adapter, Invocation, Launch
from dreamcatcher.feed import Event, Note, Prose

# What an unattended round may do without being asked, and nothing else. The
# round runs under `--permission-mode auto`, so this list is Claude's whole
# answer to never stalling for a human. It is the port's list.
ALLOWED_TOOLS = (
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

# The inputs of a tool call that say most about it, most telling first. The
# whole input comes last, so a tool none of these names still says something.
TELLING_INPUTS = (
    "command",
    "file_path",
    "pattern",
    "url",
    "skill",
    "description",
    "prompt",
)


class Claude(Adapter):
    """Claude Code as one round of a session runs it."""

    program: ClassVar[str] = "claude"

    def build_first_round(self, launch: Launch) -> Invocation:
        """Return how to run a session's first round.

        The command names no prompt, which is how Claude knows to read one
        from stdin.
        """
        return Invocation(
            program=self.program,
            arguments=[
                *self._base(launch),
                "--model",
                launch.model,
                "--effort",
                launch.effort,
            ],
            prompt=launch.prompt,
        )

    def build_resumed_round(self, launch: Launch) -> Invocation:
        """Return how to continue the session in this directory.

        Claude recovers the model and the effort itself, so a resume replays
        neither.
        """
        return Invocation(
            program=self.program,
            arguments=[*self._base(launch), "--continue"],
            prompt=launch.prompt,
        )

    def build_hand_resume(self) -> list[str]:
        """Return how a person carries on the session in this directory.

        Claude continues the newest conversation of the directory it runs in,
        which is the session's own.
        """
        return [self.program, "--continue"]

    def _events(self, streamed: dict) -> list[Event]:
        """Return the feed events one Claude event turns into."""
        is_subagent = streamed.get("parent_tool_use_id") is not None
        kind = streamed["type"]
        if kind == "system":
            return _system(streamed)
        if kind == "assistant":
            return _blocks(streamed, _spoken, is_subagent)
        if kind == "user":
            return _blocks(streamed, _failure, is_subagent)
        if kind == "result":
            return _closing(streamed)
        return []

    def _base(self, launch: Launch) -> list[str]:
        """Return the arguments every round shares."""
        return [
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "auto",
            "--allowedTools",
            " ".join(ALLOWED_TOOLS),
            "--name",
            launch.session,
        ]


CLAUDE = Claude()


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
            Note("report", streamed["status"], is_subagent=True),
            Prose(streamed["summary"], is_subagent=True),
        ]
    # A retried round says nothing else while it waits, and ten retries of a
    # rate limit take about three minutes, so the feed says what it waits on.
    if subtype == "api_retry":
        return [
            Note(
                "retry",
                f"{streamed['error']} ({streamed['error_status']}), "
                f"attempt {streamed['attempt']} of {streamed['max_retries']}",
            )
        ]
    return []


def _blocks(
    streamed: dict, read: Callable[[dict, bool], list[Event]], is_subagent: bool
) -> list[Event]:
    """Return what every block of one message carries."""
    return [
        event
        for block in streamed["message"]["content"]
        for event in read(block, is_subagent)
    ]


def _spoken(block: dict, is_subagent: bool) -> list[Event]:
    """Return what one block of an assistant message carries."""
    kind = block["type"]
    if kind == "text":
        # A subagent's own words reach the feed as its report, so the feed does
        # not carry them twice.
        return [] if is_subagent else [Prose(block["text"])]
    if kind == "thinking":
        # Claude streams the block without the thinking in it, so the feed says
        # the agent thought and cannot say what it thought.
        return [Note("thinking", is_subagent=is_subagent)]
    if kind == "tool_use":
        return [
            Note(block["name"], _telling_input(block["input"]), is_subagent=is_subagent)
        ]
    return []


def _failure(block: dict, is_subagent: bool) -> list[Event]:
    """Return the failure one block of a user message carries, if it failed."""
    if block["type"] == "tool_result" and block.get("is_error"):
        return [Note("failed", _text(block["content"]), is_subagent=is_subagent)]
    return []


def _closing(streamed: dict) -> list[Event]:
    """Return the lines that close the round: what it used, then how it ended.

    The subtype reads "success" even on a round that failed, so the event's own
    error flag is what the feed reports.
    """
    used = _usage(streamed["total_cost_usd"], streamed["usage"])
    if streamed.get("is_error"):
        return [used, Note("failed", _text(streamed["result"]))]
    return [used, Note("result", streamed["subtype"])]


def _usage(cost: float, counts: dict) -> Note:
    """Return what the round used, in money and in tokens.

    Each count keeps the name the event gave it, and this does not add them up.
    A cache read and a cache write each cost a different amount from a fresh
    input token, so one total would tell the reader less than the separate
    counts do.
    """
    return Note(
        "usage",
        f"${cost:.4f}, "
        f"{counts['output_tokens']} output, "
        f"{counts['input_tokens']} input, "
        f"{counts['cache_read_input_tokens']} cache read, "
        f"{counts['cache_creation_input_tokens']} cache write",
    )


def _telling_input(given: dict) -> str:
    """Return the one input that says most about what a tool call is doing."""
    for name in TELLING_INPUTS:
        if given.get(name):
            return _text(given[name])
    return _text(given)


def _text(value: object) -> str:
    """Return a value out of the stream as feed text, as JSON unless it is text.

    A tool result's content, and a failed round's message, each arrive sometimes
    as a string and sometimes as a list of blocks.
    """
    return value if isinstance(value, str) else json.dumps(value)
