"""Run Codex, and read what it streams back."""

from collections.abc import Sequence
from typing import ClassVar

from dreamcatcher.feed import FeedEvent, FeedNote, FeedProse
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    HarnessAdapter,
    HarnessInvocation,
    HarnessOutput,
    HarnessSessionIdentifier,
)

# Let the round reach the network from inside its sandbox, so it can talk to
# GitHub.
NETWORK_ACCESS_OVERRIDE = "sandbox_workspace_write.network_access=true"

# What Codex takes where a prompt would go, to read the prompt from stdin
# instead. Claude reads stdin as soon as its command names no prompt, so it
# needs no word of its own for this.
STDIN_ARGUMENT = "-"

# What an unattended round may do without being asked. The first round gets this
# from `--approve-for-me`, which sends every approval to Codex's own reviewer and
# turns on the workspace-write sandbox. A resume does not keep any of that, so it
# has to set the same permissions again itself. This is the port's list, and it is
# how Codex avoids ever stopping to wait for a person.
RESUME_PERMISSION_OVERRIDES = (
    'sandbox_mode="workspace-write"',
    NETWORK_ACCESS_OVERRIDE,
    'approval_policy="on-request"',
    'approvals_reviewer="auto_review"',
)


class CodexHarnessAdapter(HarnessAdapter):
    """Run Codex and translate its stream into feed events."""

    program: ClassVar[str] = "codex"

    def build_first_round(
        self, *, request: AgentRoundLaunchRequest
    ) -> HarnessInvocation:
        """Return how to run an assignment's first round.

        The command does not say which directory to work in, so whoever runs
        it has to run it in the assignment's worktree.
        """
        return HarnessInvocation(
            program=self.program,
            arguments=[
                "exec",
                "--json",
                "--approve-for-me",
                *_build_round_settings(request=request),
                *_build_config_overrides(settings=[NETWORK_ACCESS_OVERRIDE]),
                STDIN_ARGUMENT,
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

        Codex forgets the model and the effort when it resumes, so this sets
        both again.
        """
        return HarnessInvocation(
            program=self.program,
            arguments=[
                "exec",
                "resume",
                "--json",
                *_build_round_settings(request=request),
                *_build_config_overrides(settings=RESUME_PERMISSION_OVERRIDES),
                harness_session_identifier,
                STDIN_ARGUMENT,
            ],
            prompt=request.prompt,
        )

    def build_hand_resume(
        self, *, harness_session_identifier: HarnessSessionIdentifier
    ) -> list[str]:
        """Return how a person resumes the identified harness session.

        `codex resume` is Codex's interactive resume, where `codex exec resume`
        is the headless one that every round of an assignment runs.
        """
        return [self.program, "resume", harness_session_identifier]

    def _read(self, *, harness_event: dict) -> HarnessOutput:
        """Return what one parsed Codex event says.

        An event this does not handle gets no feed line. The feed writes its own
        opening line for a round, so it does not need the event that says a turn
        started. Codex reports each item three times, as it starts, as it
        changes and as it finishes, and only the last of those is complete.
        """
        kind = harness_event["type"]
        if kind == "thread.started":
            identifier = harness_event["thread_id"]
            if not isinstance(identifier, str):
                raise TypeError("Codex reported a non-text harness session identifier")
            return HarnessOutput(
                events=[FeedNote(label="harness session", detail=f"id {identifier}")],
                harness_session_identifier=identifier,
            )
        if kind == "item.completed":
            return HarnessOutput(
                events=_read_completed_item(item=harness_event["item"])
            )
        if kind == "turn.completed":
            return HarnessOutput(
                events=[_compose_usage_note(counts=harness_event["usage"])]
            )
        # When a turn fails, Codex sends the error twice: once on its own, then
        # again as the reason the turn failed. Keeping only this second one means
        # the reader sees the failure once.
        if kind == "turn.failed":
            return HarnessOutput(
                events=[
                    FeedNote(label="failed", detail=harness_event["error"]["message"])
                ]
            )
        return HarnessOutput(events=[])


CODEX_ADAPTER = CodexHarnessAdapter()


def _build_round_settings(*, request: AgentRoundLaunchRequest) -> list[str]:
    """Return the model and effort flags that every assignment round uses."""
    return [
        "--model",
        request.model,
        *_build_config_overrides(
            settings=[f'model_reasoning_effort="{request.effort}"']
        ),
    ]


def _build_config_overrides(*, settings: Sequence[str]) -> list[str]:
    return [part for setting in settings for part in ("-c", setting)]


def _read_completed_item(*, item: dict) -> list[FeedEvent]:
    """Return the feed events represented by a completed Codex item.

    When the agent does something, the item becomes one action line. Codex's own
    name for the item is the label, and the detail is the thing the agent acted
    on. An error item is different. That is Codex reporting a problem of its own
    rather than the agent doing anything, so its label says so.

    An item this does not handle gets no feed line. The only one a round really
    sends is a todo list, and it arrives finished just as the round ends, so it
    says nothing about what the round is doing.
    """
    kind = item["type"]
    if kind == "agent_message":
        return [FeedProse(text=item["text"])]
    if kind == "command_execution":
        return _read_command_execution(item=item)
    if kind == "file_change":
        # Codex reports all the files of one patch in a single item, so give each
        # file its own line. Putting what happened to the file in the label
        # leaves the path as the whole detail, and the feed can then cut the
        # worktree's path off the front of it.
        return [
            FeedNote(label=change["kind"], detail=change["path"])
            for change in item["changes"]
        ]
    if kind == "web_search":
        return [FeedNote(label=kind, detail=item["query"])]
    if kind == "error":
        return [FeedNote(label=kind, detail=item["message"])]
    return []


def _read_command_execution(*, item: dict) -> list[FeedEvent]:
    """Return the command and any non-successful outcome that Codex reported.

    A command that finished cleanly says all it needs to in one line. Anything
    else gets a second line, labelled with the status Codex gave it. So a failed
    command says `failed` and a declined one says `declined`, and this does not
    have to know which statuses Codex has.
    """
    command_note = FeedNote(label=item["type"], detail=item["command"])
    status = item["status"]
    if status == "completed":
        return [command_note]
    return [
        command_note,
        FeedNote(label=status, detail=item["aggregated_output"]),
    ]


def _compose_usage_note(*, counts: dict) -> FeedNote:
    """Return the round's separate token counts.

    Codex tells us no prices, so this reports tokens and no money. Each count
    keeps the name Codex gave it, and this does not add them up: a cached input
    token costs a different amount from a fresh one, so one total would tell the
    reader less than the separate counts do. Reasoning gets its own count
    because Codex sends no reasoning items, so the count is the only sign in the
    feed that the model thought at all.
    """
    return FeedNote(
        label="usage",
        detail=f"{counts['output_tokens']} output, "
        f"{counts['reasoning_output_tokens']} reasoning, "
        f"{counts['input_tokens']} input, "
        f"{counts['cached_input_tokens']} cache read, "
        f"{counts['cache_write_input_tokens']} cache write",
    )
