"""Orchestrate week → rootcoz API → format → Slack / email."""

from __future__ import annotations

import json
import logging
import os
from datetime import date

import httpx
from pydantic import ValidationError

from rootcoz_slack_digest.digest_result import DigestResult, TargetResult
from rootcoz_slack_digest.email_client import EmailClient
from rootcoz_slack_digest.email_format import format_celebration_html, format_digest_html
from rootcoz_slack_digest.jenkins_client import JenkinsClient
from rootcoz_slack_digest.jenkins_digest import (
    annotate_slack_comment,
    annotate_slack_with_misses,
    build_jenkins_fallback_targets,
    fetch_jenkins_builds,
    filter_rows,
)
from rootcoz_slack_digest.jenkins_miss_check import find_missing_builds, unmapped_builds
from rootcoz_slack_digest.mentions import (
    SlackUsergroupResolver,
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
    WeekWindow,
)
from rootcoz_slack_digest.rootcoz_client import RootcozClient
from rootcoz_slack_digest.slack_client import SlackClient
from rootcoz_slack_digest.slack_format import (
    COMMENT_BOTH_DOWN,
    COMMENT_JENKINS_DOWN,
    _link,
    _safe_format,
    both_down_payload,
    build_message,
)
from rootcoz_slack_digest.week import last_complete_week, week_from_dates

logger = logging.getLogger(__name__)


