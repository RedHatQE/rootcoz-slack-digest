"""Tests for Slack message formatting from API rows."""

from datetime import date

from rootcoz_slack_digest.models import (
    DigestColumn,
    JobRow,
    MessageConfig,
    MessageFormat,
    SortBy,
)
from rootcoz_slack_digest.slack_format import build_message, sort_rows
from rootcoz_slack_digest.week import week_from_dates


def _row(name: str, failures: int, reviewed: int) -> JobRow:
    return JobRow(
        job_id=name,
        job_name=name,
        tier="gating",
        failure_count=failures,
        reviewed_count=reviewed,
        jenkins_url=f"https://jenkins.example/job/{name}/1/",
        rootcoz_url=f"https://rootcoz.example/results/{name}",
    )


def test_sort_by_not_reviewed() -> None:
    rows = [
        _row("a", 10, 9),
        _row("b", 5, 0),
        _row("c", 3, 3),
    ]
    ordered = sort_rows(rows, SortBy.NOT_REVIEWED)
    assert [r.job_name for r in ordered] == ["b", "a", "c"]


def test_build_message_blocks_no_html_summary() -> None:
    window = week_from_dates(date(2026, 7, 27), date(2026, 8, 2))
    rows = [_row(f"job-{i}", 2, 0) for i in range(5)]
    payload = build_message(
        window=window,
        rows=rows,
        max_rows=2,
        sort_by=SortBy.NOT_REVIEWED,
        columns=[
            DigestColumn.JOB_NAME,
            DigestColumn.TIER,
            DigestColumn.FAILURES,
            DigestColumn.REVIEWED,
            DigestColumn.JENKINS,
            DigestColumn.ROOTCOZ,
        ],
        message=MessageConfig(),
        mention="<!subteam^S1>",
    )
    assert isinstance(payload, list)
    blob = str(payload)
    assert "cc <!subteam^S1>" in blob
    assert "HTML summary" not in blob
    assert "rootcause-summary" not in blob
    assert "+3 more" in blob


def test_columns_omit_jenkins() -> None:
    window = week_from_dates(date(2026, 7, 27), date(2026, 8, 2))
    payload = build_message(
        window=window,
        rows=[_row("only", 1, 0)],
        max_rows=10,
        sort_by=SortBy.JOB_NAME,
        columns=[DigestColumn.JOB_NAME, DigestColumn.FAILURES, DigestColumn.ROOTCOZ],
        message=MessageConfig(format=MessageFormat.MRKDWN, table_code_fence=True),
        mention="",
    )
    assert isinstance(payload, str)
    assert "Jenkins" not in payload
    assert "rootcoz" in payload


def test_plain_format_is_string() -> None:
    window = week_from_dates(date(2026, 7, 27), date(2026, 8, 2))
    payload = build_message(
        window=window,
        rows=[_row("j", 1, 0)],
        max_rows=10,
        sort_by=SortBy.JOB_NAME,
        columns=[DigestColumn.JOB_NAME, DigestColumn.FAILURES],
        message=MessageConfig(format=MessageFormat.PLAIN),
    )
    assert isinstance(payload, str)
    assert "HTML" not in payload
