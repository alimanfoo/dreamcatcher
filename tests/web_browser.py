"""Serve representative dreamcatcher state for browser tests."""

from collections.abc import Generator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from clocks import DISPLAY_TIME_ZONE
from status_fabrications import (
    ASSIGNMENT_TIMESTAMP,
    LOOKED_AT,
    compose_conversation_row,
    fabricate_campaigns,
    fabricate_conversation,
    fabricate_everything,
)
from werkzeug.serving import make_server

from dreamcatcher.agent_work import find_agent_work
from dreamcatcher.documents import append_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.scheduler.models import IssueCommentsFinding
from dreamcatcher.state import StateDirectory
from dreamcatcher.web.app import _create_app
from dreamcatcher.web.server import WEB_HOST, run_web_server_in_background

BROWSER_ASSIGNMENT_IDENTIFIER = f"GH13-{ASSIGNMENT_TIMESTAMP}-assignment"
FEED_LINE_COUNT_PER_ROUND = 40


@contextmanager
def serve_fabricated_web(*, root: Path) -> Generator[str, None, None]:
    """Serve representative state on an available port until the caller exits."""
    state = StateDirectory(root=root)
    fabricate_conversation(state=state)
    fabricate_everything(
        state=state,
        other_rows=[
            compose_conversation_row(finding=IssueCommentsFinding(new_comments=0)),
            *fabricate_campaigns(state=state),
        ],
    )
    assignment = find_agent_work(
        state=state,
        identifier=BROWSER_ASSIGNMENT_IDENTIFIER,
    )
    assert assignment is not None
    for round_record in assignment.rounds:
        append_text(
            text="".join(
                FeedLine(
                    at=round_record.started + timedelta(minutes=5, seconds=line_number),
                    text=(
                        f"[Agent] round {round_record.number} line {line_number:02d}"
                    ),
                ).render()
                for line_number in range(1, FEED_LINE_COUNT_PER_ROUND + 1)
            ),
            path=assignment.compose_round_paths(number=round_record.number).feed,
        )
    application = _create_app(
        state=state,
        clock=lambda: LOOKED_AT,
        zone=DISPLAY_TIME_ZONE,
    )
    server = make_server(WEB_HOST, 0, application)
    with run_web_server_in_background(server=server):
        yield f"http://{WEB_HOST}:{server.server_port}"
