"""Tests for config loading."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rootcoz_slack_digest.models import (
    EmailTargetConfig,
    SlackTargetConfig,
    Target,
    load_config,
)


def test_load_config_example(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / "config" / "config.example.toml"
    cfg = load_config(example)
    assert cfg.digest.max_rows == 0
    assert cfg.slack.mode == "bot"
    assert cfg.email.enabled is False
    assert "exclude_tags" not in type(cfg.digest).model_fields


def test_load_config_missing_file() -> None:
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.digest.max_rows == 0


def test_target_requires_slack_or_email() -> None:
    with pytest.raises(ValidationError):
        Target(team="network")


def test_target_accepts_nested_slack_and_email() -> None:
    t = Target(
        team="network",
        slack=SlackTargetConfig(channel="C1", usergroup="ug"),
        email=EmailTargetConfig(recipients=["a@example.com"]),
    )
    assert t.slack is not None
    assert t.slack.channel == "C1"
    assert t.email is not None
    assert t.email.recipients == ["a@example.com"]
