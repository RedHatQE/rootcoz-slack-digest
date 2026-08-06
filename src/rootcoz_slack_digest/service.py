"""Orchestrate week → rootcoz → format → Slack."""

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
from rootcoz_slack_digest.slack_format import build_blocks
from rootcoz_slack_digest.week import last_complete_week, week_from_dates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DigestResult:
    """Outcome of a digest run."""

    blocks: list[dict[str, object]]
    rows: list[JobRow]
    posted: bool


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
    """Build (and optionally post) the weekly digest.

    When ``rows`` is provided, rootcoz is not contacted (tests / offline render).
    """
    cfg = apply_env_overrides(config)
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

    mention = _resolve_primary_mention(cfg, usergroup_resolver)
    blocks = build_blocks(
        window=window,
        rows=rows,
        max_rows=cfg.digest.max_rows,
        sort_by=cfg.digest.sort_by,
        mention=mention,
        summary_url=cfg.digest.rootcause_summary_url,
    )

    if dry_run:
        logger.info("Dry-run: not posting to Slack (%d jobs)", len(rows))
        return DigestResult(blocks=blocks, rows=rows, posted=False)

    own_slack = slack_client is None
    sc = slack_client or SlackClient(cfg.slack)
    try:
        sc.post_blocks(blocks)
    finally:
        if own_slack:
            sc.close()
    return DigestResult(blocks=blocks, rows=rows, posted=True)


def _resolve_primary_mention(
    cfg: AppConfig,
    resolver: UsergroupResolver | None,
) -> str:
    """Build a single CC line from configured team usergroups.

    Mentions every configured team handle that resolves. Empty if none.
    """
    handles = list(cfg.mentions.teams.values())
    if not handles:
        return ""

    own = False
    if resolver is None:
        if cfg.slack.bot_token:
            resolver = SlackUsergroupResolver(cfg.slack.bot_token)
            own = True
        else:
            # Webhook mode cannot resolve usergroups; skip pings.
            logger.warning("No bot token; cannot resolve usergroup mentions — posting without CC")
            return ""

    try:
        parts = [mention_for_handle(resolver, h) for h in handles]
        return " ".join(p for p in parts if p)
    finally:
        if own and isinstance(resolver, SlackUsergroupResolver):
            resolver.close()


def render_blocks_json(blocks: list[dict[str, object]]) -> str:
    """Pretty-print blocks for dry-run / render CLI."""
    return json.dumps(blocks, indent=2, sort_keys=False)


# Re-export for tests / typing convenience
__all__ = [
    "DigestResult",
    "RootcozConfig",
    "SlackConfig",
    "StaticUsergroupResolver",
    "apply_env_overrides",
    "render_blocks_json",
    "run_digest",
]
