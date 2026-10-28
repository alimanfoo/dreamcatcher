"""Serve and render dreamcatcher's local web interface."""

import logging
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from datetime import datetime, tzinfo
from functools import partial
from webbrowser import open as open_browser

from flask import Flask, Response, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from werkzeug.serving import BaseWSGIServer

from dreamcatcher.agent_assignments import cancel_assignment
from dreamcatcher.agent_rounds import request_agent_round_stop
from dreamcatcher.agent_work import (
    AgentWork,
    find_agent_work,
    request_agent_work_retry,
)
from dreamcatcher.clock import read_current_time
from dreamcatcher.errors import ReportableError
from dreamcatcher.harness_adapters import AgentWorkKind
from dreamcatcher.state import StateDirectory
from dreamcatcher.status import (
    DOCUMENTATION_URL,
    AgentWorkStatus,
    read_agent_work_status,
    read_dreamcatcher_daemon_status,
    read_repository,
    read_status_report,
)
from dreamcatcher.web.feed import (
    InvalidFeedPositionError,
    decode_feed_position,
    read_agent_tail,
)
from dreamcatcher.web.models import (
    WebAgentLiveState,
    WebAgentWorkControl,
)
from dreamcatcher.web.server import (
    WEB_HOST,
    WebServerRunner,
    create_web_server,
    run_web_server,
    run_web_server_in_background,
)
from dreamcatcher.web.views import (
    compose_agent_live_state,
    compose_agent_work_view,
    compose_github_repository_url,
    compose_home_view,
)

