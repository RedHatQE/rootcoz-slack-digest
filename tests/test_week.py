"""Tests for week window helpers."""

from datetime import UTC, date, datetime

import pytest

from rootcoz_slack_digest.week import last_complete_week, week_from_dates


def test_last_complete_week_from_wednesday() -> None:
    # 2026-08-05 is Wednesday → last Sunday 2026-08-02, Monday 2026-07-27
    as_of = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    window = last_complete_week(as_of=as_of)
    assert window.date_from == date(2026, 7, 27)
    assert window.date_to == date(2026, 8, 2)


def test_last_complete_week_on_sunday_uses_previous_week() -> None:
    # If "today" is Sunday, that week is not complete yet → previous Sunday
    as_of = datetime(2026, 8, 2, 18, 0, tzinfo=UTC)  # Sunday
    window = last_complete_week(as_of=as_of)
    assert window.date_from == date(2026, 7, 20)
    assert window.date_to == date(2026, 7, 26)


def test_week_from_dates_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="date_to"):
        week_from_dates(date(2026, 8, 2), date(2026, 8, 1))


def test_week_label() -> None:
    window = week_from_dates(date(2026, 7, 27), date(2026, 8, 2))
    assert "Jul 27" in window.label
    assert "2026" in window.label
