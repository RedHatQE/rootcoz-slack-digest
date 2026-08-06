"""Tests for Slack Block Kit formatting."""

from datetime import date

from rootcoz_slack_digest.models import JobRow, SortBy
from rootcoz_slack_digest.slack_format import build_blocks, sort_rows
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
        _row("a", 10, 9),  # 1 left
        _row("b", 5, 0),  # 5 left
        _row("c", 3, 3),  # 0 left
    ]
    ordered = sort_rows(rows, SortBy.NOT_REVIEWED)
    assert [r.job_name for r in ordered] == ["b", "a", "c"]


def test_build_blocks_includes_mention_and_omission() -> None:
    window = week_from_dates(date(2026, 7, 27), date(2026, 8, 2))
    rows = [_row(f"job-{i}", 2, 0) for i in range(5)]
    blocks = build_blocks(
        window=window,
        rows=rows,
        max_rows=2,
        sort_by=SortBy.NOT_REVIEWED,
        mention="<!subteam^S1>",
        summary_url="https://summary.example/",
    )
    header = blocks[0]["text"]["text"]  # type: ignore[index]
    assert "cc <!subteam^S1>" in header
    assert any("+3 more" in str(b.get("elements", b.get("text", ""))) for b in blocks)
