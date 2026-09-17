"""Run Codex, and read what it streams back."""

from collections.abc import Sequence
from typing import ClassVar

from dreamcatcher.adapters import Adapter, HarnessOutput, Invocation, Launch
from dreamcatcher.feed import Event, Note, Prose

# Let the round reach the network from inside its sandbox, so it can talk to
# GitHub.
NETWORK_ACCESS = "sandbox_workspace_write.network_access=true"

# What Codex takes where a prompt would go, to read the prompt from stdin
# instead. Claude reads stdin as soon as its command names no prompt, so it
# needs no word of its own for this.
STDIN = "-"

# What an unattended round may do without being asked. The first round gets this
# from `--approve-for-me`, which sends every approval to Codex's own reviewer and
# turns on the workspace-write sandbox. A resume does not keep any of that, so it
# has to set the same permissions again itself. This is the port's list, and it is
# how Codex avoids ever stopping to wait for a person.
RESUME_PERMISSIONS = (
    'sandbox_mode="workspace-write"',
    NETWORK_ACCESS,
    'approval_policy="on-request"',
    'approvals_reviewer="auto_review"',
)


class Codex(Adapter):
    """Codex as one round of an agent assignment runs it."""

    program: ClassVar[str] = "codex"

    def build_first_round(self, *, launch: Launch) -> Invocation:
        """Return how to run an assignment's first round.

        The command does not say which directory to work in, so whoever runs
        it has to run it in the assignment's worktree.
        """
        return Invocation(
            program=self.program,
            arguments=[
                "exec",
                "--json",
                "--approve-for-me",
                *_settings(launch=launch),
                *_overrides(settings=[NETWORK_ACCESS]),
                STDIN,
            ],
            prompt=launch.prompt,
        )

    def build_resumed_round(
        self, *, launch: Launch, harness_session_identifier: str
    ) -> Invocation:
        """Return how to resume the identified harness session.

        Codex forgets the model and the effort when it resumes, so this sets
        both again.
        """
        return Invocation(
            program=self.program,
            arguments=[
                "exec",
                "resume",
                "--json",
                *_settings(launch=launch),
                *_overrides(settings=RESUME_PERMISSIONS),
                harness_session_identifier,
                STDIN,
            ],
            prompt=launch.prompt,
        )

    def build_hand_resume(self, *, harness_session_identifier: str) -> list[str]:
        """Return how a person carries on the identified harness session.

        `codex resume` is Codex's interactive resume, where `codex exec resume`
        is the headless one that every round of an assignment runs.
        """
        return [self.program, "resume", harness_session_identifier]

    def _read(self, *, streamed: dict) -> HarnessOutput:
        """Return what one parsed Codex event says.

        An event this does not handle gets no feed line. The feed writes its own
        opening line for a round, so it does not need the event that says a turn
        started. Codex reports each item three times, as it starts, as it
        changes and as it finishes, and only the last of those is complete.
        """
        kind = streamed["type"]
        if kind == "thread.started":
            identifier = str(streamed["thread_id"])
            return HarnessOutput(
                events=[Note(label="harness session", detail=f"id {identifier}")],
                harness_session_identifier=identifier,
            )
        if kind == "item.completed":
            return HarnessOutput(events=_item(item=streamed["item"]))
        if kind == "turn.completed":
            return HarnessOutput(events=[_usage(counts=streamed["usage"])])
        # When a turn fails, Codex sends the error twice: once on its own, then
        # again as the reason the turn failed. Keeping only this second one means
        # the reader sees the failure once.
        if kind == "turn.failed":
            return HarnessOutput(
                events=[Note(label="failed", detail=streamed["error"]["message"])]
            )
        return HarnessOutput(events=[])


CODEX = Codex()


def _settings(*, launch: Launch) -> list[str]:
    """Return the model and effort flags that every assignment round uses."""
    return [
        "--model",
        launch.model,
        *_overrides(settings=[f'model_reasoning_effort="{launch.effort}"']),
    ]


def _overrides(*, settings: Sequence[str]) -> list[str]:
    """Return each setting as the `-c setting` pair Codex expects."""
    return [part for setting in settings for part in ("-c", setting)]


def _item(*, item: dict) -> list[Event]:
    """Return the feed events one finished item turns into.

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
        return [Prose(text=item["text"])]
    if kind == "command_execution":
        return _command(item=item)
    if kind == "file_change":
        # Codex reports all the files of one patch in a single item, so give each
        # file its own line. Putting what happened to the file in the label
        # leaves the path as the whole detail, and the feed can then cut the
        # worktree's path off the front of it.
        return [
            Note(label=change["kind"], detail=change["path"])
            for change in item["changes"]
        ]
    if kind == "web_search":
        return [Note(label=kind, detail=item["query"])]
    if kind == "error":
        return [Note(label=kind, detail=item["message"])]
    return []


def _command(*, item: dict) -> list[Event]:
    """Return the command the agent ran, and how it went.

    A command that finished cleanly says all it needs to in one line. Anything
    else gets a second line, labelled with the status Codex gave it. So a failed
    command says `failed` and a declined one says `declined`, and this does not
    have to know which statuses Codex has.
    """
    ran = Note(label=item["type"], detail=item["command"])
    status = item["status"]
    if status == "completed":
        return [ran]
    return [ran, Note(label=status, detail=item["aggregated_output"])]


def _usage(*, counts: dict) -> Note:
    """Return what the round used, counted in tokens.

    Codex tells us no prices, so this reports tokens and no money. Each count
    keeps the name Codex gave it, and this does not add them up: a cached input
    token costs a different amount from a fresh one, so one total would tell the
    reader less than the separate counts do. Reasoning gets its own count
    because Codex sends no reasoning items, so the count is the only sign in the
    feed that the model thought at all.
    """
    return Note(
        label="usage",
        detail=f"{counts['output_tokens']} output, "
        f"{counts['reasoning_output_tokens']} reasoning, "
        f"{counts['input_tokens']} input, "
        f"{counts['cached_input_tokens']} cache read, "
        f"{counts['cache_write_input_tokens']} cache write",
    )
