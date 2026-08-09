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


def _row(
    name: str,
    failures: int,
    reviewed: int,
    *,
    tier: str = "gating",
    version: str = "",
    bundle: str = "",
) -> JobRow:
    return JobRow(
        job_id=name,
        job_name=name,
        tier=tier,
        failure_count=failures,
        reviewed_count=reviewed,
        jenkins_url=f"https://jenkins.example/job/{name}/1/",
        rootcoz_url=f"https://rootcoz.example/results/{name}",
        version=version,
        bundle=bundle,
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
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    rows = [
        _row("job-a", 14, 0, tier="gating"),
        _row("job-b", 23, 0, tier="gating"),
        _row("job-c", 14, 0, tier="release-checklist"),
        _row("job-d", 23, 0, tier="other"),
        _row("job-e", 2, 0, tier="other"),
    ]
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
    # Mention is a context block (mrkdwn)
    assert payload[0] == {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "<!subteam^S1>"}],
    }
    tables = [b for b in payload if b.get("type") == "table"]
    assert tables
    assert "HTML summary" not in blob
    assert "rootcause-summary" not in blob
    assert "```" not in blob
    assert "*gating*" in blob
    assert "https://jenkins.example/job/" in blob
    # rootcoz column uses rich_text link with label "view"
    rootcoz_cells = [row[3] for table in tables for row in table["rows"][1:]]
    assert any(
        cell.get("type") == "rich_text" and cell["elements"][0]["elements"][0].get("text") == "view"
        for cell in rootcoz_cells
    )
    assert "+3 more" in blob


def test_build_message_max_rows_zero_shows_all() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    rows = [_row(f"job-{i}", i + 1, 0) for i in range(5)]
    payload = build_message(
        window=window,
        rows=rows,
        max_rows=0,
        sort_by=SortBy.NOT_REVIEWED,
        columns=[DigestColumn.JOB_NAME, DigestColumn.FAILURES],
        message=MessageConfig(format=MessageFormat.MRKDWN),
    )
    assert isinstance(payload, str)
    assert "more jobs not shown" not in payload
    for row in rows:
        assert row.job_name in payload


def test_grouped_by_tier_order_and_links() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    rows = [
        _row("other-job", 5, 0, tier="other"),
        _row("rc-job", 14, 0, tier="release-checklist"),
        _row("gate-low", 10, 0, tier="gating"),
        _row("gate-high", 23, 0, tier="gating"),
    ]
    payload = build_message(
        window=window,
        rows=rows,
        max_rows=10,
        sort_by=SortBy.JOB_NAME,
        columns=list(DigestColumn),
        message=MessageConfig(format=MessageFormat.MRKDWN),
    )
    assert isinstance(payload, str)
    gating_idx = payload.index("*gating*")
    rc_idx = payload.index("*release-checklist*")
    other_idx = payload.index("*other*")
    assert gating_idx < rc_idx < other_idx
    # Within gating: higher failures first
    assert payload.index("gate-high") < payload.index("gate-low")
    assert "<https://jenkins.example/job/gate-high/1/|gate-high>" in payload
    assert "0/23 reviewed · <https://rootcoz.example/results/gate-high|rootcoz>" in payload


def test_grouped_by_tier_sorts_by_version_then_bundle_then_failures() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    rows = [
        _row("job-4.22-high", 14, 0, version="4.22", bundle="v4.22.6.rhel9-9"),
        _row("job-5.0", 3, 0, version="5.0", bundle="v5.0.0.rhel9-9"),
        _row("job-4.22-older", 2, 0, version="4.22", bundle="v4.22.5.rhel9-8"),
        _row("job-4.22-low", 1, 0, version="4.22", bundle="v4.22.6.rhel9-9"),
        _row("job-4.23", 1, 0, version="4.23", bundle="v4.23.0.rhel9-9"),
    ]
    payload = build_message(
        window=window,
        rows=rows,
        max_rows=10,
        sort_by=SortBy.JOB_NAME,
        columns=list(DigestColumn),
        message=MessageConfig(format=MessageFormat.MRKDWN),
    )
    assert isinstance(payload, str)
    assert payload.index("job-5.0") < payload.index("job-4.23")
    assert payload.index("job-4.23") < payload.index("job-4.22-high")
    assert payload.index("job-4.22-high") < payload.index("job-4.22-low")
    assert payload.index("job-4.22-low") < payload.index("job-4.22-older")
    assert "[v5.0.0.rhel9-9] 0/3 reviewed" in payload
    assert "[v4.22.6.rhel9-9] 0/14 reviewed" in payload


def test_columns_omit_jenkins() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
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
    # Job name is the Jenkins link label; no separate "Jenkins" column label
    assert "Jenkins" not in payload
    assert "rootcoz" in payload


def test_plain_format_is_string() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
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


def test_build_message_blocks_use_table() -> None:
    """BLOCKS format uses table blocks (one per tier) instead of text sections."""
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    rows = [
        _row("gate-a", 2, 0, tier="gating", bundle="v4.22.6.rhel9-9"),
        _row("other-a", 3, 0, tier="other", bundle="v5.0.0.rhel9-9"),
    ]
    payload = build_message(
        window=window,
        rows=rows,
        max_rows=10,
        sort_by=SortBy.JOB_NAME,
        columns=[
            DigestColumn.JOB_NAME,
            DigestColumn.FAILURES,
            DigestColumn.REVIEWED,
            DigestColumn.JENKINS,
            DigestColumn.ROOTCOZ,
        ],
        message=MessageConfig(format=MessageFormat.BLOCKS),
    )
    assert isinstance(payload, list)
    types = [b.get("type") for b in payload]
    assert "divider" not in types
    tables = [b for b in payload if b.get("type") == "table"]
    assert len(tables) == 2
    # Tier headers before tables when multiple tiers
    assert "*gating*" in str(payload)
    assert "*other*" in str(payload)
    gate_table = tables[0]
    assert gate_table["column_settings"] == [
        {"is_wrapped": True},
        {},
        {"align": "right"},
        {},
    ]
    header = gate_table["rows"][0]
    assert [c["text"] for c in header] == ["Jobs (2)", "Bundle", "Reviewed (0/5)", "rootcoz"]
    job_cell = gate_table["rows"][1][0]
    assert job_cell["type"] == "rich_text"
    link = job_cell["elements"][0]["elements"][0]
    assert link["type"] == "link"
    assert link["url"] == "https://jenkins.example/job/gate-a/1/"
    assert link["text"] == "gate-a"
    assert gate_table["rows"][1][1]["text"] == "v4.22.6.rhel9-9"
    assert gate_table["rows"][1][2]["text"] == "0/2"
    rootcoz_link = gate_table["rows"][1][3]["elements"][0]["elements"][0]
    assert rootcoz_link["url"] == "https://rootcoz.example/results/gate-a"
    assert rootcoz_link["text"] == "view"


def test_build_message_includes_lanes_in_header() -> None:
    window = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))
    payload = build_message(
        window=window,
        rows=[_row("j", 1, 0)],
        max_rows=10,
        sort_by=SortBy.JOB_NAME,
        columns=[DigestColumn.JOB_NAME],
        message=MessageConfig(format=MessageFormat.MRKDWN),
        tiers=["gating", "release-checklist"],
    )
    assert isinstance(payload, str)
    assert "*rootcoz gating, release-checklist weekly digest*" in payload
