"""Render issue conversations in terminal views."""

import shutil
from datetime import timedelta
from io import StringIO

import pytest
from clocks import PINNED
from records import (
    find_conversation_directory,
    hold_daemon_lock_for_test,
    write_conversation,
    write_ending,
    write_feed,
    write_final_output,
    write_round,
    write_running_conversation,
    write_tick,
)
from rich.console import Console
from rows import request_row
from status_fabrications import conversation_row

from dreamcatcher.agent_rounds import (
    AgentRoundRecord,
    _compose_agent_round_ending,
)
from dreamcatcher.agent_work import AgentWorkEndReason
from dreamcatcher.documents import write_json, write_text
from dreamcatcher.errors import ReportableError
from dreamcatcher.feed import FeedLine
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.issue_conversations import (
    ConversationRoundInput,
    InitialConversationIssue,
)
from dreamcatcher.scheduler.models import (
    ConflictingLabelsFinding,
    IssueCommentsFinding,
    PauseCause,
    PausedFinding,
    ReadFailureFinding,
    SchedulerRecord,
)
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import (
    show_agent_work_view,
    show_feed_view,
    show_status_view,
)


def conversation_state(
    *,
    root,
    status: int = 0,
    is_paused: bool = True,
    harness_session_identifier: str | None = "conversation-session",
) -> StateDirectory:
    """Return state containing one finished conversation.

    The tick after a round that errored still finds its comment to answer.
    """
    state = StateDirectory(root=root)
    directory = write_conversation(
        state=state,
        issue=8,
        harness_session_identifier=harness_session_identifier,
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(
            number=1,
            started=PINNED,
            pid=1,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=4), status=status
            ),
        ),
    )
    write_json(
        document=ConversationRoundInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
            comments=[
                {
                    "id": 1,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123",
        ),
        path=(directory / "rounds" / "1" / "round-input.json"),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=PINNED, text="I found the answer.")],
    )
    write_final_output(directory=directory, number=1, text="The answer.")
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED + timedelta(minutes=5),
            rows=[
                conversation_row(
                    ended_round=1,
                    finding=(
                        PausedFinding(cause=PauseCause.LABEL_REMOVED)
                        if is_paused
                        else IssueCommentsFinding(new_comments=int(status != 0))
                    ),
                )
            ],
        ),
    )
    return state


def rendered_console() -> tuple[Console, StringIO]:
    """Return a plain fixed-width console and the text it writes."""
    written = StringIO()
    return Console(file=written, width=100, color_system=None), written


def test_status_lists_the_conversation(tmp_path):
    state = conversation_state(root=tmp_path, is_paused=False)
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        clock=lambda: PINNED,
    )

    shown = written.getvalue()
    assert "conversations" in shown
    assert "GH8" in shown
    assert "idle" in shown
    assert "round 1, answered, ran 4m" in shown


def test_conversation_detail_shows_settings_revision_session_and_round(tmp_path):
    state = conversation_state(root=tmp_path, harness_session_identifier=None)
    directory = find_conversation_directory(state=state, issue=8)
    write_text(
        text=(
            '{"type":"system","subtype":"init","model":"claude-opus-5",'
            '"session_id":"recovered-session"}\n'
        ),
        path=directory / "rounds" / "1" / "raw.jsonl",
    )
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED + timedelta(minutes=6),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=10), status=0
            ),
        ),
    )
    write_json(
        document=ConversationRoundInput(
            issue=8,
            initial_issue=InitialConversationIssue(
                title="Issue 8",
                body="Explain it.",
            ),
            comments=[
                {
                    "id": 2,
                    "body": "Does that still hold?",
                    "author": "alice",
                    "written_at": "2026-09-23T02:00:00Z",
                }
            ],
            revision="def456",
        ),
        path=(directory / "rounds" / "2" / "round-input.json"),
    )
    console, written = rendered_console()

    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
    )

    shown = written.getvalue()
    assert "conversation GH8-" in shown
    assert "recovered-session" in shown
    assert "abc123" in shown
    assert "def456" in shown
    assert "opus[1m]" in shown
    assert "1 comment" in shown
    assert "successful" in shown
    assert "resume by hand" in shown
    assert "cd .dreamcatcher/v6/worktrees/GH8-20260819-184158-conversation" in shown
    assert "claude --resume recovered-session" in shown


