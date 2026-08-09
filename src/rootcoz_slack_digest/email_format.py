"""Format digest as HTML email."""

from __future__ import annotations

import html

from rootcoz_slack_digest.models import JobRow, WeekWindow
from rootcoz_slack_digest.utils import version_sort_key


def format_digest_html(
    *,
    window: WeekWindow,
    rows: list[JobRow],
    team: str,
    tiers: list[str] | None = None,
) -> str:
    """Render digest rows as styled HTML email body."""
    total_failures = sum(r.failure_count for r in rows)
    total_reviewed = sum(r.reviewed_count for r in rows)
    tier_display = ", ".join(html.escape(t) for t in tiers) if tiers else "all"
    team_html = html.escape(team)

    groups: dict[str, list[JobRow]] = {}
    for row in rows:
        groups.setdefault(row.tier, []).append(row)
    tier_order = {t: i for i, t in enumerate(tiers)} if tiers else {}
    sorted_tiers = sorted(groups.keys(), key=lambda t: (tier_order.get(t, 99), t))

    html_parts = [
        "<html><body style='font-family: Arial, sans-serif; font-size: 14px;'>",
        f"<h2>rootcoz weekly digest — {html.escape(window.label)}</h2>",
        f"<p><strong>Team:</strong> {team_html} · "
        f"<strong>Tiers:</strong> {tier_display} · "
        f"<strong>Jobs:</strong> {len(rows)} · "
        f"<strong>Failures:</strong> {total_failures} · "
        f"<strong>Reviewed:</strong> {total_reviewed}/{total_failures}</p>",
        "<hr>",
    ]

    for tier in sorted_tiers:
        tier_rows = sorted(
            groups[tier],
            key=lambda r: (
                version_sort_key(r.version),
                version_sort_key(r.bundle.lstrip("v")),
                r.failure_count,
            ),
            reverse=True,
        )
        if len(sorted_tiers) > 1:
            html_parts.append(f"<h3>{html.escape(tier)}</h3>")
        html_parts.append("<ul>")
        for row in tier_rows:
            job_name = html.escape(row.job_name)
            if row.jenkins_url:
                name_html = f'<a href="{html.escape(row.jenkins_url, quote=True)}">{job_name}</a>'
            else:
                name_html = f"<strong>{job_name}</strong>"
            rootcoz_html = (
                f' · <a href="{html.escape(row.rootcoz_url, quote=True)}">rootcoz</a>'
                if row.rootcoz_url
                else ""
            )
            bundle_html = f" [{html.escape(row.bundle)}]" if row.bundle else ""
            html_parts.append(
                f"<li>{name_html}{bundle_html} "
                f"{row.reviewed_count}/{row.failure_count} reviewed"
                f"{rootcoz_html}</li>"
            )
        html_parts.append("</ul>")

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def format_celebration_html(
    *,
    window: WeekWindow,
    team: str,
    total_jobs: int,
    tiers: list[str] | None = None,
    jobs: list[JobRow] | None = None,
) -> str:
    """Render celebration message as HTML."""
    tier_display = ", ".join(html.escape(t) for t in tiers) if tiers else "all"
    team_html = html.escape(team)
    if total_jobs > 0:
        body = (
            f"All <strong>{total_jobs}</strong> {tier_display} failures "
            f"for <strong>{team_html}</strong> have been reviewed! 👏"
        )
    else:
        body = f"Zero {tier_display} failures for <strong>{team_html}</strong> this week! 🚀"

    parts = [
        "<html><body style='font-family: Arial, sans-serif;'>",
        f"<h2>🎉 rootcoz weekly digest — {html.escape(window.label)}</h2>",
        f"<p>✅ {body}</p>",
    ]
    if total_jobs > 0 and jobs:
        items: list[str] = []
        for job in jobs[:20]:
            bundle_html = f" [{html.escape(job.bundle)}]" if job.bundle else ""
            if job.rootcoz_url:
                items.append(
                    f'<li><a href="{html.escape(job.rootcoz_url, quote=True)}">'
                    f"{html.escape(job.job_name)}</a>{bundle_html}</li>"
                )
            else:
                items.append(f"<li>{html.escape(job.job_name)}{bundle_html}</li>")
        parts.append("<ul>" + "".join(items) + "</ul>")
        if len(jobs) > 20:
            parts.append(f"<p><em>+{len(jobs) - 20} more reviewed jobs</em></p>")
    parts.append("</body></html>")
    return "\n".join(parts)
