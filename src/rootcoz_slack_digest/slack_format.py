"""Format digest rows into Slack Block Kit payloads."""

from __future__ import annotations

from rootcoz_slack_digest.models import JobRow, SortBy, WeekWindow


def sort_rows(rows: list[JobRow], sort_by: SortBy) -> list[JobRow]:
    """Return a new list sorted per ``sort_by``."""
    if sort_by is SortBy.FAILURES:
        return sorted(rows, key=lambda r: (-r.failure_count, r.job_name))
    if sort_by is SortBy.JOB_NAME:
        return sorted(rows, key=lambda r: r.job_name.lower())
    return sorted(rows, key=lambda r: (-r.not_reviewed, -r.failure_count, r.job_name))


def _link(label: str, url: str) -> str:
    if not url:
        return label
    return f"<{url}|{label}>"


def format_table_text(rows: list[JobRow]) -> str:
    """Monospace-ish table body for a section block."""
    if not rows:
        return "_No completed jobs with failures in this window._"
    lines = [
        "```",
        f"{'Job':<40} {'Tier':<18} {'Fail':>5} {'Rev':>5}  Links",
        "-" * 78,
    ]
    for row in rows:
        name = row.job_name if len(row.job_name) <= 40 else row.job_name[:37] + "..."
        jenkins = _link("jenkins", row.jenkins_url) if row.jenkins_url else "-"
        rootcoz = _link("rootcoz", row.rootcoz_url) if row.rootcoz_url else "-"
        # Links cannot live inside a code fence; keep fence for numbers only.
        lines.append(f"{name:<40} {row.tier:<18} {row.failure_count:>5} {row.reviewed_count:>5}")
        # Store link line outside fence — rebuilt below
        _ = (jenkins, rootcoz)
    lines.append("```")
    # Append clickable links after the fence
    link_lines: list[str] = []
    for row in rows:
        parts: list[str] = [f"• *{row.job_name}*"]
        if row.jenkins_url:
            parts.append(_link("Jenkins", row.jenkins_url))
        if row.rootcoz_url:
            parts.append(_link("rootcoz", row.rootcoz_url))
        link_lines.append(" · ".join(parts))
    return "\n".join(lines + link_lines)


def build_blocks(
    *,
    window: WeekWindow,
    rows: list[JobRow],
    max_rows: int,
    sort_by: SortBy,
    mention: str = "",
    summary_url: str = "",
) -> list[dict[str, object]]:
    """Build Slack Block Kit blocks for the weekly digest."""
    ordered = sort_rows(rows, sort_by)
    total_failures = sum(r.failure_count for r in ordered)
    total_reviewed = sum(r.reviewed_count for r in ordered)
    total_jobs = len(ordered)
    shown = ordered[:max_rows]
    omitted = max(len(ordered) - len(shown), 0)

    header = f"*rootcoz weekly digest* — {window.label}"
    if mention:
        header = f"{header} — cc {mention}"

    totals = f"Jobs: *{total_jobs}* · Failures: *{total_failures}* · Reviewed: *{total_reviewed}*"
    if summary_url:
        totals = f"{totals} · <{summary_url}|HTML summary>"

    blocks: list[dict[str, object]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": totals}},
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": format_table_text(shown)},
        },
    ]
    if omitted:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_+{omitted} more jobs not shown — open the HTML summary._",
                    }
                ],
            }
        )
    return blocks


def blocks_to_fallback_text(blocks: list[dict[str, object]]) -> str:
    """Plain-text fallback for notifications / webhook top-level text."""
    parts: list[str] = []
    for block in blocks:
        text = block.get("text")
        if isinstance(text, dict) and "text" in text:
            parts.append(str(text["text"]))
    return "\n".join(parts) if parts else "rootcoz weekly digest"
