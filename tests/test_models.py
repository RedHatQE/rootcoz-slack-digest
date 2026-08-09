"""Tests for config loading."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rootcoz_slack_digest.models import (
    EmailTargetConfig,
    FieldMapConfig,
    MessageConfig,
    SlackTargetConfig,
    Target,
    TierLabelsConfig,
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


def test_tier_labels_flat_toml_keeps_default_tier() -> None:
    cfg = TierLabelsConfig.model_validate(
        {"gating": "gating", "release-checklist": "rc", "default_tier": "misc"}
    )
    assert cfg.default_tier == "misc"
    assert cfg.labels == {"gating": "gating", "release-checklist": "rc"}
    assert "default_tier" not in cfg.labels


def test_message_and_field_map_configurable_defaults() -> None:
    msg = MessageConfig()
    assert "{lanes}" in msg.celebration_reviewed_template
    assert "{lanes}" in msg.celebration_no_failures_template
    assert msg.email_subject_template.startswith("rootcoz")
    assert FieldMapConfig().bundle_pattern == r"v\d+\.\d+\."