def apply_env_overrides(config: AppConfig) -> AppConfig:
    """Overlay standard env vars onto config (secrets + URLs)."""
    from urllib.parse import urlparse

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
    miss = config.jenkins.miss_check
    allowed_hosts = list(miss.allowed_rootcoz_hosts)
    if not allowed_hosts and rootcoz.url:
        parsed = urlparse(rootcoz.url)
        host = (parsed.hostname or "").strip()
        if host:
            try:
                port = parsed.port
            except ValueError:
                port = None
            scheme = (parsed.scheme or "https").lower()
            if port is not None and not (
                (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
            ):
                allowed_hosts = [f"{host}:{port}"]
            else:
                allowed_hosts = [host]
    miss = miss.model_copy(update={"allowed_rootcoz_hosts": allowed_hosts})
    jenkins = config.jenkins.model_copy(
        update={
            "url": os.environ.get("JENKINS_URL", config.jenkins.url).strip(),
            "user": os.environ.get("JENKINS_USER", config.jenkins.user).strip(),
            "token": os.environ.get("JENKINS_TOKEN", config.jenkins.token).strip(),
            "verify_ssl": _env_bool("JENKINS_VERIFY_SSL", config.jenkins.verify_ssl),
            "miss_check": miss,
        }
    )
    return config.model_copy(update={"rootcoz": rootcoz, "slack": slack, "jenkins": jenkins})


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
    jenkins_client: JenkinsClient | None = None,
    slack_client: SlackClient | None = None,
    email_client: EmailClient | None = None,
) -> DigestResult:
    """Query rootcoz API for the week, format the message, optionally post.

    When ``rows`` is provided, rootcoz is not contacted (tests / offline render).
    Message content always comes from API job rows — never from HTML report URLs.
    Each ``Target`` gets a team-filtered digest delivered via Slack and/or email.
    Live runs fetch once per target with server-side team/label filters.

    When ``jenkins.miss_check`` is enabled, Slack payloads may gain a miss section
    or down-path comments. Credentials and hosts come from env / config only.
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
        window = last_complete_week(week_start=cfg.schedule.week_start)

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

    email_only_targets = [t for t in resolved_targets if t.email and not t.slack]
    if email_only_targets and not cfg.email.enabled:
        names = ", ".join(t.team for t in email_only_targets)
        msg = f"Targets [{names}] have email delivery only but email.enabled is false"
        raise ValueError(msg)

    own_resolver = False
    resolver = usergroup_resolver
    needs_mentions = cfg.message.include_mentions and any(
        t.slack is not None and t.slack.usergroup for t in resolved_targets
    )
    if needs_mentions and resolver is None:
        if cfg.slack.bot_token:
            resolver = SlackUsergroupResolver(
                cfg.slack.bot_token,
                api_base_url=cfg.slack.api_base_url,
                timeout=cfg.slack.timeout,
            )
            own_resolver = True
        else:
            logger.warning("No bot token; cannot resolve usergroup mentions — posting without CC")

    miss_cfg = cfg.jenkins.miss_check
    use_jenkins = miss_cfg.enabled and rows is None

    all_rows: list[JobRow] = []
    target_results: list[TargetResult] = []
    # default_tier is a display catch-all, not a real rootcoz label
    default_tier = cfg.rootcoz.tier_labels.default_tier
    api_labels = [t for t in cfg.digest.tiers if t != default_tier] if cfg.digest.tiers else None
    rootcoz_failed = False

    own_rootcoz = False
    client: RootcozClient | None = None
    try:
        if rows is not None:
            for target in resolved_targets:
                target_rows = [r for r in rows if r.team == target.team]
                all_rows.extend(target_rows)
                target_results.extend(
                    _target_results_for_rows(
                        cfg=cfg,
                        window=window,
                        target=target,
                        target_rows=target_rows,
                        resolver=resolver,
                        client=None,
                        api_labels=api_labels,
                        injected_mode=True,
                    )
                )
        else:
            own_rootcoz = rootcoz_client is None
            client = rootcoz_client or RootcozClient(cfg.rootcoz)
            for target in resolved_targets:
                try:
                    target_rows = client.fetch_job_rows(
                        window,
                        team=target.team,
                        labels=api_labels or None,
                        exclude_labels=cfg.digest.exclude_labels or None,
                        exclude_versions=cfg.digest.exclude_versions or None,
                        include_tags=cfg.digest.include_tags or None,
                    )
                except httpx.HTTPError:
                    if use_jenkins and miss_cfg.fallback_when_rootcoz_down:
                        # Deterministic fallback for ALL targets — do not publish
                        # a partial rootcoz digests set that silently omits teams.
                        rootcoz_failed = True
                        logger.exception(
                            "rootcoz fetch failed for team %r; "
                            "switching all targets to Jenkins fallback",
                            target.team,
                        )
                        target_results = []
                        all_rows = []
                        break
                    raise
                target_rows = filter_rows(target_rows, cfg)
                all_rows.extend(target_rows)
                logger.info(
                    "Target %s: %d rows for team %r",
                    _target_label(target),
                    len(target_rows),
                    target.team,
                )
                try:
                    trs = _target_results_for_rows(
                        cfg=cfg,
                        window=window,
                        target=target,
                        target_rows=target_rows,
                        resolver=resolver,
                        client=client,
                        api_labels=api_labels,
                        injected_mode=False,
                    )
                except httpx.HTTPError:
                    if use_jenkins and miss_cfg.fallback_when_rootcoz_down:
                        # Celebration path calls fetch_all_jobs; treat that like
                        # fetch_job_rows failure so we do not abort the run.
                        rootcoz_failed = True
                        logger.exception(
                            "rootcoz fetch failed during target render for team %r; "
                            "switching all targets to Jenkins fallback",
                            target.team,
                        )
                        target_results = []
                        all_rows = []
                        break
                    raise
                target_results.extend(trs)

        if rootcoz_failed:
            builds = fetch_jenkins_builds(cfg, window, jenkins_client)
            if builds is None:
                for target in resolved_targets:
                    mention = ""
                    usergroup = target.slack.usergroup if target.slack is not None else ""
                    if cfg.message.include_mentions and usergroup and resolver is not None:
                        mention = mention_for_handle(resolver, usergroup)
                    mention_suffix = f" — {mention}" if mention else ""
                    payload: list[dict[str, object]] | str
                    if cfg.message.format is MessageFormat.BLOCKS:
                        payload = both_down_payload(
                            week_label=window.label,
                            mention_suffix=mention_suffix,
                        )
                    else:
                        payload = (
                            f"*rootcoz weekly digest* — {window.label}{mention_suffix}\n\n"
                            f"{COMMENT_BOTH_DOWN}"
                        )
                    target_results.append(
                        TargetResult(target=target, payload=payload, rows=[], total_jobs=0)
                    )
            else:
                target_results, all_rows = build_jenkins_fallback_targets(
                    cfg=cfg,
                    window=window,
                    targets=resolved_targets,
                    builds=builds,
                    resolver=resolver,
                )
        elif use_jenkins and miss_cfg.attach_to_slack:
            # Full inventory (reviewed + unreviewed) so reviewed jobs are not
            # false-positive misses. Skip miss-check if inventory cannot be loaded.
            inventory_rows: list[JobRow] = []
            inventory_ok = False
            if client is not None:
                try:
                    # Presence inventory must not apply digest display filters
                    # (exclude_versions / exclude_labels / include_tags) or jobs
                    # that exist in rootcoz are false-positive misses.
                    inventory_rows = client.fetch_all_jobs(
                        window,
                        labels=miss_cfg.scopes or None,
                    )
                    inventory_ok = True
                except Exception:
                    logger.exception("rootcoz inventory fetch for miss-check failed")
            if not inventory_ok:
                target_results = annotate_slack_comment(
                    target_results,
                    "_⚠️ Jenkins miss-check skipped (rootcoz inventory unavailable)._",
                )
            else:
                builds = fetch_jenkins_builds(cfg, window, jenkins_client)
                if builds is None:
                    target_results = annotate_slack_comment(
                        target_results,
                        COMMENT_JENKINS_DOWN,
                    )
                else:
                    target_teams = {t.team for t in resolved_targets}
                    scoped = [b for b in builds if (not b.team) or b.team in target_teams]
                    misses = find_missing_builds(scoped, inventory_rows)
                    unmapped = unmapped_builds(builds)
                    target_results = annotate_slack_with_misses(
                        target_results,
                        misses=misses,
                        unmapped=unmapped,
                        cfg=cfg,
                        window=window,
                        resolver=resolver,
                    )
                    all_rows = [row for tr in target_results for row in tr.rows]
    finally:
        if own_rootcoz and client is not None:
            client.close()
        if own_resolver and isinstance(resolver, SlackUsergroupResolver):
            resolver.close()

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

    if cfg.email.enabled and not rootcoz_failed:
        ec = email_client or EmailClient(cfg.email)
        tiers = cfg.digest.tiers or None
        for tr in target_results:
            if tr.target.email is None:
                continue
            tier_display = ", ".join(cfg.digest.tiers) if cfg.digest.tiers else "all"
            subject = _safe_format(
                cfg.message.email_subject_template,
                "email_subject",
                week_label=window.label,
                team=tr.target.team,
                lanes=tier_display,
            )
            if tr.rows:
                # Miss-check rows are Slack-only; never include in email digests.
                email_rows = [r for r in tr.rows if not r.rootcoz_missing]
                if tr.celebration_jobs:
                    # All-reviewed rootcoz outcome — keep celebration email even if
                    # Slack merged celebration rows into the miss table.
                    html = format_celebration_html(
                        window=window,
                        team=tr.target.team,
                        total_jobs=tr.total_jobs,
                        tiers=tiers,
                        jobs=tr.celebration_jobs,
                        message=cfg.message,
                    )
                elif email_rows:
                    html = format_digest_html(
                        window=window,
                        rows=email_rows,
                        team=tr.target.team,
                        tiers=tiers,
                        message=cfg.message,
                    )
                else:
                    # Miss-only Slack table: still send rootcoz empty/celebration outcome.
                    html = format_celebration_html(
                        window=window,
                        team=tr.target.team,
                        total_jobs=tr.total_jobs,
                        tiers=tiers,
                        jobs=tr.celebration_jobs,
                        message=cfg.message,
                    )
            else:
                html = format_celebration_html(
                    window=window,
                    team=tr.target.team,
                    total_jobs=tr.total_jobs,
                    tiers=tiers,
                    jobs=tr.celebration_jobs,
                    message=cfg.message,
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


def _target_results_for_rows(
    *,
    cfg: AppConfig,
    window: WeekWindow,
    target: Target,
    target_rows: list[JobRow],
    resolver: UsergroupResolver | None,
    client: RootcozClient | None,
    api_labels: list[str] | None,
    injected_mode: bool,
) -> list[TargetResult]:
    """Build one TargetResult (digest or celebration) for a team."""
    usergroup = target.slack.usergroup if target.slack is not None else ""
    if not target_rows:
        all_jobs: list[JobRow] = []
        if not injected_mode and client is not None:
            all_jobs = client.fetch_all_jobs(
                window,
                team=target.team,
                labels=api_labels or None,
                exclude_labels=cfg.digest.exclude_labels or None,
                exclude_versions=cfg.digest.exclude_versions or None,
                include_tags=cfg.digest.include_tags or None,
            )
            all_jobs = filter_rows(all_jobs, cfg)
        total_jobs = len(all_jobs)

        mention = ""
        if cfg.message.include_mentions and usergroup and resolver is not None:
            mention = mention_for_handle(resolver, usergroup)
        mention_suffix = f" — {mention}" if mention else ""

        tier_display = ", ".join(cfg.digest.tiers) if cfg.digest.tiers else "all tiers"
        excl_display = (
            f" (excl. {', '.join(cfg.digest.exclude_versions)})"
            if cfg.digest.exclude_versions
            else ""
        )
        template_vars = {
            "week_label": window.label,
            "mention_suffix": mention_suffix,
            "mention": mention,
            "team": target.team,
            "total_jobs": str(total_jobs),
            "lanes": tier_display,
            "excluded_versions": excl_display,
        }

        if total_jobs > 0:
            celebrate_text = _safe_format(
                cfg.message.celebration_reviewed_template,
                "celebration_reviewed",
                **template_vars,
            )
            max_links = cfg.message.celebration_max_links
            shown_jobs = all_jobs[:max_links]
            link_lines: list[str] = []
            for job in shown_jobs:
                bundle_part = f" [{job.bundle}]" if job.bundle else ""
                if job.rootcoz_url:
                    link_lines.append(f"• {_link(job.job_name, job.rootcoz_url)}{bundle_part}")
                else:
                    safe_name = job.job_name.replace("|", "/").replace("<", "").replace(">", "")
                    link_lines.append(f"• {safe_name}{bundle_part}")
            if link_lines:
                celebrate_text += "\n" + "\n".join(link_lines)
            if len(all_jobs) > max_links:
                celebrate_text += "\n" + _safe_format(
                    cfg.message.celebration_more_template,
                    "celebration_more",
                    remaining=len(all_jobs) - max_links,
                )
        else:
            celebrate_text = _safe_format(
                cfg.message.celebration_no_failures_template,
                "celebration_no_failures",
                **template_vars,
            )

        if cfg.message.format is MessageFormat.BLOCKS:
            celebrate_payload: list[dict[str, object]] | str = [
                {"type": "section", "text": {"type": "mrkdwn", "text": celebrate_text}},
            ]
        else:
            celebrate_payload = celebrate_text
        logger.info(
            "Target %s: %s for team %r (total_jobs=%d)",
            _target_label(target),
            "all reviewed" if total_jobs > 0 else "no failures",
            target.team,
            total_jobs,
        )
        return [
            TargetResult(
                target=target,
                payload=celebrate_payload,
                rows=[],
                total_jobs=total_jobs,
                celebration_jobs=all_jobs if total_jobs > 0 else [],
            )
        ]

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
        excluded_versions=cfg.digest.exclude_versions or None,
    )
    return [
        TargetResult(
            target=target,
            payload=payload,
            rows=target_rows,
            total_jobs=len(target_rows),
        )
    ]


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
    "Target",
    "TargetResult",
    "apply_env_overrides",
    "render_blocks_json",
    "render_payload",
    "run_digest",
]
