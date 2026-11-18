"""Timezone-aware clocks and production dates.

Production dates use the client timezone. A slot at 19:00 in Berlin belongs
to that local calendar day even when UTC has already moved on.
"""

from datetime import datetime, timezone
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    """Source of the current instant. Tests supply a fixed clock."""

    def now(self) -> datetime:
        """Return a timezone-aware UTC instant."""


class SystemClock:
    """Clock backed by the operating system."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """Clock that always returns the same instant."""

    def __init__(self, moment: datetime) -> None:
        self._moment = ensure_utc(moment)

    def now(self) -> datetime:
        return self._moment


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes and convert aware ones to UTC."""

    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    """Serialize an aware datetime as a stable UTC timestamp."""

    return ensure_utc(value).isoformat(timespec="seconds")


def parse_utc(value: str) -> datetime:
    """Parse a timestamp written by utc_iso."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ValueError("stored datetime is missing a timezone")
    return parsed.astimezone(timezone.utc)


def production_date(now: datetime, timezone_name: str) -> str:
    """Return the client-local calendar date as YYYY-MM-DD."""

    local = ensure_utc(now).astimezone(ZoneInfo(timezone_name))
    return local.date().isoformat()
