"""Week-window helpers (last complete Monday–Sunday in UTC)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from rootcoz_slack_digest.models import WeekWindow


def last_complete_week(*, as_of: datetime | None = None) -> WeekWindow:
    """Return the most recent complete Mon–Sun week ending on the last Sunday.

    If ``as_of`` is a Sunday, that day is treated as the end of the *current*
    incomplete week, so the previous Sunday closes the window (same rule as
    rootcause-summary generate.py).
    """
    now = as_of or datetime.now(tz=UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)

    days_since_sunday = (now.weekday() + 1) % 7
    if days_since_sunday == 0:
        days_since_sunday = 7
    last_sunday = (now - timedelta(days=days_since_sunday)).date()
    monday = last_sunday - timedelta(days=6)
    return WeekWindow(date_from=monday, date_to=last_sunday)


def week_from_dates(date_from: date, date_to: date) -> WeekWindow:
    """Build a window from explicit dates (inclusive)."""
    if date_to < date_from:
        msg = f"date_to {date_to} must be >= date_from {date_from}"
        raise ValueError(msg)
    return WeekWindow(date_from=date_from, date_to=date_to)