def test_conversation_detail_shows_a_failed_round(tmp_path):
    state = conversation_state(root=tmp_path, status=2, is_paused=False)
    console, written = rendered_console()

    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
    )

    assert "waiting  round 1 errored (exit 2)" in written.getvalue()


def test_conversation_detail_shows_two_errors_as_a_fault(tmp_path):
    state = conversation_state(root=tmp_path, status=2, is_paused=False)
    directory = find_conversation_directory(state=state, issue=8)
    write_round(
        directory=directory,
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED + timedelta(minutes=5),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=8), status=2
            ),
        ),
    )
    write_json(
        document=ConversationRoundInput(
            issue=8,
            comments=[
                {
                    "id": 1,
                    "body": "Please explain.",
                    "author": "alice",
                    "written_at": "2026-09-23T01:00:00Z",
                }
            ],
            revision="abc123",
        ),
        path=directory / "rounds" / "2" / "round-input.json",
    )
    console, written = rendered_console()
    console.width = 140

    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
    )

    shown = written.getvalue()
    assert "fault  round 2 errored (exit 2)" in shown
    assert "round 2 errored" in shown


def test_conversation_feed_shows_its_saved_activity(tmp_path):
    state = conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_feed_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
    )

    shown = written.getvalue()
    assert "round 1: 1 comment" in shown
    assert "I found the answer." in shown


def test_conversation_feed_follows_a_later_round_without_repeating_the_first(
    tmp_path,
):
    state = conversation_state(root=tmp_path, is_paused=False)
    written = StringIO()
    console = Console(
        file=written,
        width=100,
        color_system=None,
        force_terminal=True,
    )

    def wait(seconds, /):
        assert seconds > 0
        directory = find_conversation_directory(state=state, issue=8)
        write_round(
            directory=directory,
            number=2,
            record=AgentRoundRecord(
                number=2,
                started=PINNED + timedelta(minutes=6),
                pid=2,
                ending=_compose_agent_round_ending(
                    at=PINNED + timedelta(minutes=10), status=0
                ),
            ),
        )
        write_json(
            document=ConversationRoundInput(
                issue=8,
                initial_issue=InitialConversationIssue(
                    title="Issue 8",
                    body="Explain it.",
                ),
                comments=[
                    {
                        "id": 2,
                        "body": "What evidence supports that?",
                        "author": "alice",
                        "written_at": "2026-09-23T02:00:00Z",
                    }
                ],
                revision="def456",
            ),
            path=(directory / "rounds" / "2" / "round-input.json"),
        )
        write_feed(
            directory=directory,
            number=2,
            lines=[FeedLine(at=PINNED, text="I found the follow-up answer.")],
        )
        write_ending(
            directory=directory,
            reason=AgentWorkEndReason.COMPLETED,
            at=PINNED + timedelta(minutes=11),
        )

    show_feed_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        wait=wait,
    )

    shown = written.getvalue()
    assert shown.count("round 1: 1 comment") == 1
    assert shown.count("I found the answer.") == 1
    assert shown.count("round 2: 1 comment") == 1
    assert shown.count("code revision abc123 -> def456") == 1
    assert shown.count("I found the follow-up answer.") == 1


def test_conversation_feed_can_select_one_round(tmp_path):
    state = conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_feed_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        round_number=1,
    )

    assert "I found the answer." in written.getvalue()


def test_a_missing_conversation_detail_is_reportable(tmp_path):
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="No conversation here for GH8"):
        show_agent_work_view(
            state=StateDirectory(root=tmp_path),
            reference=8,
            kind=AgentWorkKind.CONVERSATION,
            console=console,
        )


def test_a_missing_conversation_round_says_how_many_exist(tmp_path):
    state = conversation_state(root=tmp_path)
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="has run 1 round, so it has no round 2"):
        show_feed_view(
            state=state,
            reference=8,
            kind=AgentWorkKind.CONVERSATION,
            console=console,
            round_number=2,
        )


def unsaved_conversation_state(*, root) -> StateDirectory:
    """Return state whose latest tick found a comment to answer at GH9."""
    state = StateDirectory(root=root)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=9,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=1),
                )
            ],
        ),
    )
    return state


