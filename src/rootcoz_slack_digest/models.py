"""Immutable domain models and configuration."""

from __future__ import annotations

import tomllib
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SortBy(StrEnum):
    """How to order job rows in the digest."""

    NOT_REVIEWED = "not_reviewed"
    FAILURES = "failures"
    JOB_NAME = "job_name"


class DigestColumn(StrEnum):
    """Allowed Slack message columns (order comes from config list)."""

    JOB_NAME = "job_name"
    TIER = "tier"
    TEAM = "team"
    FAILURES = "failures"
    REVIEWED = "reviewed"
    NOT_REVIEWED = "not_reviewed"
    JENKINS = "jenkins"
    ROOTCOZ = "rootcoz"
    BUILD = "build"


class MessageFormat(StrEnum):
    """How the digest is rendered for Slack."""

    BLOCKS = "blocks"
    MRKDWN = "mrkdwn"
    PLAIN = "plain"


DEFAULT_COLUMNS: list[DigestColumn] = [
    DigestColumn.JOB_NAME,
    DigestColumn.TIER,
    DigestColumn.FAILURES,
    DigestColumn.REVIEWED,
    DigestColumn.JENKINS,
    DigestColumn.ROOTCOZ,
]


class WeekWindow(BaseModel):
    """Inclusive Mon–Sun UTC week window."""

    model_config = ConfigDict(frozen=True)

    date_from: date
    date_to: date

    @property
    def label(self) -> str:
        """Human-readable week range."""
        return f"{self.date_from.strftime('%b %d')} – {self.date_to.strftime('%b %d, %Y')}"


class JobRow(BaseModel):
    """One job line in the Slack digest table."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    job_name: str
    tier: str = "other"
    team: str = ""
    failure_count: int = 0
    reviewed_count: int = 0
    build_number: int | None = None
    jenkins_url: str = ""
    rootcoz_url: str = ""

    @property
    def not_reviewed(self) -> int:
        """Failures still waiting on review."""
        return max(self.failure_count - self.reviewed_count, 0)


class ScheduleConfig(BaseModel):
    """When the digest should run (CronJob must match ``cron``)."""

    model_config = ConfigDict(frozen=True)

    cron: str = "0 7 * * 0"
    timezone: str = "UTC"


class DigestConfig(BaseModel):
    """Digest behaviour from config.toml ``[digest]``."""

    model_config = ConfigDict(frozen=True)

    max_rows: int = 25
    sort_by: SortBy = SortBy.NOT_REVIEWED
    tiers: list[str] = Field(default_factory=lambda: ["gating", "release-checklist", "other"])
    teams: list[str] = Field(default_factory=list)
    columns: list[DigestColumn] = Field(default_factory=lambda: list(DEFAULT_COLUMNS))

    @field_validator("columns", mode="before")
    @classmethod
    def _normalize_columns(cls, value: Any) -> Any:
        if value is None or value == []:
            return list(DEFAULT_COLUMNS)
        return value


class MessageConfig(BaseModel):
    """Slack message layout templates (API data only — no external HTML reports)."""

    model_config = ConfigDict(frozen=True)

    format: MessageFormat = MessageFormat.BLOCKS
    include_mentions: bool = True
    header_template: str = "*rootcoz weekly digest* — {week_label}{mention_suffix}"
    totals_template: str = (
        "Jobs: *{total_jobs}* · Failures: *{total_failures}* · Reviewed: *{total_reviewed}*"
    )
    row_template: str = (
        "• *{job_name}* ({tier}) — fail {failures} / rev {reviewed}{jenkins_part}{rootcoz_part}"
    )
    omitted_template: str = "_+{omitted} more jobs not shown (raise digest.max_rows)._"
    table_code_fence: bool = True


class RootcozConfig(BaseModel):
    """Rootcoz connection settings (secrets usually from env)."""

    model_config = ConfigDict(frozen=True)

    url: str = ""
    username: str = ""
    api_key: str = ""
    verify_ssl: bool = True


class SlackConfig(BaseModel):
    """Slack posting settings."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["webhook", "bot"] = "bot"
    webhook_url: str = ""
    bot_token: str = ""
    channel: str = ""


class MentionsConfig(BaseModel):
    """Team key → Slack usergroup handle (without @). Teams own membership."""

    model_config = ConfigDict(frozen=True)

    teams: dict[str, str] = Field(default_factory=dict)

    @field_validator("teams", mode="before")
    @classmethod
    def _strip_at(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {str(k): str(v).lstrip("@") for k, v in value.items() if v is not None}


class AppConfig(BaseModel):
    """Full application config loaded from TOML + env overlays."""

    model_config = ConfigDict(frozen=True)

    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    message: MessageConfig = Field(default_factory=MessageConfig)
    rootcoz: RootcozConfig = Field(default_factory=RootcozConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    mentions: MentionsConfig = Field(default_factory=MentionsConfig)


def load_config(path: Path | None) -> AppConfig:
    """Load config from TOML. Missing file yields defaults."""
    if path is None or not path.is_file():
        return AppConfig()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return AppConfig.model_validate(raw)
