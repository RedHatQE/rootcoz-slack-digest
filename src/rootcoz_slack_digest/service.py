"""Orchestrate week → rootcoz API → format → Slack / email."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date

from pydantic import ValidationError

from rootcoz_slack_digest.email_client import EmailClient
from rootcoz_slack_digest.email_format import format_celebration_html, format_digest_html
from rootcoz_slack_digest.mentions import (
    SlackUsergroupResolver,
    StaticUsergroupResolver,
    UsergroupResolver,
    mention_for_handle,
)
from rootcoz_slack_digest.models import (
    AppConfig,
    JobRow,
    MessageFormat,
    RootcozConfig,
    SlackConfig,
    Target,
)
from rootcoz_slack_digest.rootcoz_client import RootcozClient
from rootcoz_slack_digest.slack_client import SlackClient
from rootcoz_slack_digest.slack_format import build_message
from rootcoz_slack_digest.week import last_complete_week, week_from_dates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TargetResult:
    """Result for one target."""

    target: Target
    payload: list[dict[str, object]] | str
    rows: list[JobRow]
    total_jobs: int = 0


@dataclass(frozen=True)
class DigestResult:
    """Outcome of a digest run."""

    target_results: list[TargetResult]
    all_rows: list[JobRow]
    posted: bool

    @property
    def payload(self) -> list[dict[str, object]] | str:
        """First target payload for backward compat."""
        if self.target_results:
            return self.target_results[0].payload
        return []

    @property
    def rows(self) -> list[JobRow]:
        """First target rows for backward compat."""
        if self.target_results:
            return self.target_results[0].rows
        return self.all_rows

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
            "url": os.environ.get("ROOTCOZ_URL", config.rootcoz.url).strip(),
            "api_key": os.environ.get("ROOTCOZ_API_KEY", config.rootcoz.api_key).strip(),
            "verify_ssl": _env_bool("ROOTCOZ_VERIFY_SSL", config.rootcoz.verify_ssl),
        }
    )
    slack = config.slack.model_copy(
        update={
            "webhook_url": os.environ.get("SLACK_WEBHOOK_URL", config.slack.webhook_url).strip(),
            "bot_token": os.environ.get("SLACK_BOT_TOKEN", config.slack.bot_token).strip(),
        }
    )
    return config.model_copy(update={"rootcoz": rootcoz, "slack": slack})


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_targets() -> list[Target]:
    """Parse ``TARGETS`` JSON env into routing entries."""
    raw = os.environ.get("TARGETS", "")
    if not raw:
        return []
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"TARGETS is not valid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(entries, list):
        msg = "TARGETS must be a JSON array of {team, slack?, email?} objects"
        raise ValueError(msg)
    try:
        return [Target.model_validate(e) for e in entries]
    except ValidationError as exc:
        msg = f"TARGETS entry validation failed: {exc}"
        raise ValueError(msg) from exc


def _target_label(target: Target) -> str:
    """Human-readable target id for logs."""
    if target.slack is not None:
        return target.slack.channel
    if target.email is not None:
        return ",".join(target.email.recipients)
    return target.team


def run_digest(
    config: AppConfig,
    *,
    dry_run: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
    rows: list[JobRow] | None = None,
    targets: list[Target] | None = None,
    usergroup_resolver: UsergroupResolver | None = None,
    rootcoz_client: RootcozClient | None = None,
    slack_client: SlackClient | None = None,
    email_client: EmailClient | None = None,
) -> DigestResult:
    """Query rootcoz API for the week, format the message, optionally post.

    When ``rows`` is provided, rootcoz is not contacted (tests / offline render).
    Message content always comes from API job rows — never from HTML report URLs.
    Each ``Target`` gets a team-filtered digest delivered via Slack and/or email.
    Live runs fetch once per target with server-side team/label filters.
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

    resolved_targets = targets if targets is not None else _load_targets()
    if not resolved_targets:
        if dry_run:
            logger.warning("No TARGETS configured; nothing to render")
            return DigestResult(target_results=[], all_rows=rows or [], posted=False)
        msg = "No TARGETS configured; cannot post digest"
        raise ValueError(msg)

    slack_target_count = sum(1 for t in resolved_targets if t.slack is not None)
    if cfg.slack.mode == "webhook" and slack_target_count > 1:
        msg = (
            "webhook mode does not support per-target channel routing; use mode='bot' with TARGETS"
        )
        raise ValueError(msg)

    own_resolver = False
    resolver = usergroup_resolver
    needs_mentions = cfg.message.include_mentions and any(
        t.slack is not None and t.slack.usergroup for t in resolved_targets
    )
    if needs_mentions and resolver is None:
        if cfg.slack.bot_token:
            resolver = SlackUsergroupResolver(cfg.slack.bot_token)
            own_resolver = True
        else:
            logger.warning("No bot token; cannot resolve usergroup mentions — posting without CC")

    own_rootcoz = False
    client: RootcozClient | None = None
    if rows is None:
        own_rootcoz = rootcoz_client is None
        client = rootcoz_client or RootcozClient(cfg.rootcoz)

    all_rows: list[JobRow] = []
    target_results: list[TargetResult] = []
    # default_tier is a display catch-all, not a real rootcoz label
    default_tier = cfg.rootcoz.tier_labels.default_tier
    api_labels = [t for t in cfg.digest.tiers if t != default_tier] if cfg.digest.tiers else None
    try:
        for target in resolved_targets:
            if rows is None:
                assert client is not None
                target_rows = client.fetch_job_rows(
                    window,
                    team=target.team,
                    labels=api_labels or None,
                    exclude_labels=cfg.digest.exclude_labels or None,
                )
                if cfg.digest.exclude_job_patterns:
                    patterns = cfg.digest.exclude_job_patterns
                    target_rows = [
                        r for r in target_rows if not any(pat in r.job_name for pat in patterns)
                    ]
            else:
                # Test / offline mode: filter injected rows by team
                target_rows = [r for r in rows if r.team == target.team]
            all_rows.extend(target_rows)
            logger.info(
                "Target %s: %d rows for team %r",
                _target_label(target),
                len(target_rows),
                target.team,
            )
            usergroup = target.slack.usergroup if target.slack is not None else ""
            if not target_rows:
                # Check if there were failures that are all reviewed
                total_jobs = 0
                if rows is None:  # Only query API if not in test mode
                    assert client is not None
                    total_jobs = client.count_all_jobs(
                        window,
                        team=target.team,
                        labels=api_labels or None,
                        exclude_labels=cfg.digest.exclude_labels or None,
                    )

                mention = ""
                if cfg.message.include_mentions and usergroup and resolver is not None:
                    mention = mention_for_handle(resolver, usergroup)
                mention_suffix = f" — {mention}" if mention else ""

                tier_display = ", ".join(cfg.digest.tiers) if cfg.digest.tiers else "all tiers"
                template_vars = {
                    "week_label": window.label,
                    "mention_suffix": mention_suffix,
                    "mention": mention,
                    "team": target.team,
                    "total_jobs": str(total_jobs),
                    "lanes": tier_display,
                }

                if total_jobs > 0:
                    celebrate_text = cfg.message.celebration_reviewed_template.format(
                        **template_vars
                    )
                else:
                    celebrate_text = cfg.message.celebration_no_failures_template.format(
                        **template_vars
                    )

                if cfg.message.format is MessageFormat.BLOCKS:
                    celebrate_payload: list[dict[str, object]] | str = [
                        {"type": "section", "text": {"type": "mrkdwn", "text": celebrate_text}},
                    ]
                else:
                    celebrate_payload = celebrate_text
                target_results.append(
                    TargetResult(
                        target=target,
                        payload=celebrate_payload,
                        rows=[],
                        total_jobs=total_jobs,
                    )
                )
                logger.info(
                    "Target %s: %s for team %r (total_jobs=%d)",
                    _target_label(target),
                    "all reviewed" if total_jobs > 0 else "no failures",
                    target.team,
                    total_jobs,
                )
                continue
            mention = ""
            if cfg.message.include_mentions and usergroup and resolver is not None:
                mention = mention_for_handle(resolver, usergroup)
            payload = build_message(
                window=window,
                rows=target_rows,
                max_rows=cfg.digest.max_rows,
                sort_by=cfg.digest.sort_by,
                columns=list(cfg.digest.columns),
                message=cfg.message,
                mention=mention,
                tiers=cfg.digest.tiers or None,
            )
            target_results.append(
                TargetResult(
                    target=target,
                    payload=payload,
                    rows=target_rows,
                    total_jobs=len(target_rows),
                )
            )
    finally:
        if own_rootcoz and client is not None:
            client.close()
        if own_resolver and isinstance(resolver, SlackUsergroupResolver):
            resolver.close()

    if not target_results:
        if not all_rows:
            # Quiet week — no failures to report. Successful no-op.
            logger.info("No failures in window — nothing to post")
            return DigestResult(target_results=[], all_rows=all_rows, posted=False)
        if dry_run:
            logger.warning("All targets filtered out — no rows matched any team")
            return DigestResult(target_results=[], all_rows=all_rows, posted=False)
        msg = "No target digests generated — no rows matched any TARGETS team"
        raise ValueError(msg)

    if dry_run:
        logger.info(
            "Dry-run: not posting (%d jobs, %d targets)",
            len(all_rows),
            len(target_results),
        )
        return DigestResult(
            target_results=target_results,
            all_rows=all_rows,
            posted=False,
        )

    posted_any = False
    slack_results = [tr for tr in target_results if tr.target.slack is not None]
    if slack_results:
        own_slack = slack_client is None
        sc = slack_client or SlackClient(cfg.slack)
        try:
            for tr in slack_results:
                assert tr.target.slack is not None
                logger.info(
                    "Posting digest to channel %s (team %s)",
                    tr.target.slack.channel,
                    tr.target.team,
                )
                try:
                    sc.post(tr.payload, channel=tr.target.slack.channel)
                    posted_any = True
                except Exception as exc:
                    msg = (
                        f"Failed to post digest for team {tr.target.team!r} "
                        f"to channel {tr.target.slack.channel!r}: {exc}"
                    )
                    raise RuntimeError(msg) from exc
        finally:
            if own_slack:
                sc.close()

    if cfg.email.enabled:
        ec = email_client or EmailClient(cfg.email)
        tiers = cfg.digest.tiers or None
        for tr in target_results:
            if tr.target.email is None:
                continue
            tier_display = ", ".join(cfg.digest.tiers) if cfg.digest.tiers else "all"
            subject = cfg.message.email_subject_template.format(
                week_label=window.label,
                team=tr.target.team,
                lanes=tier_display,
            )
            if tr.rows:
                html = format_digest_html(
                    window=window,
                    rows=tr.rows,
                    team=tr.target.team,
                    tiers=tiers,
                )
            else:
                html = format_celebration_html(
                    window=window,
                    team=tr.target.team,
                    total_jobs=tr.total_jobs,
                    tiers=tiers,
                )
            logger.info(
                "Sending digest email for team %s to %s",
                tr.target.team,
                ", ".join(tr.target.email.recipients),
            )
            try:
                ec.send(
                    recipients=tr.target.email.recipients,
                    cc=tr.target.email.cc,
                    subject=subject,
                    html_body=html,
                )
                posted_any = True
            except Exception as exc:
                msg = (
                    f"Failed to send digest email for team {tr.target.team!r} "
                    f"to {tr.target.email.recipients!r}: {exc}"
                )
                raise RuntimeError(msg) from exc

    return DigestResult(
        target_results=target_results,
        all_rows=all_rows,
        posted=posted_any,
    )


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
    "Target",
    "TargetResult",
    "apply_env_overrides",
    "render_blocks_json",
    "render_payload",
    "run_digest",
]
