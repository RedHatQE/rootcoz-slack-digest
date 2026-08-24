"""Jenkins miss-check / rootcoz-down Slack orchestration helpers."""

from __future__ import annotations

import logging

from rootcoz_slack_digest.digest_result import TargetResult
from rootcoz_slack_digest.jenkins_client import JenkinsBuildRef, JenkinsClient
from rootcoz_slack_digest.jenkins_miss_check import (
    builds_for_team,
    jenkins_build_to_job_row,
    unmapped_builds,
)
from rootcoz_slack_digest.mentions import UsergroupResolver, mention_for_handle
from rootcoz_slack_digest.models import AppConfig, JobRow, MessageFormat, Target, WeekWindow
from rootcoz_slack_digest.slack_format import (
    _safe_format,
    append_slack_comment,
    build_message,
    comment_rootcoz_down,
    format_unmapped_teams_text,
    sort_rows,
)

logger = logging.getLogger(__name__)


def scope_tier(cfg: AppConfig) -> str:
    """Display tier for Jenkins-sourced rows (first configured scope)."""
    scopes = cfg.jenkins.miss_check.scopes
    return scopes[0] if scopes else "gating"


def filter_rows(rows: list[JobRow], cfg: AppConfig) -> list[JobRow]:
    """Apply client-side exclude_job_patterns."""
    if not cfg.digest.exclude_job_patterns:
        return rows
    patterns = cfg.digest.exclude_job_patterns
    return [r for r in rows if not any(pat in r.job_name for pat in patterns)]


def fetch_jenkins_builds(
    cfg: AppConfig,
    window: WeekWindow,
    jenkins_client: JenkinsClient | None,
) -> list[JenkinsBuildRef] | None:
    """Fetch Jenkins builds for miss-check / fallback. ``None`` means Jenkins failed."""
    own = False
    client = jenkins_client
    try:
        if client is None:
            client = JenkinsClient(cfg.jenkins)
            own = True
        return client.fetch_builds_in_window(window)
    except Exception:
        logger.exception("Jenkins miss-check / fallback failed")
        return None
    finally:
        if own and client is not None:
            client.close()


def annotate_slack_with_misses(
    target_results: list[TargetResult],
    *,
    misses: list[JenkinsBuildRef],
    unmapped: list[JenkinsBuildRef],
    cfg: AppConfig,
    window: WeekWindow,
    resolver: UsergroupResolver | None,
) -> list[TargetResult]:
    """Merge per-team Jenkins misses into the main digest table (rootcoz=missing)."""
    mc = cfg.jenkins.miss_check
    if not mc.attach_to_slack:
        return target_results
    tier = scope_tier(cfg)
    unmapped_note = format_unmapped_teams_text([b.team_display for b in unmapped])
    updated: list[TargetResult] = []
    unmapped_attached = False
    for tr in target_results:
        if tr.target.slack is None:
            updated.append(tr)
            continue
        team_misses = builds_for_team(misses, tr.target.team)
        # Filter excluded patterns before capping so max_miss_rows applies to
        # rows that would actually be shown.
        miss_rows = filter_rows(
            [jenkins_build_to_job_row(b, tier=tier, rootcoz_missing=True) for b in team_misses],
            cfg,
        )[: mc.max_miss_rows]
        payload = tr.payload
        rows = tr.rows
        total_jobs = tr.total_jobs
        celebration_jobs = tr.celebration_jobs
        if miss_rows:
            # Keep rootcoz digest/celebration rows in the same table as misses.
            # Celebration targets have empty ``rows`` but populated ``celebration_jobs``.
            prior_rows = list(tr.rows)
            prior_celebration = list(tr.celebration_jobs)
            prior_total = tr.total_jobs
            base_rows = prior_rows if prior_rows else prior_celebration
            # Truncate base rows only so digest.max_rows cannot drop reserved misses.
            if cfg.digest.max_rows > 0:
                base_rows = sort_rows(base_rows, cfg.digest.sort_by)[: cfg.digest.max_rows]
            rows = [*base_rows, *miss_rows]
            usergroup = tr.target.slack.usergroup
            mention = ""
            if cfg.message.include_mentions and usergroup and resolver is not None:
                mention = mention_for_handle(resolver, usergroup)
            payload = build_message(
                window=window,
                rows=rows,
                max_rows=0,
                sort_by=cfg.digest.sort_by,
                columns=list(cfg.digest.columns),
                message=cfg.message,
                mention=mention,
                tiers=cfg.digest.tiers or None,
                excluded_versions=cfg.digest.exclude_versions or None,
            )
            # Preserve rootcoz email source-of-truth (misses are Slack-only).
            if prior_rows:
                total_jobs = len(rows)
                celebration_jobs = []
            else:
                total_jobs = prior_total
                celebration_jobs = prior_celebration
        if unmapped_note and not unmapped_attached:
            payload = append_slack_comment(payload, unmapped_note)
            unmapped_attached = True
        updated.append(
            TargetResult(
                target=tr.target,
                payload=payload,
                rows=rows,
                total_jobs=total_jobs,
                celebration_jobs=celebration_jobs,
            )
        )
    return updated


