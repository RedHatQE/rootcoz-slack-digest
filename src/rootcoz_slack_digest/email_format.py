"""Format digest as HTML email."""

from __future__ import annotations

from rootcoz_slack_digest.models import JobRow, WeekWindow
from rootcoz_slack_digest.slack_format import _version_sort_key

_TIER_ORDER = {"gating": 0, "release-checklist": 1}


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
    tier_display = ", ".join(tiers) if tiers else "all"

    groups: dict[str, list[JobRow]] = {}
    for row in rows:
        groups.setdefault(row.tier, []).append(row)
    sorted_tiers = sorted(groups.keys(), key=lambda t: (_TIER_ORDER.get(t, 99), t))

    html_parts = [
        "<html><body style='font-family: Arial, sans-serif; font-size: 14px;'>",
        f"<h2>rootcoz weekly digest — {window.label}</h2>",
        f"<p><strong>Team:</strong> {team} · "
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
                _version_sort_key(r.version),
                _version_sort_key(r.bundle.lstrip("v")),
                r.failure_count,
            ),
            reverse=True,
        )
        html_parts.append(f"<h3>{tier}</h3>")
        html_parts.append("<ul>")
        for row in tier_rows:
            name_html = (
                f'<a href="{row.jenkins_url}">{row.job_name}</a>'
                if row.jenkins_url
                else f"<strong>{row.job_name}</strong>"
            )
            rootcoz_html = f' · <a href="{row.rootcoz_url}">rootcoz</a>' if row.rootcoz_url else ""
            bundle_html = f" [{row.bundle}]" if row.bundle else ""
            html_parts.append(
                f"<li>{name_html} — "
                f"{row.reviewed_count} / {row.failure_count} reviewed"
                f"{bundle_html}{rootcoz_html}</li>"
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
) -> str:
    """Render celebration message as HTML."""
    tier_display = ", ".join(tiers) if tiers else "all"
    if total_jobs > 0:
        body = (
            f"All <strong>{total_jobs}</strong> {tier_display} failures "
            f"for <strong>{team}</strong> have been reviewed! 👏"
        )
    else:
        body = f"Zero {tier_display} failures for <strong>{team}</strong> this week! 🚀"
    return (
        "<html><body style='font-family: Arial, sans-serif;'>"
        f"<h2>🎉 rootcoz weekly digest — {window.label}</h2>"
        f"<p>✅ {body}</p>"
        "</body></html>"
    )
