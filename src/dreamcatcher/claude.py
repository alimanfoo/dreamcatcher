"""Run Claude Code, and read what it streams back."""

import json
from typing import ClassVar, Protocol

from dreamcatcher.feed import FeedEvent, FeedNote, FeedProse
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
    HarnessSessionIdentifier,
)

# What an unattended round may do without being asked, and nothing else. The
# round runs under `--permission-mode auto`, so this list is Claude's whole
# answer to never stalling for a human. It is the port's list.
CLAUDE_ALLOWED_TOOLS = (
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
TOOL_INPUT_KEYS_BY_PRIORITY = (
    "command",
    "file_path",
    "pattern",
    "url",
    "skill",
    "description",
    "prompt",
)


class ClaudeHarnessAdapter(HarnessAdapter):
    """Run Claude Code and translate its stream into feed events."""

    program: ClassVar[str] = "claude"

    def build_first_round(
        self, *, request: AgentRoundLaunchRequest
    ) -> HarnessInvocation:
        """Return how to run an assignment's first round.

        The command names no prompt, which is how Claude knows to read one
        from stdin.
        """
        return HarnessInvocation(
            program=self.program,
            arguments=[
                *self._build_base_arguments(request=request),
                "--model",
                request.model,
                "--effort",
                request.effort,
            ],
            prompt=request.prompt,
        )

    def build_resumed_round(
        self,
        *,
        request: AgentRoundLaunchRequest,
        harness_session_identifier: HarnessSessionIdentifier,
    ) -> HarnessInvocation:
        """Return how to resume the identified harness session.

        Claude recovers the model and the effort itself, so a resume replays
        neither.
        """
        return HarnessInvocation(
            program=self.program,
            arguments=[
                *self._build_base_arguments(request=request),
                "--resume",
                harness_session_identifier,
            ],
            prompt=request.prompt,
        )

    def build_hand_resume(
        self, *, harness_session_identifier: HarnessSessionIdentifier
    ) -> list[str]:
        """Return the command that resumes the harness session interactively."""
        return [self.program, "--resume", harness_session_identifier]

    def _read(self, *, harness_event: dict) -> HarnessOutput:
        """Return what one parsed Claude event says."""
        is_subagent = harness_event.get("parent_tool_use_id") is not None
        kind = harness_event["type"]
        if kind == "system":
            return _read_system_event(harness_event=harness_event)
        if kind == "assistant":
            events = _read_message_blocks(
                harness_event=harness_event,
                read_block=_read_assistant_block,
                is_subagent=is_subagent,
            )
            return HarnessOutput(events=events)
        if kind == "user":
            events = _read_message_blocks(
                harness_event=harness_event,
                read_block=_read_tool_failure,
                is_subagent=is_subagent,
            )
            return HarnessOutput(events=events)
        if kind == "result":
            return HarnessOutput(events=_read_round_result(harness_event=harness_event))
        return HarnessOutput(events=[])

    def _build_base_arguments(self, *, request: AgentRoundLaunchRequest) -> list[str]:
        """Return the arguments every round shares."""
        return [
            "--print",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "auto",
            "--allowedTools",
            " ".join(CLAUDE_ALLOWED_TOOLS),
            "--name",
            request.agent_work_identifier,
        ]


CLAUDE_ADAPTER = ClaudeHarnessAdapter()


def _read_system_event(*, harness_event: dict) -> HarnessOutput:
    """Return a system event's harness session, report, or nothing."""
    subtype = harness_event["subtype"]
    if subtype == "init":
        identifier = harness_event["session_id"]
        if not isinstance(identifier, str):
            raise TypeError("Claude reported a non-text harness session identifier")
        return HarnessOutput(
            events=[
                FeedNote(
                    label="harness session",
                    detail=f"model {harness_event['model']}, id {identifier}",
                )
            ],
            harness_session_identifier=identifier,
        )
    # A subagent reports its token usage as it finishes, and a background
    # command does not, so the usage is what tells the two events apart.
    if subtype == "task_notification" and harness_event.get("usage") is not None:
        return HarnessOutput(
            events=[
                FeedNote(
                    label="report", detail=harness_event["status"], is_subagent=True
                ),
                FeedProse(text=harness_event["summary"], is_subagent=True),
            ]
        )
    # A retried round says nothing else while it waits, and ten retries of a
    # rate limit take about three minutes, so the feed says what it waits on.
    if subtype == "api_retry":
        return HarnessOutput(
            events=[
                FeedNote(
                    label="retry",
                    detail=(
                        f"{harness_event['error']} "
                        f"({harness_event['error_status']}), attempt "
                        f"{harness_event['attempt']} of "
                        f"{harness_event['max_retries']}"
                    ),
                )
            ]
        )
    return HarnessOutput(events=[])


class _ReadsClaudeBlock(Protocol):
    """Read one block from a Claude message."""

    def __call__(self, *, block: dict, is_subagent: bool) -> list[FeedEvent]:
        """Return what one block carries."""


def _read_message_blocks(
    *,
    harness_event: dict,
    read_block: _ReadsClaudeBlock,
    is_subagent: bool,
) -> list[FeedEvent]:
    """Return what every block of one message carries."""
    return [
        event
        for block in harness_event["message"]["content"]
        for event in read_block(block=block, is_subagent=is_subagent)
    ]


def _read_assistant_block(*, block: dict, is_subagent: bool) -> list[FeedEvent]:
    """Return what one block of an assistant message carries."""
    kind = block["type"]
    if kind == "text":
        # A subagent's own words reach the feed as its report, so the feed does
        # not carry them twice.
        return [] if is_subagent else [FeedProse(text=block["text"])]
    if kind == "thinking":
        # Claude streams the block without the thinking in it, so the feed says
        # the agent thought and cannot say what it thought.
        return [FeedNote(label="thinking", is_subagent=is_subagent)]
    if kind == "tool_use":
        return [
            FeedNote(
                label=block["name"],
                detail=_describe_tool_input(tool_input=block["input"]),
                is_subagent=is_subagent,
            )
        ]
    return []


def _read_tool_failure(*, block: dict, is_subagent: bool) -> list[FeedEvent]:
    """Return the failure one block of a user message carries, if it failed."""
    if block["type"] == "tool_result" and block.get("is_error"):
        return [
            FeedNote(
                label="failed",
                detail=_render_value_as_text(value=block["content"]),
                is_subagent=is_subagent,
            )
        ]
    return []


def _read_round_result(*, harness_event: dict) -> list[FeedEvent]:
    """Return the usage and outcome events that close the round.

    The subtype reads "success" even on a round that failed, so the event's own
    error flag is what the feed reports.
    """
    usage_note = _compose_usage_note(
        cost=harness_event["total_cost_usd"], counts=harness_event["usage"]
    )
    if harness_event.get("is_error"):
        return [
            usage_note,
            FeedNote(
                label="failed",
                detail=_render_value_as_text(value=harness_event["result"]),
            ),
        ]
    return [usage_note, FeedNote(label="result", detail=harness_event["subtype"])]


def _compose_usage_note(*, cost: float, counts: dict) -> FeedNote:
    """Return the round's cost and separate token counts.

    Each count keeps the name the event gave it, and this does not add them up.
    A cache read and a cache write each cost a different amount from a fresh
    input token, so one total would tell the reader less than the separate
    counts do.
    """
    return FeedNote(
        label="usage",
        detail=f"${cost:.4f}, "
        f"{counts['output_tokens']} output, "
        f"{counts['input_tokens']} input, "
        f"{counts['cache_read_input_tokens']} cache read, "
        f"{counts['cache_creation_input_tokens']} cache write",
    )


def _describe_tool_input(*, tool_input: dict) -> str:
    """Return the one input that says most about what a tool call is doing."""
    for name in TOOL_INPUT_KEYS_BY_PRIORITY:
        if tool_input.get(name):
            return _render_value_as_text(value=tool_input[name])
    return _render_value_as_text(value=tool_input)


def _render_value_as_text(*, value: object) -> str:
    """Return a value out of the stream as feed text, as JSON unless it is text.

    A tool result's content, and a failed round's message, each arrive sometimes
    as a string and sometimes as a list of blocks.
    """
    return value if isinstance(value, str) else json.dumps(value)
