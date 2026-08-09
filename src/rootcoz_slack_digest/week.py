"""Week-window helpers (last complete Sunday–Saturday in UTC)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from rootcoz_slack_digest.models import WeekWindow


def last_complete_week(*, as_of: datetime | None = None) -> WeekWindow:
    """Return the most recent complete Sun–Sat week.

    If today is Saturday, the current week is incomplete — return the previous one.
    If today is Sunday, today starts a new week — return the previous Sun–Sat.
    """
    now = as_of or datetime.now(tz=UTC)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now.astimezone(UTC)
    today = now.date()

    # Find last Saturday (end of last complete week)
    # Saturday = weekday 5
    days_since_saturday = (today.weekday() - 5) % 7
    if days_since_saturday == 0:
        days_since_saturday = 7  # If today is Saturday, go to previous Saturday
    last_saturday = today - timedelta(days=days_since_saturday)
    last_sunday = last_saturday - timedelta(days=6)
    return WeekWindow(date_from=last_sunday, date_to=last_saturday)


def week_from_dates(date_from: date, date_to: date) -> WeekWindow:
    """Build a window from explicit dates (inclusive)."""
    if date_to < date_from:
        msg = f"date_to {date_to} must be >= date_from {date_from}"
        raise ValueError(msg)
    return WeekWindow(date_from=date_from, date_to=date_to)
