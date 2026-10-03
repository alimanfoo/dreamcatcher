"""Serve and render Dreamcatcher's local web interface."""

import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, tzinfo
from functools import partial
from webbrowser import open as open_browser

from flask import Flask, Response, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from dreamcatcher.agent_rounds import request_agent_round_stop
from dreamcatcher.clock import read_current_time
from dreamcatcher.errors import ReportableError
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    AssignmentStatus,
    ConversationStatus,
    read_assignment_status,
    read_conversation_status,
    read_status_report,
)
from dreamcatcher.web.feed import (
    InvalidFeedCursorError,
    decode_feed_cursor,
    read_agent_tail,
)
from dreamcatcher.web.models import WebAgentTailContext, WebFeedOwner
from dreamcatcher.web.server import (
    WEB_HOST,
    WebServerRunner,
    create_web_server,
    run_web_server,
)
from dreamcatcher.web.views import (
    compose_agent_rounds,
    compose_assignment_view,
    compose_conversation_view,
    compose_home_view,
)

_HTMX_STOP_POLLING_STATUS = 286
_DEFAULT_WEB_THEME = "matrix"
_WEB_THEME_MARKS = {_DEFAULT_WEB_THEME: "phosphor", "nature": "ink"}
_WEB_THEMES = tuple(_WEB_THEME_MARKS)
_CROSS_ORIGIN_STOP_RESPONSE = (
    "Stop requests must come from this Dreamcatcher page.",
    403,
)


def _create_app(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime] = read_current_time,
    zone: tzinfo | None = None,
) -> Flask:
    """Create the web application for one local state directory.

    Pages read persisted status and feeds. A same-origin stop request can write
    into the running round's directory. Page times use the machine's local zone
    when zone is None.
    """
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config["TRUSTED_HOSTS"] = [WEB_HOST, "localhost"]
    _configure_web_theme(app=app)
    app.add_url_rule(
        "/",
        endpoint="show_home",
        view_func=partial(_show_home, state=state, clock=clock, zone=zone),
    )
    _register_assignment_routes(app=app, state=state, clock=clock, zone=zone)
    _register_conversation_routes(app=app, state=state, clock=clock, zone=zone)
    app.register_error_handler(ReportableError, _show_reportable_error)
    return app


