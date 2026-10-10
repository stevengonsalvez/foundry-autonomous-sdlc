"""Wall clock for the hosted runtime and ISO 8601 helpers. Stdlib only."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp ('Z' or an offset) into an aware UTC datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def format_iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_between(start: str, end: str) -> int:
    return int((parse_iso(end) - parse_iso(start)).total_seconds())


class SystemClock:
    def now_iso(self) -> str:
        return format_iso(datetime.now(UTC))

    def monotonic(self) -> float:
        return time.monotonic()
