"""Tests for digest orchestration (offline rows / API-shaped data)."""

from datetime import date

from rootcoz_slack_digest.mentions import StaticUsergroupResolver
from rootcoz_slack_digest.models import AppConfig, JobRow, SlackTarget
from rootcoz_slack_digest.service import run_digest


def test_run_digest_dry_run_with_injected_rows() -> None:
    cfg = AppConfig()
    rows = [
        JobRow(
            job_id="j1",
            job_name="tier2-network",
            tier="gating",
            team="network",
            failure_count=4,
            reviewed_count=1,
            jenkins_url="https://jenkins.example/job/tier2-network/9/",
            rootcoz_url="https://rootcoz.example/results/j1",
        )
    ]
    targets = [
        SlackTarget(team="network", channel="Cnetwork", usergroup="network-qe"),
    ]
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        targets=targets,
        usergroup_resolver=StaticUsergroupResolver({"network-qe": "S42"}),
    )
    assert result.posted is False
    assert len(result.target_results) == 1
    assert len(result.rows) == 1
    blob = str(result.payload)
    assert "<!subteam^S42>" in blob
    assert "rootcause-summary" not in blob
    assert "HTML summary" not in blob


def test_run_digest_celebrates_when_team_has_no_unreviewed_failures() -> None:
    cfg = AppConfig()
    rows = [
        JobRow(
            job_id="j1",
            job_name="tier2-storage",
            tier="gating",
            team="storage",
            failure_count=2,
            reviewed_count=0,
            jenkins_url="https://jenkins.example/job/tier2-storage/1/",
            rootcoz_url="https://rootcoz.example/results/j1",
        )
    ]
    targets = [
        SlackTarget(team="network", channel="Cnetwork", usergroup="network-qe"),
    ]
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        targets=targets,
        usergroup_resolver=StaticUsergroupResolver({"network-qe": "S42"}),
    )
    assert result.posted is False
    assert len(result.target_results) == 1
    assert result.target_results[0].rows == []
    blob = str(result.payload)
    assert "All clear for" in blob
    assert "either no failures occurred or all have been reviewed" in blob
    assert "*network*" in blob
    assert "<!subteam^S42>" in blob


def test_load_example_has_no_html_summary_url() -> None:
    from pathlib import Path

    from rootcoz_slack_digest.models import load_config

    cfg = load_config(Path(__file__).resolve().parents[1] / "config" / "config.example.toml")
    assert "rootcause_summary_url" not in type(cfg.digest).model_fields
    assert cfg.schedule.cron == "0 7 * * 0"
    assert "job_name" in [c.value for c in cfg.digest.columns]
    assert cfg.rootcoz.field_map.team == "metadata.team"
    assert "gating" in cfg.rootcoz.tier_labels.labels
