"""Tests for config loading."""

from pathlib import Path

from rootcoz_slack_digest.models import load_config


def test_load_config_example(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / "config" / "config.example.toml"
    cfg = load_config(example)
    assert cfg.digest.max_rows == 0
    assert cfg.slack.mode == "bot"
    assert "exclude_tags" not in type(cfg.digest).model_fields


def test_load_config_missing_file() -> None:
    cfg = load_config(Path("/nonexistent/config.toml"))
    assert cfg.digest.max_rows == 0
