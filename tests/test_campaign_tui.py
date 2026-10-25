"""Render campaigns in terminal views."""

from io import StringIO

import pytest
from clocks import PINNED
from records import read_newest_work, write_tick
from status_fabrications import LOOKED_AT, fabricate_campaigns, write_running_daemon
from terminals import create_pinned_console

from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import show_agent_work_view, show_feed_view, show_status_view


@pytest.fixture
def state(tmp_path):
    """Return a running daemon's state holding an idle and an ended campaign."""
    state = StateDirectory(root=tmp_path)
    write_running_daemon(state=state)
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED, finished=PINNED, rows=fabricate_campaigns(state=state)
        ),
    )
    return state


def test_status_lists_campaigns_their_requests_and_how_many_ended(state):
    written = StringIO()
    console = create_pinned_console(written_to=written)

    show_status_view(state=state, console=console, clock=lambda: LOOKED_AT)

    shown = written.getvalue()
    campaigns = shown[shown.index("campaigns") :]
    assert "GH60-20260819-184158-campaign" in campaigns
    assert "round 1, successful, ran 4m" in campaigns
    assert "GH62" in campaigns
    assert "available" in campaigns
    assert "1 ended campaign" in campaigns


def test_campaign_detail_shows_its_parent_settings_and_rounds(state):
    written = StringIO()
    console = create_pinned_console(written_to=written)

    show_agent_work_view(
        state=state,
        work=read_newest_work(state=state, issue=60, kind=AgentWorkKind.CAMPAIGN),
        console=console,
        clock=lambda: LOOKED_AT,
    )

    shown = written.getvalue()
    assert "campaign GH60-20260819-184158-campaign" in shown
    assert "\ncampaign\n" in shown
    assert "dream:lead" in shown
    assert "abc123" not in shown
    assert "start" in shown
    assert "claude --resume lead-session" in shown


def test_a_closed_campaign_view_shows_closed_once_as_its_status(state):
    written = StringIO()
    console = create_pinned_console(written_to=written)

    show_agent_work_view(
        state=state,
        work=read_newest_work(state=state, issue=61, kind=AgentWorkKind.CAMPAIGN),
        console=console,
        clock=lambda: LOOKED_AT,
    )

    assert written.getvalue().splitlines()[1] == "closed"


def test_campaign_feed_shows_what_the_lead_said(state):
    written = StringIO()
    console = create_pinned_console(written_to=written)

    show_feed_view(
        state=state,
        work=read_newest_work(state=state, issue=60, kind=AgentWorkKind.CAMPAIGN),
        console=console,
    )

    assert "I acknowledged the plan on the parent." in written.getvalue()
