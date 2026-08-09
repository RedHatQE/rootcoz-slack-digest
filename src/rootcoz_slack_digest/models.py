"""Immutable domain models and configuration."""

from __future__ import annotations

import tomllib
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    """Inclusive Sun–Sat UTC week window."""

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
    created_at: str = ""
    version: str = ""

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

    max_rows: int = Field(default=0, ge=0)  # 0 = no limit
    sort_by: SortBy = SortBy.NOT_REVIEWED
    # Passed as API ``label`` query params (server-side tier filter).
    tiers: list[str] = Field(default_factory=lambda: ["gating", "release-checklist", "other"])
    columns: list[DigestColumn] = Field(default_factory=lambda: list(DEFAULT_COLUMNS))
    # Passed as API ``exclude_label`` query params (metadata labels).
    exclude_labels: list[str] = Field(default_factory=list)
    # Client-side filter: drop jobs whose name contains any of these substrings.
    exclude_job_patterns: list[str] = Field(default_factory=list)

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
        "Jobs: *{total_jobs}* · Failures: *{total_failures}* · "
        "Reviewed: *{total_reviewed}/{total_failures}*"
    )
    row_template: str = (
        "• *{job_name}* ({tier}) — fail {failures} / rev {reviewed}{jenkins_part}{rootcoz_part}"
    )
    omitted_template: str = "_+{omitted} more jobs not shown (raise digest.max_rows)._"
    table_code_fence: bool = True


class FieldMapConfig(BaseModel):
    """Map logical field names → JSON dot-paths in the API response."""

    model_config = ConfigDict(frozen=True)

    job_id: str = "job_id"
    job_name: str = "job_name"
    team: str = "metadata.team"
    version: str = "metadata.version"
    tier: str = "metadata.labels"
    failures: str = "failure_count"
    reviewed: str = "reviewed_count"
    build: str = "build_number"
    jenkins: str = "jenkins_url"
    rootcoz: str = "{url}/results/{job_id}"
    created_at: str = "created_at"


class TierLabelsConfig(BaseModel):
    """Map API label values → display tier names. Unmatched → 'other'."""

    model_config = ConfigDict(frozen=True)

    labels: dict[str, str] = Field(
        default_factory=lambda: {
            "gating": "gating",
            "release-checklist": "release-checklist",
        }
    )

    @model_validator(mode="before")
    @classmethod
    def _wrap_flat_labels(cls, value: Any) -> Any:
        """Accept flat TOML ``[rootcoz.tier_labels] key = value`` as ``labels``."""
        if isinstance(value, dict) and "labels" not in value:
            return {"labels": value}
        return value

    @field_validator("labels", mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return {"gating": "gating", "release-checklist": "release-checklist"}
        return value


class RootcozConfig(BaseModel):
    """Rootcoz connection + API mapping settings."""

    model_config = ConfigDict(frozen=True)

    url: str = ""
    api_key: str = ""
    verify_ssl: bool = True
    endpoint: str = "/api/dashboard/filtered"
    params: dict[str, str] = Field(
        default_factory=lambda: {
            "review_status": "not_reviewed",
            "limit": "0",
        }
    )
    field_map: FieldMapConfig = Field(default_factory=FieldMapConfig)
    tier_labels: TierLabelsConfig = Field(default_factory=TierLabelsConfig)


class SlackConfig(BaseModel):
    """Slack posting settings."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["webhook", "bot"] = "bot"
    webhook_url: str = ""
    bot_token: str = ""


class SlackTargetConfig(BaseModel):
    """Slack delivery config for a target."""

    model_config = ConfigDict(frozen=True)

    channel: str
    usergroup: str = ""


class EmailTargetConfig(BaseModel):
    """Email delivery config for a target."""

    model_config = ConfigDict(frozen=True)

    recipients: list[str]
    cc: list[str] = Field(default_factory=list)


class Target(BaseModel):
    """One team routing entry with optional Slack and email delivery."""

    model_config = ConfigDict(frozen=True)

    team: str
    slack: SlackTargetConfig | None = None
    email: EmailTargetConfig | None = None

    @model_validator(mode="after")
    def _require_delivery(self) -> Target:
        if self.slack is None and self.email is None:
            msg = f"Target for team {self.team!r} must have slack and/or email"
            raise ValueError(msg)
        return self


class EmailConfig(BaseModel):
    """SMTP email settings."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 25
    from_address: str = "rootcoz-digest@redhat.com"
    use_tls: bool = False


class AppConfig(BaseModel):
    """Full application config loaded from TOML + env overlays."""

    model_config = ConfigDict(frozen=True)

    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    message: MessageConfig = Field(default_factory=MessageConfig)
    rootcoz: RootcozConfig = Field(default_factory=RootcozConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)


def load_config(path: Path | None) -> AppConfig:
    """Load config from TOML. Missing file yields defaults."""
    if path is None or not path.is_file():
        return AppConfig()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return AppConfig.model_validate(raw)
