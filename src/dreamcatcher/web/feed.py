"""Read and compose web feed snapshots and tails."""

from collections.abc import Sequence
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
    WebFeedLine,
    WebFeedPosition,
    WebFeedRound,
)
from dreamcatcher.words import describe_time


@dataclass(frozen=True, kw_only=True)
class _WebRoundFeed:
    """Pair one saved round with the feed it wrote."""

    record: AgentRoundRecord
    feed: Path


class InvalidFeedPositionError(Exception):
    """Report a feed position that names no complete line of a saved round."""


def _encode_feed_position(*, feed_position: WebFeedPosition) -> str:
    return f"{feed_position.round_number}:{feed_position.position}"


def _is_ascii_digits(*, text: str) -> bool:
    return text.isascii() and text.isdigit()


def decode_feed_position(*, value: str) -> WebFeedPosition:
    """Decode a feed position from its encoded text form.

    Raise InvalidFeedPositionError when the value names no valid position.
    """
    round_text, separator, position_text = value.partition(":")
    has_leading_zero = round_text.startswith("0") and round_text != "0"
    if (
        not separator
        or has_leading_zero
        or not _is_ascii_digits(text=round_text)
        or not _is_ascii_digits(text=position_text)
    ):
        raise InvalidFeedPositionError
    try:
        feed_position = WebFeedPosition(
            round_number=int(round_text),
            position=int(position_text),
        )
    except ValueError:
        raise InvalidFeedPositionError from None
    if feed_position.round_number == 0 and feed_position.position != 0:
        raise InvalidFeedPositionError
    return feed_position


def read_agent_tail(
    *,
    work: AgentWork,
    github_repository_url: str | None,
    live: WebAgentLiveState,
    feed_position: WebFeedPosition,
    zone: tzinfo | None,
) -> WebAgentTail:
    """Read feed output written after one feed position for any agent work."""
    round_feeds = _list_round_feeds(work=work)
    number, position, is_opening_round = _resolve_feed_position(
        feed_position=feed_position,
        round_feeds=round_feeds,
    )
    feed_rounds = []
    next_feed_position = feed_position
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
        next_feed_position = WebFeedPosition(round_number=number, position=position)
        if should_stop:
            break
        number += 1
        position = 0
        is_opening_round = True
    return WebAgentTail(
        github_repository_url=github_repository_url,
        feed_position=_encode_feed_position(feed_position=next_feed_position),
        feed_rounds=tuple(feed_rounds),
        live=live,
        has_empty_feed_placeholder=feed_position.round_number == 0,
    )


def _read_tail_round(
    *,
    round_feed: _WebRoundFeed,
    number: int,
    position: int,
    is_opening_round: bool,
    rounds: Sequence[WebAgentRound],
    zone: tzinfo | None,
) -> tuple[WebFeedRound | None, int, bool]:
    record = round_feed.record
    if not is_complete_line_position(path=round_feed.feed, position=position):
        raise InvalidFeedPositionError
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


def _resolve_feed_position(
    *,
    feed_position: WebFeedPosition,
    round_feeds: dict[int, _WebRoundFeed],
) -> tuple[int, int, bool]:
    if feed_position.round_number == 0:
        return 1, 0, True
    if feed_position.round_number not in round_feeds:
        raise InvalidFeedPositionError
    return feed_position.round_number, feed_position.position, False


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
    rounds: Sequence[WebAgentRound],
) -> WebAgentFeed:
    """Read the complete saved feed for any agent work."""
    feed_rounds = []
    feed_position = WebFeedPosition(round_number=0, position=0)
    for round_feed in _list_round_feeds(work=work).values():
        record = round_feed.record
        written_lines, position = read_lines_from(path=round_feed.feed, position=0)
        feed_position = WebFeedPosition(round_number=record.number, position=position)
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
        feed_position=_encode_feed_position(feed_position=feed_position),
    )


def _find_web_round(*, rounds: Sequence[WebAgentRound], number: int) -> WebAgentRound:
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
    )
