"""Serve representative Dreamcatcher state for browser tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Thread

from clocks import DISPLAY_TIME_ZONE, PINNED
from records import write_feed
from status_fabrications import (
    ASSIGNMENT_TIMESTAMP,
    LOOKED_AT,
    fabricate_conversation,
    fabricate_everything,
)
from werkzeug.serving import make_server

from dreamcatcher.agent_assignments import read_agent_assignment
from dreamcatcher.feed import FeedLine
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import WEB_HOST, create_app

BROWSER_ASSIGNMENT_IDENTIFIER = f"GH13-{ASSIGNMENT_TIMESTAMP}"
FEED_LINE_COUNT_PER_ROUND = 40


@contextmanager
def serve_fabricated_web(*, root: Path) -> Iterator[str]:
    """Serve representative state on an available port until the caller exits."""
    state = StateDirectory(root=root)
    fabricate_conversation(state=state)
    fabricate_everything(state=state)
    assignment = read_agent_assignment(
        state=state,
        identifier=BROWSER_ASSIGNMENT_IDENTIFIER,
    )
    assert assignment is not None
    for round_number in (1, 2):
        write_feed(
            directory=assignment.directory,
            number=round_number,
            lines=[
                FeedLine(
                    at=PINNED + timedelta(minutes=round_number, seconds=line_number),
                    text=f"[Agent] round {round_number} line {line_number:02d}",
                )
                for line_number in range(1, FEED_LINE_COUNT_PER_ROUND + 1)
            ],
        )
    application = create_app(
        state=state,
        clock=lambda: LOOKED_AT,
        zone=DISPLAY_TIME_ZONE,
    )
    server = make_server(WEB_HOST, 0, application, threaded=True)
    thread = Thread(target=server.serve_forever, name="fabricated-web-server")
    thread.start()
    try:
        yield f"http://{WEB_HOST}:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
