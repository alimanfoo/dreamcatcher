"""The clock the tests read, pinned so every run and every platform agrees.

A test that asserts on a timestamp cannot read the real clock. Every timing test
in this project passes one of these in instead.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

PINNED = datetime(2026, 8, 19, 18, 41, 58, tzinfo=UTC)
DISPLAY_TIME_ZONE = timezone(timedelta(hours=8))


@dataclass(kw_only=True)
class Ticking:
    """A clock that starts at the pinned time and moves on with every reading."""

    step: float = 1
    readings: list[datetime] = field(default_factory=list)

    def __call__(self) -> datetime:
        """Return the next reading, and remember it."""
        self.readings.append(PINNED + timedelta(seconds=self.step * len(self.readings)))
        return self.readings[-1]
