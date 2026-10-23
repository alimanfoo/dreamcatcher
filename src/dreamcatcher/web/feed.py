"""Read and compose web feed snapshots and tails."""

import re
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path

from dreamcatcher.agent_rounds import AgentRoundRecord
from dreamcatcher.agent_work import AgentWork
from dreamcatcher.documents import is_complete_line_position, read_lines_from
from dreamcatcher.feed import compose_agent_round_boundary, read_feed_line
from dreamcatcher.web.models import (
    WebAgentFeed,
    WebAgentLiveState,
    WebAgentRound,
    WebAgentTail,
    WebFeedCursor,
    WebFeedLine,
    WebFeedRound,
)
from dreamcatcher.words import describe_time

_FEED_CURSOR_PATTERN = re.compile(r"(?P<round>0|[1-9]\d*):(?P<position>\d+)")


@dataclass(frozen=True, kw_only=True)
class _WebRoundFeed:
    """Pair one saved round with the feed it wrote."""

    record: AgentRoundRecord
    feed: Path


class InvalidFeedCursorError(Exception):
    """Report a feed cursor that cannot identify a complete feed position."""


def _encode_feed_cursor(*, feed_cursor: WebFeedCursor) -> str:
    return f"{feed_cursor.round_number}:{feed_cursor.position}"


def decode_feed_cursor(*, value: str) -> WebFeedCursor:
    """Decode a feed cursor from its encoded text form.

    Raise InvalidFeedCursorError when the value names no valid position.
    """
    match = _FEED_CURSOR_PATTERN.fullmatch(value)
    if match is None:
        raise InvalidFeedCursorError
    try:
        feed_cursor = WebFeedCursor(
            round_number=int(match["round"]),
            position=int(match["position"]),
        )
    except ValueError:
        raise InvalidFeedCursorError from None
    if feed_cursor.round_number == 0 and feed_cursor.position != 0:
        raise InvalidFeedCursorError
    return feed_cursor


def read_agent_tail(
    *,
    work: AgentWork,
    live: WebAgentLiveState,
    feed_cursor: WebFeedCursor,
    zone: tzinfo | None,
) -> WebAgentTail:
    """Read feed output written after one feed cursor for any agent work."""
    round_feeds = _list_round_feeds(work=work)
    number, position, is_opening_round = _resolve_feed_cursor(
        feed_cursor=feed_cursor,
        round_feeds=round_feeds,
    )
    feed_rounds = []
    next_feed_cursor = feed_cursor
    while (round_feed := round_feeds.get(number)) is not None:
        feed_round, position, should_stop = _read_tail_round(
            round_feed=round_feed,
            number=number,
            position=position,
            is_opening_round=is_opening_round,
            rounds=live.rounds,
            zone=zone,
        )
        if feed_round is not None:
            feed_rounds.append(feed_round)
        next_feed_cursor = WebFeedCursor(round_number=number, position=position)
        if should_stop:
            break
        number += 1
        position = 0
        is_opening_round = True
    return WebAgentTail(
        feed_cursor=_encode_feed_cursor(feed_cursor=next_feed_cursor),
        feed_rounds=tuple(feed_rounds),
        live=live,
        has_empty_feed_placeholder=feed_cursor.round_number == 0,
    )


def _read_tail_round(
    *,
    round_feed: _WebRoundFeed,
    number: int,
    position: int,
    is_opening_round: bool,
    rounds: tuple[WebAgentRound, ...],
    zone: tzinfo | None,
) -> tuple[WebFeedRound | None, int, bool]:
    record = round_feed.record
    if not is_complete_line_position(path=round_feed.feed, position=position):
        raise InvalidFeedCursorError
    written_lines, next_position = read_lines_from(
        path=round_feed.feed,
        position=position,
    )
    lines = tuple(
        _compose_web_feed_line(written_line=written_line, zone=zone)
        for written_line in written_lines
    )
    if is_opening_round:
        lines = (
            _compose_web_round_boundary(
                record=record, round_=_find_web_round(rounds=rounds, number=number)
            ),
            *lines,
        )
    feed_round = WebFeedRound(number=number, lines=lines) if lines else None
    return feed_round, next_position, bool(written_lines) or record.ending is None


def _resolve_feed_cursor(
    *,
    feed_cursor: WebFeedCursor,
    round_feeds: dict[int, _WebRoundFeed],
) -> tuple[int, int, bool]:
    if feed_cursor.round_number == 0:
        return 1, 0, True
    if feed_cursor.round_number not in round_feeds:
        raise InvalidFeedCursorError
    return feed_cursor.round_number, feed_cursor.position, False


def _compose_web_round_boundary(
    *, record: AgentRoundRecord, round_: WebAgentRound
) -> WebFeedLine:
    boundary = compose_agent_round_boundary(
        number=record.number,
        trigger=round_.trigger.describe(),
        at=record.started,
    )
    return WebFeedLine(
        timestamp=round_.started,
        label=None,
        detail=boundary.text,
        is_boundary=True,
    )


def _list_round_feeds(*, work: AgentWork) -> dict[int, _WebRoundFeed]:
    """Return every saved round of the agent work with its feed, by number."""
    return {
        record.number: _WebRoundFeed(
            record=record, feed=work.compose_round_paths(number=record.number).feed
        )
        for record in work.rounds
    }


def read_agent_feed(
    *,
    work: AgentWork,
    zone: tzinfo | None,
    rounds: tuple[WebAgentRound, ...],
) -> WebAgentFeed:
    """Read the complete saved feed for any agent work."""
    feed_rounds = []
    feed_cursor = WebFeedCursor(round_number=0, position=0)
    for round_feed in _list_round_feeds(work=work).values():
        record = round_feed.record
        written_lines, position = read_lines_from(path=round_feed.feed, position=0)
        feed_cursor = WebFeedCursor(round_number=record.number, position=position)
        feed_rounds.append(
            WebFeedRound(
                number=record.number,
                lines=(
                    _compose_web_round_boundary(
                        record=record,
                        round_=_find_web_round(rounds=rounds, number=record.number),
                    ),
                    *(
                        _compose_web_feed_line(written_line=written_line, zone=zone)
                        for written_line in written_lines
                    ),
                ),
            )
        )
    return WebAgentFeed(
        rounds=tuple(feed_rounds),
        feed_cursor=_encode_feed_cursor(feed_cursor=feed_cursor),
    )


def _find_web_round(*, rounds: tuple[WebAgentRound, ...], number: int) -> WebAgentRound:
    """Return the round row with this number.

    The rows and the feeds are read from the same agent work, so every round
    whose feed is read has a row.
    """
    return next(round_ for round_ in rounds if round_.number == number)


def _compose_web_feed_line(*, written_line: str, zone: tzinfo | None) -> WebFeedLine:
    line = read_feed_line(written_line=written_line)
    if line is None:
        return WebFeedLine(timestamp=None, label=None, detail=written_line)
    return WebFeedLine(
        timestamp=describe_time(at=line.at, zone=zone),
        label=line.label,
        detail=line.detail,
        is_subagent=line.is_subagent,
    )
