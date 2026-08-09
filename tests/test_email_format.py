"""Tests for HTML email formatting."""

from datetime import date

from rootcoz_slack_digest.email_format import format_celebration_html, format_digest_html
from rootcoz_slack_digest.models import JobRow, WeekWindow


def test_format_digest_html_includes_rows_and_links() -> None:
    window = WeekWindow(date_from=date(2026, 7, 27), date_to=date(2026, 8, 2))
    rows = [
        JobRow(
            job_id="j1",
            job_name="tier2-network",
            tier="gating",
            team="network",
            failure_count=3,
            reviewed_count=1,
            version="4.22",
            bundle="v4.22.6.rhel9-9",
            jenkins_url="https://jenkins.example/job/n/1/",
            rootcoz_url="https://rootcoz.example/results/j1",
            created_at="2026-07-28T12:00:00Z",
        )
    ]
    html = format_digest_html(window=window, rows=rows, team="network", tiers=["gating"])
    assert "rootcoz weekly digest" in html
    assert "network" in html
    assert "tier2-network" in html
    assert "https://jenkins.example/job/n/1/" in html
    assert "https://rootcoz.example/results/j1" in html
    assert "[v4.22.6.rhel9-9] 1/3 reviewed" in html


def test_format_celebration_html_zero_and_all_reviewed() -> None:
    window = WeekWindow(date_from=date(2026, 7, 27), date_to=date(2026, 8, 2))
    zero = format_celebration_html(window=window, team="network", total_jobs=0, tiers=["gating"])
    assert "Zero" in zero
    assert "network" in zero
    reviewed = format_celebration_html(
        window=window, team="network", total_jobs=5, tiers=["gating"]
    )
    assert "All" in reviewed
    assert "5" in reviewed


def test_format_celebration_html_includes_job_links() -> None:
    window = WeekWindow(date_from=date(2026, 7, 27), date_to=date(2026, 8, 2))
    jobs = [
        JobRow(
            job_id="j1",
            job_name="tier2-network",
            rootcoz_url="https://rootcoz.example/results/j1",
            bundle="v4.22.6.rhel9-9",
        ),
        JobRow(job_id="j2", job_name="no-link-job", bundle="v4.23.0.rhel9-9"),
    ]
    html = format_celebration_html(
        window=window,
        team="network",
        total_jobs=2,
        tiers=["gating"],
        jobs=jobs,
    )
    assert 'href="https://rootcoz.example/results/j1"' in html
    assert "tier2-network" in html
    assert "[v4.22.6.rhel9-9]" in html
    assert "<li>no-link-job [v4.23.0.rhel9-9]</li>" in html


def test_format_celebration_html_truncates_links() -> None:
    window = WeekWindow(date_from=date(2026, 7, 27), date_to=date(2026, 8, 2))
    jobs = [
        JobRow(
            job_id=f"j{i}",
            job_name=f"job-{i}",
            rootcoz_url=f"https://rootcoz.example/results/j{i}",
        )
        for i in range(25)
    ]
    html = format_celebration_html(
        window=window,
        team="network",
        total_jobs=25,
        tiers=["gating"],
        jobs=jobs,
    )
    assert "+5 more reviewed jobs" in html
    assert "job-0" in html
    assert "job-19" in html
    assert "job-20" not in html
