"""Run Codex, and read what it streams back."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import AfterValidator, StringConstraints

from dreamcatcher.commands import refuse_unquotable
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedEvent, FeedNote, FeedProse
from dreamcatcher.harness_adapters import (
    AgentRoundLaunchRequest,
    AgentWorkKind,
    HarnessAdapter,
    HarnessConfig,
    HarnessConfigValue,
    HarnessInvocation,
    HarnessOutput,
    HarnessSessionIdentifier,
)

# Let the round reach the network from inside its sandbox, so it can talk to
# GitHub.
_NETWORK_ACCESS_SETTING = {"sandbox_workspace_write.network_access": True}

# What Codex takes where a prompt would go, to read the prompt from stdin
# instead. Claude reads stdin as soon as its command names no prompt, so it
# needs no word of its own for this.
_STDIN_ARGUMENT = "-"

# What an unattended assignment resume may do without being asked. Its first
# round gets this from `--approve-for-me`, but a resume does not keep it, so the
# resumed command has to set the same permissions again itself.
_ASSIGNMENT_RESUME_PERMISSION_SETTINGS = {
    "sandbox_mode": "workspace-write",
    **_NETWORK_ACCESS_SETTING,
    "approval_policy": "on-request",
    "approvals_reviewer": "auto_review",
}

# A conversation may write scratch files and make issue changes on GitHub, but
# it must not ask a person to approve wider access.
_CONVERSATION_PERMISSION_SETTINGS = {
    "sandbox_mode": "workspace-write",
    **_NETWORK_ACCESS_SETTING,
    "approval_policy": "never",
}

_EFFORT_KEY = "model_reasoning_effort"

# Every setting that Dreamcatcher keeps for itself: those it gives Codex, and a
# permissions profile, which Codex would apply in place of the sandbox settings.
# A recipe's own setting of one, or of a key inside one, would compete with the
# model, the effort or the permissions that an unattended round needs.
_DREAMCATCHER_SETTING_KEYS = frozenset(
    {
        "model",
        _EFFORT_KEY,
        *_ASSIGNMENT_RESUME_PERMISSION_SETTINGS,
        *_CONVERSATION_PERMISSION_SETTINGS,
        "default_permissions",
        "permissions",
    }
)


def _refuse_unusable_codex_config(config: HarnessConfig, /) -> HarnessConfig:
    """Return config, or raise ValueError naming a setting no round can use.

    pydantic is what calls this, as the validator behind `CodexConfig`, and it
    passes the config positionally, so the parameter is positional-only.
    """
    kept_keys = [
        key
        for key in sorted(config)
        if any(
            key == kept or key.startswith(f"{kept}.")
            for kept in _DREAMCATCHER_SETTING_KEYS
        )
    ]
    if kept_keys:
        raise ValueError(
            f"cannot set {' or '.join(kept_keys)}, which Dreamcatcher keeps for itself"
        )
    for key, value in config.items():
        try:
            refuse_unquotable(_compose_config_argument(key=key, value=value))
        except ValueError as error:
            raise ValueError(f"{key} {error}") from error
    return config


# A dotted path of TOML bare keys, as `-c` reads it. Any other text could name
# one of Dreamcatcher's own settings in a form that the refusal does not match.
_CodexConfigKey = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")
]

# Settings that every round of one piece of agent work passes to Codex, each
# with `-c`.
CodexConfig = Annotated[
    dict[_CodexConfigKey, HarnessConfigValue],
    AfterValidator(_refuse_unusable_codex_config),
]


class _CodexHarnessAdapter(HarnessAdapter):
    """Run Codex and translate its stream into feed events."""

    program: ClassVar[str] = "codex"

    def build_first_round(
        self, *, request: AgentRoundLaunchRequest, final_output_path: Path
    ) -> HarnessInvocation:
        """Return how to run an agent work item's first round.

        The command does not say which directory to work in, so whoever runs
        it has to run it in the agent work item's worktree.
        """
        round_arguments = (
            [
                *_build_round_settings(request=request),
                *_build_config_arguments(settings=_CONVERSATION_PERMISSION_SETTINGS),
            ]
            if request.work_kind is AgentWorkKind.CONVERSATION
            else [
                "--approve-for-me",
                *_build_round_settings(request=request),
                *_build_config_arguments(settings=_NETWORK_ACCESS_SETTING),
            ]
        )
        return HarnessInvocation(
            program=self.program,
            arguments=[
                "exec",
                "--json",
                *round_arguments,
                *_build_final_output_arguments(
                    request=request, final_output_path=final_output_path
                ),
                _STDIN_ARGUMENT,
            ],
            prompt=request.prompt,
        )

    def build_resumed_round(
        self,
        *,
        request: AgentRoundLaunchRequest,
        harness_session_identifier: HarnessSessionIdentifier,
        final_output_path: Path,
    ) -> HarnessInvocation:
        """Return how to resume the identified harness session.

        Codex forgets the model and the effort when it resumes, so this sets
        both again.
        """
        permission_settings = (
            _CONVERSATION_PERMISSION_SETTINGS
            if request.work_kind is AgentWorkKind.CONVERSATION
            else _ASSIGNMENT_RESUME_PERMISSION_SETTINGS
        )
        return HarnessInvocation(
            program=self.program,
            arguments=[
                "exec",
                "resume",
                "--json",
                *_build_round_settings(request=request),
                *_build_config_arguments(settings=permission_settings),
                *_build_final_output_arguments(
                    request=request, final_output_path=final_output_path
                ),
                harness_session_identifier,
                _STDIN_ARGUMENT,
            ],
            prompt=request.prompt,
        )

    def build_hand_resume(
        self, *, harness_session_identifier: HarnessSessionIdentifier
    ) -> list[str]:
        """Return the command that resumes the harness session interactively.

        `codex resume` is Codex's interactive resume, where `codex exec resume`
        is the headless command that resumed assignment rounds use.
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


def _build_final_output_arguments(
    *, request: AgentRoundLaunchRequest, final_output_path: Path
) -> list[str]:
    """Return Codex's final-message file arguments for a conversation."""
    if request.work_kind is not AgentWorkKind.CONVERSATION:
        return []
    try:
        output_path = refuse_unquotable(str(final_output_path))
    except ValueError as error:
        raise ReportableError(
            f"{request.agent_work_identifier}'s final output path {error}."
        ) from error
    return ["--output-last-message", output_path]


CODEX_ADAPTER = _CodexHarnessAdapter()


def _build_round_settings(*, request: AgentRoundLaunchRequest) -> list[str]:
    """Return the model, effort and Codex config flags that every round uses."""
    return [
        "--model",
        request.model,
        *_build_config_arguments(
            settings={_EFFORT_KEY: request.effort, **request.harness_config}
        ),
    ]


def _build_config_arguments(*, settings: Mapping[str, HarnessConfigValue]) -> list[str]:
    return [
        part
        for key, value in settings.items()
        for part in ("-c", _compose_config_argument(key=key, value=value))
    ]


def _compose_config_argument(*, key: str, value: HarnessConfigValue) -> str:
    """Return the setting as `-c` takes it, with the value written as TOML.

    JSON writes a boolean, an integer and a string as TOML does, except that
    TOML refuses a delete character inside a string.
    """
    toml_value = json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
    return f"{key}={toml_value}"


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
