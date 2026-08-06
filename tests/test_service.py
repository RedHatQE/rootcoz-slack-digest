"""Tests for digest orchestration (offline rows)."""

from datetime import date

from rootcoz_slack_digest.mentions import StaticUsergroupResolver
from rootcoz_slack_digest.models import AppConfig, JobRow, MentionsConfig
from rootcoz_slack_digest.service import run_digest


def test_run_digest_dry_run_with_injected_rows() -> None:
    cfg = AppConfig(
        mentions=MentionsConfig(teams={"network": "network-qe"}),
    )
    rows = [
        JobRow(
            job_id="j1",
            job_name="tier2-network",
            tier="gating",
            failure_count=4,
            reviewed_count=1,
            jenkins_url="https://jenkins.example/job/tier2-network/9/",
            rootcoz_url="https://rootcoz.example/results/j1",
        )
    ]
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        usergroup_resolver=StaticUsergroupResolver({"network-qe": "S42"}),
    )
    assert result.posted is False
    assert len(result.rows) == 1
    header = result.blocks[0]["text"]["text"]  # type: ignore[index]
    assert "<!subteam^S42>" in header