def test_status_lists_a_conversation_request_before_its_conversation_is_saved(
    tmp_path,
):
    state = unsaved_conversation_state(root=tmp_path)
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        clock=lambda: PINNED,
    )

    shown = written.getvalue()
    assert "GH9" in shown
    assert "dream:conversation" in shown
    assert "1 comment to answer" in shown


def test_conversation_detail_before_the_conversation_starts_says_there_is_none(
    tmp_path,
):
    state = unsaved_conversation_state(root=tmp_path)
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="No conversation here for GH9"):
        show_agent_work_view(
            state=state,
            reference=9,
            kind=AgentWorkKind.CONVERSATION,
            console=console,
            clock=lambda: PINNED,
        )


def test_a_conversation_feed_before_the_conversation_starts_says_there_is_none(
    tmp_path,
):
    state = unsaved_conversation_state(root=tmp_path)
    console, _ = rendered_console()

    with pytest.raises(ReportableError, match="No conversation here for GH9"):
        show_feed_view(
            state=state,
            reference=9,
            kind=AgentWorkKind.CONVERSATION,
            console=console,
        )


def test_conversations_are_listed_in_attention_order_before_requests(tmp_path):
    state = conversation_state(root=tmp_path)
    write_running_conversation(state=state, issue=11, started=PINNED)
    hold_daemon_lock_for_test(path=state.lock)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                conversation_row(
                    ended_round=1, finding=IssueCommentsFinding(new_comments=0)
                ),
                conversation_row(
                    issue=11, finding=IssueCommentsFinding(new_comments=0)
                ),
                request_row(
                    issue=9,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=0),
                ),
                request_row(
                    issue=10,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=IssueCommentsFinding(new_comments=1),
                ),
                request_row(
                    issue=12,
                    kind=AgentWorkKind.CONVERSATION,
                    finding=ReadFailureFinding(reason="gh: offline"),
                ),
            ],
        ),
    )
    console, written = rendered_console()

    show_status_view(
        state=state,
        console=console,
        clock=lambda: PINNED,
    )

    shown = written.getvalue()
    assert (
        shown.index("GH11")
        < shown.index("GH8")
        < shown.index("GH9")
        < shown.index("GH10")
        < shown.index("GH12")
    )
    assert "working" in shown
    assert "waiting for a comment" in shown
    assert "cannot tell: gh: offline" in shown


def watched_console() -> tuple[Console, StringIO]:
    """Return a plain console that says it is a terminal, so a view follows."""
    written = StringIO()
    return (
        Console(
            file=written,
            width=100,
            height=40,
            force_terminal=True,
            color_system=None,
            legacy_windows=False,
            _environ={"TERM": "xterm"},
        ),
        written,
    )


def refusing(seconds, /):
    """A wait that a view with nothing more to show must never reach."""
    raise AssertionError("the view waited for something that was not coming")


@pytest.mark.parametrize("status", [0, 2], ids=["answered", "errored"])
def test_an_ended_conversation_view_never_waits(tmp_path, status):
    state = conversation_state(root=tmp_path, status=status)
    write_ending(
        directory=find_conversation_directory(state=state, issue=8),
        reason=AgentWorkEndReason.COMPLETED,
        at=PINNED + timedelta(minutes=5),
    )
    console, written = watched_console()

    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
        wait=refusing,
    )

    assert "conversation GH8-" in written.getvalue()


def test_a_conversation_view_of_an_idle_conversation_keeps_watching(tmp_path):
    state = conversation_state(root=tmp_path, is_paused=False)
    assert_conversation_views_keep_watching(state=state)


def test_a_conversation_view_in_fault_keeps_watching(tmp_path):
    state = conversation_state(root=tmp_path, status=2, is_paused=False)
    write_round(
        directory=find_conversation_directory(state=state, issue=8),
        number=2,
        record=AgentRoundRecord(
            number=2,
            started=PINNED + timedelta(minutes=5),
            pid=2,
            ending=_compose_agent_round_ending(
                at=PINNED + timedelta(minutes=8), status=2
            ),
        ),
    )

    assert_conversation_views_keep_watching(state=state)