_HTMX_STOP_POLLING_STATUS = 286
_DEFAULT_WEB_THEME = "nature"
_WEB_THEME_MARKS = {"matrix": "phosphor", "nature": "ink"}
_WEB_THEMES = tuple(_WEB_THEME_MARKS)
_CROSS_ORIGIN_POST_RESPONSE = (
    "Requests that change agent work must come from this dreamcatcher page.",
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
    into the running round's directory, and a same-origin retry request or
    cancel into the directory of the agent work that it names. Page times use
    the machine's local zone when zone is None.
    """
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.config["TRUSTED_HOSTS"] = [WEB_HOST, "localhost"]
    app.context_processor(_add_documentation_url)
    _configure_web_theme(app=app)
    app.add_url_rule(
        "/",
        endpoint="show_home",
        view_func=partial(_show_home, state=state, clock=clock),
    )
    _register_work_routes(app=app, state=state, clock=clock, zone=zone)
    app.register_error_handler(ReportableError, _show_reportable_error)
    return app


def _register_work_routes(
    *,
    app: Flask,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
) -> None:
    app.add_url_rule(
        "/work/<identifier>",
        endpoint="show_work",
        view_func=partial(_show_work, state=state, clock=clock, zone=zone),
    )
    app.add_url_rule(
        "/work/<identifier>/tail",
        endpoint="show_work_tail",
        view_func=partial(_show_work_tail, state=state, clock=clock, zone=zone),
    )
    app.add_url_rule(
        "/work/<identifier>/stop/<int:number>",
        endpoint="request_work_stop",
        view_func=partial(_request_work_stop, state=state, clock=clock),
        methods=["POST"],
    )
    app.add_url_rule(
        "/work/<identifier>/retry/<int:number>",
        endpoint="request_work_retry",
        view_func=partial(_request_work_retry, state=state, clock=clock),
        methods=["POST"],
    )
    app.add_url_rule(
        "/work/<identifier>/cancel",
        endpoint="cancel_assignment",
        view_func=partial(_cancel_assignment, state=state, clock=clock),
        methods=["POST"],
    )


def _show_home(*, state: StateDirectory, clock: Callable[[], datetime]) -> str:
    """Render the local status overview."""
    report = read_status_report(state=state, clock=clock)
    return render_template("home.html", view=compose_home_view(report=report))


def _show_work(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    identifier: str,
) -> str | tuple[str, int]:
    """Render the page of one piece of agent work, or a missing response."""
    work = find_agent_work(state=state, identifier=identifier)
    if work is None:
        return _missing_work_response(identifier=identifier)
    daemon = read_dreamcatcher_daemon_status(state=state)
    status = read_agent_work_status(state=state, work=work, daemon=daemon, clock=clock)
    live = _compose_work_live_state(state=state, work=work, status=status, zone=zone)
    return render_template(
        "agent-work.html",
        view=compose_agent_work_view(
            state=state, status=status, daemon=daemon, live=live, zone=zone
        ),
    )


def _compose_work_live_state(
    *,
    state: StateDirectory,
    work: AgentWork,
    status: AgentWorkStatus,
    zone: tzinfo | None,
) -> WebAgentLiveState:
    identifier = work.identifier
    heading_controls = []
    foot_controls = []
    paths = status.stoppable_round_paths
    if paths is not None:
        foot_controls.append(
            WebAgentWorkControl(
                action="stop",
                url=url_for(
                    "request_work_stop", identifier=identifier, number=paths.number
                ),
            )
        )
    number = status.faulted_round_number
    if number is not None:
        heading_controls.append(
            WebAgentWorkControl(
                action="retry",
                url=url_for("request_work_retry", identifier=identifier, number=number),
            )
        )
    if _can_cancel(work=work):
        foot_controls.append(
            WebAgentWorkControl(
                action="cancel",
                url=url_for("cancel_assignment", identifier=identifier),
            )
        )
    return compose_agent_live_state(
        state=state,
        status=status,
        zone=zone,
        heading_controls=tuple(heading_controls),
        foot_controls=tuple(foot_controls),
    )


def _show_work_tail(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    zone: tzinfo | None,
    identifier: str,
) -> str | tuple[str, int]:
    """Render the work's feed output written after the requested feed position."""
    work = find_agent_work(state=state, identifier=identifier)
    if work is None:
        return _missing_work_response(identifier=identifier)
    status = read_agent_work_status(
        state=state,
        work=work,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=clock,
    )
    return _render_work_tail(
        work=work,
        github_repository_url=compose_github_repository_url(
            repository=read_repository(state=state)
        ),
        live=_compose_work_live_state(state=state, work=work, status=status, zone=zone),
        should_stop_polling=not status.is_active,
        zone=zone,
    )


def _request_work_stop(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    identifier: str,
    number: int,
) -> ResponseReturnValue:
    """Request a stop for one piece of agent work's live round.

    A submission whose round is no longer the live one changes nothing.
    """
    if not _is_same_origin_request():
        return _CROSS_ORIGIN_POST_RESPONSE
    work = find_agent_work(state=state, identifier=identifier)
    if work is None:
        return _missing_work_response(identifier=identifier)
    status = read_agent_work_status(
        state=state,
        work=work,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=clock,
    )
    paths = status.stoppable_round_paths
    if paths is not None and paths.number == number:
        request_agent_round_stop(paths=paths)
    return redirect(url_for("show_work", identifier=identifier), code=303)


def _request_work_retry(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    identifier: str,
    number: int,
) -> ResponseReturnValue:
    """Request a retry of one faulted piece of agent work.

    A submission whose round is no longer the faulted one changes nothing.
    """
    if not _is_same_origin_request():
        return _CROSS_ORIGIN_POST_RESPONSE
    work = find_agent_work(state=state, identifier=identifier)
    if work is None:
        return _missing_work_response(identifier=identifier)
    status = read_agent_work_status(
        state=state,
        work=work,
        daemon=read_dreamcatcher_daemon_status(state=state),
        clock=clock,
    )
    if status.faulted_round_number == number:
        request_agent_work_retry(work=work, at=clock())
    return redirect(url_for("show_work", identifier=identifier), code=303)


def _cancel_assignment(
    *,
    state: StateDirectory,
    clock: Callable[[], datetime],
    identifier: str,
) -> ResponseReturnValue:
    """Cancel one assignment so the user can finish its pull request by hand.

    A submission for work that cannot be cancelled, such as an assignment that
    has already ended, changes nothing.
    """
    if not _is_same_origin_request():
        return _CROSS_ORIGIN_POST_RESPONSE
    work = find_agent_work(state=state, identifier=identifier)
    if work is None:
        return _missing_work_response(identifier=identifier)
    if _can_cancel(work=work):
        cancel_assignment(assignment=work, at=clock())
    return redirect(url_for("show_work", identifier=identifier), code=303)


def _can_cancel(*, work: AgentWork) -> bool:
    """Return whether the work is an assignment that is still open."""
    return work.record.kind is AgentWorkKind.ASSIGNMENT and work.is_open


def _is_same_origin_request() -> bool:
    """Return whether the POST came from the web page that received it."""
    return request.headers.get("Origin") == request.host_url.removesuffix("/")


def _render_work_tail(
    *,
    work: AgentWork,
    github_repository_url: str | None,
    live: WebAgentLiveState,
    should_stop_polling: bool,
    zone: tzinfo | None,
) -> str | tuple[str, int]:
    """Render incremental feed output for a piece of agent work."""
    try:
        feed_position = decode_feed_position(value=request.args.get("position", ""))
        tail = read_agent_tail(
            work=work,
            github_repository_url=github_repository_url,
            live=live,
            feed_position=feed_position,
            zone=zone,
        )
    except InvalidFeedPositionError:
        return _invalid_feed_position_response()
    response_status = (
        _HTMX_STOP_POLLING_STATUS
        if not tail.feed_rounds and should_stop_polling
        else 200
    )
    return (
        render_template("tail.html", tail=tail),
        response_status,
    )


def _missing_work_response(*, identifier: str) -> tuple[str, int]:
    """Render the response for an unknown agent work identifier."""
    return (
        render_template(
            "error.html",
            message=f"No agent work here has identifier {identifier}.",
        ),
        404,
    )


def _invalid_feed_position_response() -> tuple[str, int]:
    """Render the response for a malformed or stale feed position."""
    return render_template("error.html", message="The feed position is invalid."), 400


def _show_reportable_error(error: ReportableError, /) -> tuple[str, int]:
    """Render a reportable failure for Flask, which passes the error by position."""
    return render_template("error.html", message=str(error)), 500


def _add_documentation_url() -> dict[str, object]:
    return {"documentation_url": DOCUMENTATION_URL}


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


def _create_web_application_server(
    *,
    state: StateDirectory,
    port: int | None,
    zone: tzinfo | None,
) -> BaseWSGIServer:
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    application = _create_app(state=state, zone=zone)
    return create_web_server(state=state, port=port, application=application)


def _open_web_page(
    *, server: BaseWSGIServer, browser_opener: Callable[[str], object]
) -> None:
    address = f"http://{WEB_HOST}:{server.server_port}/"
    try:
        browser_opener(address)
    except OSError as error:
        raise ReportableError("Could not open the web interface.") from error
    try:
        print(address, flush=True)
    except (OSError, UnicodeError) as error:
        raise ReportableError("Could not write the web address.") from error


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
    server = _create_web_application_server(state=state, port=port, zone=zone)
    try:
        with suppress(KeyboardInterrupt):
            _open_web_page(server=server, browser_opener=browser_opener)
            server_runner(server=server)
    finally:
        server.server_close()


@contextmanager
def serve_web_in_background(
    *,
    state: StateDirectory,
    browser_opener: Callable[[str], object] = open_browser,
    zone: tzinfo | None = None,
) -> Generator[None, None, None]:
    """Serve and open the local status page until the surrounding context exits."""
    server = _create_web_application_server(state=state, port=None, zone=zone)
    with run_web_server_in_background(server=server):
        _open_web_page(server=server, browser_opener=browser_opener)
        yield