def annotate_slack_comment(
    target_results: list[TargetResult],
    text: str,
) -> list[TargetResult]:
    """Append the same comment to every Slack target payload."""
    updated: list[TargetResult] = []
    for tr in target_results:
        if tr.target.slack is None:
            updated.append(tr)
            continue
        updated.append(
            TargetResult(
                target=tr.target,
                payload=append_slack_comment(tr.payload, text),
                rows=tr.rows,
                total_jobs=tr.total_jobs,
                celebration_jobs=tr.celebration_jobs,
            )
        )
    return updated


def build_jenkins_fallback_targets(
    *,
    cfg: AppConfig,
    window: WeekWindow,
    targets: list[Target],
    builds: list[JenkinsBuildRef],
    resolver: UsergroupResolver | None,
) -> tuple[list[TargetResult], list[JobRow]]:
    """Per-team digests from Jenkins when rootcoz is down."""
    tier = scope_tier(cfg)
    all_rows: list[JobRow] = []
    results: list[TargetResult] = []
    unmapped_note = format_unmapped_teams_text([b.team_display for b in unmapped_builds(builds)])
    for target in targets:
        team_builds = builds_for_team(builds, target.team)
        rows = [
            jenkins_build_to_job_row(
                b,
                tier=tier,
                rootcoz_missing=not b.rootcoz_url,
            )
            for b in team_builds
        ]
        rows = filter_rows(rows, cfg)
        all_rows.extend(rows)
        usergroup = target.slack.usergroup if target.slack is not None else ""
        mention = ""
        if cfg.message.include_mentions and usergroup and resolver is not None:
            mention = mention_for_handle(resolver, usergroup)
        if rows:
            payload = build_message(
                window=window,
                rows=rows,
                max_rows=cfg.digest.max_rows,
                sort_by=cfg.digest.sort_by,
                columns=list(cfg.digest.columns),
                message=cfg.message,
                mention=mention,
                tiers=cfg.jenkins.miss_check.scopes or None,
                excluded_versions=cfg.digest.exclude_versions or None,
            )
        else:
            mention_suffix = f" — {mention}" if mention else ""
            tier_display = (
                ", ".join(cfg.jenkins.miss_check.scopes)
                if cfg.jenkins.miss_check.scopes
                else "gating"
            )
            text = _safe_format(
                cfg.message.celebration_no_failures_template,
                "celebration_no_failures",
                week_label=window.label,
                mention_suffix=mention_suffix,
                mention=mention,
                team=target.team,
                total_jobs="0",
                lanes=tier_display,
                excluded_versions="",
            )
            if cfg.message.format is MessageFormat.BLOCKS:
                payload = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
            else:
                payload = text
        payload = append_slack_comment(payload, comment_rootcoz_down(cfg.jenkins.miss_check.scopes))
        if unmapped_note and target.slack is not None:
            payload = append_slack_comment(payload, unmapped_note)
            unmapped_note = ""  # only first Slack target
        results.append(
            TargetResult(
                target=target,
                payload=payload,
                rows=rows,
                total_jobs=len(rows),
            )
        )
    return results, all_rows
