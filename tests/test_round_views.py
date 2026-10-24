"""Show round outcomes consistently in the web and terminal round lists."""

from io import StringIO

import pytest
from clocks import DISPLAY_TIME_ZONE, PINNED
from records import read_newest_work
from status_fabrications import (
    LOOKED_AT,
    compose_ended_round,
    fabricate_a_dead_daemon,
    fabricate_everything,
    write_assignment_with_rounds,
)
from terminals import create_pinned_console, refuse_to_wait

from dreamcatcher.agent_rounds import AgentRoundRecord, StoppedAgentRoundEnding
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.tui import show_agent_work_view
from dreamcatcher.web.app import _create_app


def render_assignment_page(*, state: StateDirectory, identifier: str) -> str:
    """Render one assignment page against the pinned clock."""
    application = _create_app(
        state=state, clock=lambda: LOOKED_AT, zone=DISPLAY_TIME_ZONE
    )
    response = application.test_client().get(f"/work/{identifier}")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def render_assignment_terminal(*, state: StateDirectory, issue: int) -> str:
    """Render one assignment as plain terminal text."""
    written_to = StringIO()
    console = create_pinned_console(written_to=written_to)
    show_agent_work_view(
        state=state,
        work=read_newest_work(state=state, issue=issue, kind=AgentWorkKind.ASSIGNMENT),
        console=console,
        clock=lambda: LOOKED_AT,
        wait=refuse_to_wait,
        zone=DISPLAY_TIME_ZONE,
    )
    return written_to.getvalue()


def find_round_row(*, rendered: str, number: int) -> str:
    """Return one numbered row from a rendered terminal round list."""
    prefix = f"{number}  "
    return next(
        line for line in rendered.splitlines() if line.lstrip().startswith(prefix)
    )


@pytest.mark.parametrize(
    ("record", "outcome", "description"),
    [
        pytest.param(compose_ended_round(status=2), "errored", "errored (exit 2)"),
        pytest.param(
            AgentRoundRecord(number=1, started=PINNED, pid=1),
            "interrupted",
            "interrupted",
        ),
        pytest.param(
            AgentRoundRecord(
                number=1,
                started=PINNED,
                pid=1,
                ending=StoppedAgentRoundEnding(at=PINNED),
            ),
            "stopped",
            "stopped",
        ),
    ],
)
def test_a_non_successful_round_shows_its_outcome_in_both_lists(
    tmp_path, record, outcome, description
):
    state = StateDirectory(root=tmp_path)
    fabricate_a_dead_daemon(state=state)
    write_assignment_with_rounds(state=state, issue=61, records=[record])

    page = render_assignment_page(
        state=state, identifier="GH61-20260819-184158-assignment"
    )
    terminal = render_assignment_terminal(state=state, issue=61)

    assert f'class="round-outcome outcome-{outcome}">{description}</span>' in page
    assert description in find_round_row(rendered=terminal, number=1)


def test_a_successful_round_has_no_outcome_in_either_list(tmp_path):
    state = StateDirectory(root=tmp_path)
    fabricate_everything(state=state)

    page = render_assignment_page(
        state=state, identifier="GH13-20260819-184158-assignment"
    )
    terminal = render_assignment_terminal(state=state, issue=13)

    assert 'class="round-outcome outcome-successful"' not in page
    assert "successful" not in find_round_row(rendered=terminal, number=1)
