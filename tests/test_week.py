"""Tests for week window helpers."""

from datetime import UTC, date, datetime

import pytest

from rootcoz_slack_digest.week import last_complete_week, week_from_dates


def test_last_complete_week_from_wednesday() -> None:
    # 2026-08-05 is Wednesday → last Sat 2026-08-01, Sun 2026-07-26
    as_of = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    window = last_complete_week(as_of=as_of)
    assert window.date_from == date(2026, 7, 26)
    assert window.date_to == date(2026, 8, 1)


def test_last_complete_week_on_sunday_uses_previous_week() -> None:
    # Sunday starts a new week → previous Sun–Sat
    as_of = datetime(2026, 8, 2, 18, 0, tzinfo=UTC)  # Sunday
    window = last_complete_week(as_of=as_of)
    assert window.date_from == date(2026, 7, 26)
    assert window.date_to == date(2026, 8, 1)


def test_last_complete_week_on_saturday_uses_previous_week() -> None:
    # Saturday's current week is incomplete → previous Sun–Sat
    as_of = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)  # Saturday
    window = last_complete_week(as_of=as_of)
    assert window.date_from == date(2026, 7, 19)
    assert window.date_to == date(2026, 7, 25)


def test_last_complete_week_monday_start() -> None:
    # Wednesday 2026-08-05 → last complete Mon–Sun is Jul 27 – Aug 2
    as_of = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    window = last_complete_week(as_of=as_of, week_start="monday")
    assert window.date_from == date(2026, 7, 27)
    assert window.date_to == date(2026, 8, 2)


def test_last_complete_week_rejects_bad_week_start() -> None:
    with pytest.raises(ValueError, match="week_start"):
        last_complete_week(week_start="friday")


def test_week_from_dates_rejects_inverted_range() -> None:
    with pytest.raises(ValueError, match="date_to"):
        week_from_dates(date(2026, 8, 2), date(2026, 8, 1))


def test_week_label() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    assert "Jul 26" in window.label
    assert "2026" in window.label
