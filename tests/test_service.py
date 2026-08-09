"""Tests for digest orchestration (offline rows / API-shaped data)."""

import json
from datetime import date

import pytest

from rootcoz_slack_digest.mentions import StaticUsergroupResolver
from rootcoz_slack_digest.models import (
    AppConfig,
    EmailConfig,
    EmailTargetConfig,
    JobRow,
    SlackTargetConfig,
    Target,
)
from rootcoz_slack_digest.service import _load_targets, run_digest


def _slack_target(team: str = "network") -> Target:
    return Target(
        team=team,
        slack=SlackTargetConfig(channel="Cnetwork", usergroup="network-qe"),
    )


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
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        targets=[_slack_target()],
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
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        targets=[_slack_target()],
        usergroup_resolver=StaticUsergroupResolver({"network-qe": "S42"}),
    )
    assert result.posted is False
    assert len(result.target_results) == 1
    assert result.target_results[0].rows == []
    assert result.target_results[0].total_jobs == 0
    blob = str(result.payload)
    # Injected-rows mode skips count_all_jobs → treated as zero failures
    assert "Zero" in blob
    assert "failures for" in blob
    assert "*network*" in blob
    assert "<!subteam^S42>" in blob
    assert "gating" in blob


def test_run_digest_sends_email_when_enabled() -> None:
    class FakeEmail:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        def send(self, **kwargs: object) -> None:
            self.sent.append(kwargs)

    cfg = AppConfig(email=EmailConfig(enabled=True))
    rows = [
        JobRow(
            job_id="j1",
            job_name="tier2-network",
            tier="gating",
            team="network",
            failure_count=2,
            reviewed_count=0,
            jenkins_url="https://jenkins.example/job/n/1/",
            rootcoz_url="https://rootcoz.example/results/j1",
        )
    ]
    targets = [
        Target(
            team="network",
            email=EmailTargetConfig(recipients=["net@example.com"], cc=["cc@example.com"]),
        )
    ]
    fake = FakeEmail()
    result = run_digest(
        cfg,
        dry_run=False,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        targets=targets,
        email_client=fake,  # type: ignore[arg-type]
    )
    assert result.posted is True
    assert len(fake.sent) == 1
    assert fake.sent[0]["recipients"] == ["net@example.com"]
    assert fake.sent[0]["cc"] == ["cc@example.com"]
    assert "network" in str(fake.sent[0]["subject"])
    assert "tier2-network" in str(fake.sent[0]["html_body"])


def test_run_digest_email_celebration_uses_total_jobs() -> None:
    class FakeEmail:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        def send(self, **kwargs: object) -> None:
            self.sent.append(kwargs)

    cfg = AppConfig(email=EmailConfig(enabled=True))
    targets = [
        Target(
            team="network",
            email=EmailTargetConfig(recipients=["net@example.com"]),
        )
    ]
    fake = FakeEmail()
    result = run_digest(
        cfg,
        dry_run=False,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=[],  # no matching rows → celebration with total_jobs=0
        targets=targets,
        email_client=fake,  # type: ignore[arg-type]
    )
    assert result.posted is True
    assert result.target_results[0].total_jobs == 0
    assert "Zero" in str(fake.sent[0]["html_body"])


def test_load_targets_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "team": "network",
            "slack": {"channel": "C1", "usergroup": "network-qe"},
            "email": {"recipients": ["a@example.com"], "cc": ["b@example.com"]},
        }
    ]
    monkeypatch.setenv("TARGETS", json.dumps(payload))
    targets = _load_targets()
    assert len(targets) == 1
    assert targets[0].team == "network"
    assert targets[0].slack is not None
    assert targets[0].slack.channel == "C1"
    assert targets[0].email is not None
    assert targets[0].email.recipients == ["a@example.com"]


def test_load_targets_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARGETS", raising=False)
    assert _load_targets() == []


def test_load_example_has_no_html_summary_url() -> None:
    from pathlib import Path

    from rootcoz_slack_digest.models import load_config

    cfg = load_config(Path(__file__).resolve().parents[1] / "config" / "config.example.toml")
    assert "rootcause_summary_url" not in type(cfg.digest).model_fields
    assert cfg.schedule.cron == "0 7 * * 0"
    assert "job_name" in [c.value for c in cfg.digest.columns]
    assert cfg.rootcoz.field_map.team == "metadata.team"
    assert "gating" in cfg.rootcoz.tier_labels.labels
    assert cfg.email.enabled is False