def _register_assignment_routes(
    *,
    app: Flask,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> None:
    app.add_url_rule(
        "/assignments/<identifier>",
        endpoint="show_assignment",
        view_func=partial(_show_assignment, state=state, clock=clock, zone=zone),
    )
    app.add_url_rule(
        "/assignments/<identifier>/tail",
        endpoint="show_assignment_tail",
        view_func=partial(_show_assignment_tail, state=state, clock=clock, zone=zone),
    )
    app.add_url_rule(
        "/assignments/<identifier>/stop/<int:number>",
        endpoint="request_assignment_stop",
        view_func=partial(_request_assignment_stop, state=state, clock=clock),
        methods=["POST"],
    )


def _register_conversation_routes(
    *,
    app: Flask,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> None:
    app.add_url_rule(
        "/conversations/<int:issue>",
        endpoint="show_conversation",
        view_func=partial(_show_conversation, state=state, clock=clock, zone=zone),
    )
    app.add_url_rule(
        "/conversations/<int:issue>/tail",
        endpoint="show_conversation_tail",
        view_func=partial(_show_conversation_tail, state=state, clock=clock, zone=zone),
    )
    app.add_url_rule(
        "/conversations/<int:issue>/stop/<int:number>",
        endpoint="request_conversation_stop",
        view_func=partial(_request_conversation_stop, state=state, clock=clock),
        methods=["POST"],
    )


def _show_home(
    *, state: StateDirectory, clock: Callable[[], datetime], zone: tzinfo | None
) -> str:
    """Render the local status overview."""
    report = read_status_report(state=state, clock=clock)
    return render_template(
        "home.html", view=compose_home_view(report=report, zone=zone)
    )


def _show_assignment(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    identifier: str,
) -> str | tuple[str, int]:
    """Render one assignment page, or a missing response."""
    status = read_assignment_status(
        state=state,
        identifier=identifier,
        clock=clock,
    )
    if status is None:
        return _missing_assignment_response(identifier=identifier)
    return render_template(
        "assignment.html",
        view=compose_assignment_view(
            state=state,
            status=status,
            zone=zone,
            stop_url=_compose_assignment_stop_url(status=status),
        ),
    )


def _compose_assignment_stop_url(*, status: AssignmentStatus) -> str | None:
    paths = status.stoppable_round_paths
    if paths is None:
        return None
    return url_for(
        "request_assignment_stop",
        identifier=status.assignment.identifier,
        number=paths.number,
    )


def _show_assignment_tail(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    identifier: str,
) -> str | tuple[str, int]:
    """Render assignment feed output written after the requested cursor."""
    status = read_assignment_status(
        state=state,
        identifier=identifier,
        clock=clock,
    )
    if status is None:
        return _missing_assignment_response(identifier=identifier)
    return _show_agent_tail(
        owner=status.assignment,
        context=WebAgentTailContext(
            status=str(status.value),
            status_label=str(status.value),
            detail=status.detail,
            rounds=compose_agent_rounds(
                round_statuses=status.round_statuses, zone=zone
            ),
            stop_url=_compose_assignment_stop_url(status=status),
        ),
        is_terminal=status.is_over,
        status_id="assignment-status",
        zone=zone,
    )


def _show_conversation(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    issue: int,
) -> str | tuple[str, int]:
    """Render one issue-conversation page, or a missing response."""
    status = read_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        return _missing_conversation_response(issue=issue)
    return render_template(
        "conversation.html",
        view=compose_conversation_view(
            state=state,
            status=status,
            zone=zone,
            stop_url=_compose_conversation_stop_url(status=status),
        ),
    )


def _compose_conversation_stop_url(*, status: ConversationStatus) -> str | None:
    paths = status.stoppable_round_paths
    if paths is None:
        return None
    return url_for(
        "request_conversation_stop",
        issue=status.issue,
        number=paths.number,
    )


def _show_conversation_tail(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    issue: int,
) -> str | tuple[str, int]:
    """Render conversation feed output written after the requested cursor."""
    status = read_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        return _missing_conversation_response(issue=issue)
    conversation = status.conversation
    return _show_agent_tail(
        owner=conversation,
        context=WebAgentTailContext(
            status=str(status.value),
            status_label=str(status.value),
            detail=status.detail,
            rounds=compose_agent_rounds(
                round_statuses=status.round_statuses, zone=zone
            ),
            stop_url=_compose_conversation_stop_url(status=status),
        ),
        is_terminal=status.is_over,
        status_id="conversation-status",
        zone=zone,
    )


def _request_assignment_stop(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    identifier: str,
    number: int,
) -> ResponseReturnValue:
    """Request a stop for one assignment's live round."""
    if not _is_same_origin_request():
        return _CROSS_ORIGIN_STOP_RESPONSE
    status = read_assignment_status(state=state, identifier=identifier, clock=clock)
    if status is None:
        return _missing_assignment_response(identifier=identifier)
    paths = status.stoppable_round_paths
    if paths is not None and paths.number == number:
        request_agent_round_stop(paths=paths)
    return redirect(url_for("show_assignment", identifier=identifier), code=303)


def _request_conversation_stop(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    issue: int,
    number: int,
) -> ResponseReturnValue:
    """Request a stop for one issue conversation's live round."""
    if not _is_same_origin_request():
        return _CROSS_ORIGIN_STOP_RESPONSE
    status = read_conversation_status(state=state, issue=issue, clock=clock)
    if status is None:
        return _missing_conversation_response(issue=issue)
    paths = status.stoppable_round_paths
    if paths is not None and paths.number == number:
        request_agent_round_stop(paths=paths)
    return redirect(url_for("show_conversation", issue=issue), code=303)


def _is_same_origin_request() -> bool:
    """Return whether the POST came from the web page that received it."""
    return request.headers.get("Origin") == request.host_url.removesuffix("/")


def _show_agent_tail(
    *,
    owner: WebFeedOwner | None,
    context: WebAgentTailContext,
    is_terminal: bool,
    status_id: str,
    zone: tzinfo | None,
) -> str | tuple[str, int]:
    """Render incremental feed output for an assignment or conversation."""
    try:
        cursor = decode_feed_cursor(value=request.args.get("cursor", ""))
        tail = read_agent_tail(
            owner=owner,
            context=context,
            cursor=cursor,
            zone=zone,
        )
    except InvalidFeedCursorError:
        return _invalid_feed_cursor_response()
    response_status = (
        _HTMX_STOP_POLLING_STATUS if not tail.feed_rounds and is_terminal else 200
    )
    return (
        render_template("tail.html", tail=tail, status_id=status_id),
        response_status,
    )


def _missing_assignment_response(*, identifier: str) -> tuple[str, int]:
    """Render the response for an unknown assignment identifier."""
    return (
        render_template(
            "error.html",
            message=f"No agent assignment here has identifier {identifier}.",
        ),
        404,
    )


def _missing_conversation_response(*, issue: int) -> tuple[str, int]:
    """Render the response for an issue with no conversation.

    An issue has a conversation once it has a saved conversation or the latest
    tick observed it as eligible.
    """
    return (
        render_template(
            "error.html",
            message=f"No issue conversation here is for GH{issue}.",
        ),
        404,
    )


def _invalid_feed_cursor_response() -> tuple[str, int]:
    """Render the response for a malformed or stale feed cursor."""
    return render_template("error.html", message="The feed cursor is invalid."), 400


def _show_reportable_error(error: ReportableError, /) -> tuple[str, int]:
    """Render a named read failure for Flask, which passes the error by position."""
    return render_template("error.html", message=str(error)), 500


def _configure_web_theme(*, app: Flask) -> None:
    @app.context_processor
    def add_web_theme() -> dict[str, object]:
        requested_theme = request.args.get("theme")
        remembered_theme = request.cookies.get("theme")
        if requested_theme in _WEB_THEMES:
            theme = requested_theme
        elif remembered_theme in _WEB_THEMES:
            theme = remembered_theme
        else:
            theme = _DEFAULT_WEB_THEME
        return {
            "mark": _WEB_THEME_MARKS[theme],
            "theme": theme,
            "themes": _WEB_THEMES,
        }

    @app.after_request
    def remember_web_theme(response: Response, /) -> Response:
        """Remember a valid theme selected through a browser request."""
        requested_theme = request.args.get("theme")
        if requested_theme in _WEB_THEMES:
            response.set_cookie("theme", requested_theme, samesite="Lax")
        return response


def serve_web(
    *,
    state: StateDirectory,
    port: int | None = None,
    browser_opener: Callable[[str], object] = open_browser,
    server_runner: WebServerRunner = run_web_server,
    zone: tzinfo | None = None,
) -> None:
    """Serve one local status page, open it, and run until interrupted.

    Page times use the machine's local zone when zone is None.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    application = _create_app(state=state, zone=zone)
    server = create_web_server(state=state, port=port, application=application)
    address = f"http://{WEB_HOST}:{server.server_port}/"
    try:
        with suppress(KeyboardInterrupt):
            browser_opener(address)
            print(address, flush=True)
            server_runner(server=server)
    finally:
        server.server_close()