def test_a_conversation_view_with_a_routing_conflict_keeps_watching(tmp_path):
    state = conversation_state(root=tmp_path, is_paused=False)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                conversation_row(
                    finding=ConflictingLabelsFinding(labels=["discuss", "scout"])
                )
            ],
        ),
    )

    assert_conversation_views_keep_watching(state=state)


def assert_conversation_views_keep_watching(*, state: StateDirectory) -> None:
    """Assert that the conversation detail and feed views both keep watching."""
    waits = []

    def interrupting(seconds, /):
        waits.append(seconds)
        raise KeyboardInterrupt

    console, _ = watched_console()
    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
        wait=interrupting,
    )
    console, _ = watched_console()
    show_feed_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        wait=interrupting,
    )

    assert len(waits) == 2


def end_conversation(*, state: StateDirectory) -> None:
    """Record that the conversation at issue 8 ended."""
    write_ending(
        directory=find_conversation_directory(state=state, issue=8),
        reason=AgentWorkEndReason.COMPLETED,
        at=PINNED + timedelta(minutes=10),
    )


def test_status_counts_an_ended_conversation(tmp_path):
    state = conversation_state(root=tmp_path, is_paused=False)
    end_conversation(state=state)
    console, written = rendered_console()

    show_status_view(state=state, console=console, clock=lambda: PINNED)

    shown = written.getvalue()
    assert "1 ended conversation" in shown
    assert "answered" not in shown


def test_a_view_of_an_ended_conversation_never_waits(tmp_path):
    state = conversation_state(root=tmp_path)
    end_conversation(state=state)
    console, written = watched_console()

    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
        wait=refusing,
    )

    assert "ended  completed" in written.getvalue()


def write_newer_conversation(*, state: StateDirectory) -> str:
    """Write a conversation at issue 8 under another label, and return its name.

    It is newer than the one that the conversation state holds, and its round
    has said something that a view of the older one must never show.
    """
    at = PINNED + timedelta(hours=1)
    directory = write_conversation(
        state=state, issue=8, at=at, dispatch_label="dream:scout"
    )
    write_round(
        directory=directory,
        number=1,
        record=AgentRoundRecord(number=1, started=at, pid=1),
    )
    write_feed(
        directory=directory,
        number=1,
        lines=[FeedLine(at=at, text="The newer answer.")],
    )
    return directory.name


def test_a_view_stays_on_its_conversation_when_a_newer_one_arrives(tmp_path):
    state = conversation_state(root=tmp_path, is_paused=False)
    identifier = find_conversation_directory(state=state, issue=8).name
    newer = write_newer_conversation(state=state)
    shutil.move(state.work / newer, tmp_path / newer)
    waits = []

    def arriving(seconds, /):
        """Let the newer conversation arrive at the first wait, then interrupt."""
        waits.append(seconds)
        if len(waits) % 2 == 0:
            raise KeyboardInterrupt
        if not (state.work / newer).exists():
            shutil.move(tmp_path / newer, state.work / newer)

    detail_console, detail = watched_console()
    show_agent_work_view(
        state=state,
        reference=identifier,
        kind=AgentWorkKind.CONVERSATION,
        console=detail_console,
        clock=lambda: PINNED,
        wait=arriving,
    )
    feed_console, feed = watched_console()
    show_feed_view(
        state=state,
        reference=identifier,
        kind=AgentWorkKind.CONVERSATION,
        console=feed_console,
        wait=arriving,
    )

    assert len(waits) == 4
    assert f"conversation {identifier}" in detail.getvalue()
    assert f"conversation {newer}" not in detail.getvalue()
    assert "I found the answer." in feed.getvalue()
    assert "The newer answer." not in feed.getvalue()


def test_a_conversation_view_lists_the_other_conversations_at_its_issue(tmp_path):
    state = conversation_state(root=tmp_path)
    paused = find_conversation_directory(state=state, issue=8).name
    newer = write_newer_conversation(state=state)
    console, written = rendered_console()

    show_agent_work_view(
        state=state,
        reference=8,
        kind=AgentWorkKind.CONVERSATION,
        console=console,
        clock=lambda: PINNED,
    )

    shown = " ".join(written.getvalue().split())
    assert f"conversation {newer}" in shown
    assert (
        f"other conversations {paused} dream:conversation idle paused, label removed"
        in shown
    )
