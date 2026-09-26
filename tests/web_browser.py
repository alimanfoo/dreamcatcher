"""Serve representative Dreamcatcher state for browser tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Thread

from clocks import DISPLAY_TIME_ZONE, PINNED
from flask import Flask
from records import write_feed
from status_fabrications import (
    ASSIGNMENT_TIMESTAMP,
    LOOKED_AT,
    fabricate_everything,
)
from werkzeug.serving import make_server

from dreamcatcher.agent_assignments import read_agent_assignment
from dreamcatcher.feed import FeedLine
from dreamcatcher.state import StateDirectory
from dreamcatcher.web import WEB_HOST, create_app

BROWSER_ASSIGNMENT_IDENTIFIER = f"GH13-{ASSIGNMENT_TIMESTAMP}"
FEED_LINE_COUNT_PER_ROUND = 40


def create_fabricated_web_app(*, root: Path) -> Flask:
    """Create the web app with a long two-round assignment feed."""
    state = StateDirectory(root=root)
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
    return create_app(
        state=state,
        clock=lambda: LOOKED_AT,
        zone=DISPLAY_TIME_ZONE,
    )


@contextmanager
def serve_web_app(*, application: Flask) -> Iterator[str]:
    """Serve an application on an available loopback port until the caller exits."""
    server = make_server(WEB_HOST, 0, application, threaded=True)
    thread = Thread(target=server.serve_forever, name="fabricated-web-server")
    thread.start()
    try:
        yield f"http://{WEB_HOST}:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
