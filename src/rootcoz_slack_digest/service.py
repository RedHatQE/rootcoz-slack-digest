"""Orchestrate week → rootcoz API → format → Slack."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date

from rootcoz_slack_digest.mentions import (
    SlackUsergroupResolver,
    StaticUsergroupResolver,
    UsergroupResolver,
    mention_for_handle,
)
from rootcoz_slack_digest.models import AppConfig, JobRow, RootcozConfig, SlackConfig
from rootcoz_slack_digest.rootcoz_client import RootcozClient
from rootcoz_slack_digest.slack_client import SlackClient
from rootcoz_slack_digest.slack_format import build_message
from rootcoz_slack_digest.week import last_complete_week, week_from_dates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DigestResult:
    """Outcome of a digest run."""

    payload: list[dict[str, object]] | str
    rows: list[JobRow]
    posted: bool

    @property
    def blocks(self) -> list[dict[str, object]]:
        """Block Kit payload when format=blocks; empty list otherwise."""
        if isinstance(self.payload, list):
            return self.payload
        return []


def apply_env_overrides(config: AppConfig) -> AppConfig:
    """Overlay standard env vars onto config (secrets + URLs)."""
    rootcoz = config.rootcoz.model_copy(
        update={
            "url": os.environ.get("ROOTCOZ_URL", config.rootcoz.url),
            "username": os.environ.get("ROOTCOZ_USERNAME", config.rootcoz.username),
            "api_key": os.environ.get("ROOTCOZ_API_KEY", config.rootcoz.api_key),
            "verify_ssl": _env_bool("ROOTCOZ_VERIFY_SSL", config.rootcoz.verify_ssl),
        }
    )
    slack = config.slack.model_copy(
        update={
            "webhook_url": os.environ.get("SLACK_WEBHOOK_URL", config.slack.webhook_url),
            "bot_token": os.environ.get("SLACK_BOT_TOKEN", config.slack.bot_token),
            "channel": os.environ.get("SLACK_CHANNEL", config.slack.channel),
        }
    )
    return config.model_copy(update={"rootcoz": rootcoz, "slack": slack})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def run_digest(
    config: AppConfig,
    *,
    dry_run: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    rows: list[JobRow] | None = None,
    usergroup_resolver: UsergroupResolver | None = None,
    rootcoz_client: RootcozClient | None = None,
    slack_client: SlackClient | None = None,
) -> DigestResult:
    """Query rootcoz API for the week, format the message, optionally post.

    When ``rows`` is provided, rootcoz is not contacted (tests / offline render).
    Message content always comes from API job rows — never from HTML report URLs.
    """
    cfg = apply_env_overrides(config)
    logger.info(
        "Digest schedule (CronJob must match): cron=%r timezone=%r",
        cfg.schedule.cron,
        cfg.schedule.timezone,
    )
    if date_from is not None and date_to is not None:
        window = week_from_dates(date_from, date_to)
    else:
        window = last_complete_week()

    own_rootcoz = False
    if rows is None:
        own_rootcoz = rootcoz_client is None
        client = rootcoz_client or RootcozClient(
            cfg.rootcoz,
            jenkins_base_url=os.environ.get("JENKINS_URL", ""),
        )
        try:
            if rootcoz_client is None:
                client.login()
            rows = client.fetch_job_rows(
                window,
                teams=cfg.digest.teams or None,
                tiers=cfg.digest.tiers or None,
            )
        finally:
            if own_rootcoz:
                client.close()

    mention = ""
    if cfg.message.include_mentions:
        mention = _resolve_primary_mention(cfg, usergroup_resolver)

    payload = build_message(
        window=window,
        rows=rows,
        max_rows=cfg.digest.max_rows,
        sort_by=cfg.digest.sort_by,
        columns=list(cfg.digest.columns),
        message=cfg.message,
        mention=mention,
    )

    if dry_run:
        logger.info("Dry-run: not posting to Slack (%d jobs from API)", len(rows))
        return DigestResult(payload=payload, rows=rows, posted=False)

    own_slack = slack_client is None
    sc = slack_client or SlackClient(cfg.slack)
    try:
        sc.post(payload)
    finally:
        if own_slack:
            sc.close()
    return DigestResult(payload=payload, rows=rows, posted=True)


def _resolve_primary_mention(
    cfg: AppConfig,
    resolver: UsergroupResolver | None,
) -> str:
    """Build a CC line from configured team usergroups."""
    handles = list(cfg.mentions.teams.values())
    if not handles:
        return ""

    own = False
    if resolver is None:
        if cfg.slack.bot_token:
            resolver = SlackUsergroupResolver(cfg.slack.bot_token)
            own = True
        else:
            logger.warning("No bot token; cannot resolve usergroup mentions — posting without CC")
            return ""

    try:
        parts = [mention_for_handle(resolver, h) for h in handles]
        return " ".join(p for p in parts if p)
    finally:
        if own and isinstance(resolver, SlackUsergroupResolver):
            resolver.close()


def render_payload(payload: list[dict[str, object]] | str) -> str:
    """Pretty-print payload for dry-run / render CLI."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, indent=2, sort_keys=False)


# Back-compat alias
def render_blocks_json(blocks: list[dict[str, object]]) -> str:
    """Pretty-print Block Kit JSON."""
    return render_payload(blocks)


__all__ = [
    "DigestResult",
    "RootcozConfig",
    "SlackConfig",
    "StaticUsergroupResolver",
    "apply_env_overrides",
    "render_blocks_json",
    "render_payload",
    "run_digest",
]
