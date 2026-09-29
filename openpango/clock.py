"""Time helpers. All timestamps are UTC ISO strings ending in Z."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
DEMO_NOW = "2026-09-29T12:00:00Z"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    s = value.strip()
    if len(s) == 10:
        s += "T00:00:00Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ago(now: datetime, days: float) -> str:
    return iso(now - timedelta(days=days))


def fmt_date(value: str | datetime) -> str:
    """'Sep 20, 2026'. Manual formatting keeps output identical across platforms."""
    dt = parse(value)
    return f"{_MONTHS[dt.month - 1]} {dt.day}, {dt.year}"


def days_between(earlier: str | datetime, later: datetime) -> int:
    """Whole days elapsed, never negative."""
    return max(0, (later - parse(earlier)).days)


def fmt_money(cents: int) -> str:
    return f"${cents / 100:,.2f}"
