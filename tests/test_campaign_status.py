"""Read local status for campaigns."""

import os
from datetime import timedelta

import pytest
from clocks import PINNED
from records import write_daemon_run, write_tick
from rows import request_row

from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.scheduler.models import CampaignFinding, SchedulerRecord
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import RequestReason, read_status_report
from dreamcatcher.status.requests import RequestStatusValue

LOOKED_AT = PINNED + timedelta(hours=2)


@pytest.fixture
def state(tmp_path):
    """Return local state written by a running daemon."""
    state = StateDirectory(root=tmp_path)
    write_daemon_run(state=state, pid=os.getpid())
    return state


def test_a_labelled_parent_with_no_campaign_yet_is_available(state):
    write_tick(
        state=state,
        tick=SchedulerRecord(
            at=PINNED,
            rows=[
                request_row(
                    issue=20, kind=AgentWorkKind.CAMPAIGN, finding=CampaignFinding()
                )
            ],
        ),
    )

    [request] = read_status_report(
        state=state, clock=lambda: LOOKED_AT
    ).list_request_statuses(kind=AgentWorkKind.CAMPAIGN)

    assert request.value is RequestStatusValue.AVAILABLE
    assert request.reasons == (RequestReason(words="available"),)
