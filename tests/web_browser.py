"""Serve representative dreamcatcher state for browser tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Thread

from clocks import DISPLAY_TIME_ZONE
from observations import observed_conversation
from status_fabrications import (
    ASSIGNMENT_TIMESTAMP,
    LOOKED_AT,
    fabricate_conversation,
    fabricate_everything,
)
from werkzeug.serving import make_server

from dreamcatcher.agent_assignments import read_assignment
from dreamcatcher.documents import append_text
from dreamcatcher.feed import FeedLine
from dreamcatcher.state import StateDirectory
from dreamcatcher.web.app import _create_app
from dreamcatcher.web.server import WEB_HOST

BROWSER_ASSIGNMENT_IDENTIFIER = f"GH13-{ASSIGNMENT_TIMESTAMP}"
FEED_LINE_COUNT_PER_ROUND = 40


@contextmanager
def serve_fabricated_web(*, root: Path) -> Iterator[str]:
    """Serve representative state on an available port until the caller exits."""
    state = StateDirectory(root=root)
    fabricate_conversation(state=state)
    fabricate_everything(
        state=state,
        conversation_observations=[observed_conversation()],
    )
    assignment = read_assignment(
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
    thread = Thread(target=server.serve_forever, name="fabricated-web-server")
    try:
        thread.start()
        yield f"http://{WEB_HOST}:{server.server_port}"
    finally:
        if thread.is_alive():
            server.shutdown()
            thread.join()
        server.server_close()
