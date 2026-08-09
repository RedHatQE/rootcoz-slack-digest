"""Format digest rows into Slack payloads from API data + config templates."""

from __future__ import annotations

from rootcoz_slack_digest.models import (
    DEFAULT_COLUMNS,
    DigestColumn,
    JobRow,
    MessageConfig,
    MessageFormat,
    SortBy,
    WeekWindow,
)


def sort_rows(rows: list[JobRow], sort_by: SortBy) -> list[JobRow]:
    """Return a new list sorted per ``sort_by``."""
    if sort_by is SortBy.FAILURES:
        return sorted(rows, key=lambda r: (-r.failure_count, r.job_name))
    if sort_by is SortBy.JOB_NAME:
        return sorted(rows, key=lambda r: r.job_name.lower())
    return sorted(rows, key=lambda r: (-r.not_reviewed, -r.failure_count, r.job_name))


def _link(label: str, url: str) -> str:
    if not url:
        return ""
    return f"<{url}|{label}>"


def _column_value(row: JobRow, column: DigestColumn, *, mrkdwn: bool) -> str:
    """Render one cell for a job row."""
    if column is DigestColumn.JOB_NAME:
        return row.job_name
    if column is DigestColumn.TIER:
        return row.tier
    if column is DigestColumn.TEAM:
        return row.team or "-"
    if column is DigestColumn.FAILURES:
        return str(row.failure_count)
    if column is DigestColumn.REVIEWED:
        return str(row.reviewed_count)
    if column is DigestColumn.NOT_REVIEWED:
        return str(row.not_reviewed)
    if column is DigestColumn.BUILD:
        return str(row.build_number) if row.build_number is not None else "-"
    if column is DigestColumn.JENKINS:
        if not row.jenkins_url:
            return "-"
        return _link("Jenkins", row.jenkins_url) if mrkdwn else row.jenkins_url
    if column is DigestColumn.ROOTCOZ:
        if not row.rootcoz_url:
            return "-"
        return _link("rootcoz", row.rootcoz_url) if mrkdwn else row.rootcoz_url
    return ""


_COLUMN_HEADERS: dict[DigestColumn, str] = {
    DigestColumn.JOB_NAME: "Job",
    DigestColumn.TIER: "Tier",
    DigestColumn.TEAM: "Team",
    DigestColumn.FAILURES: "Fail",
    DigestColumn.REVIEWED: "Rev",
    DigestColumn.NOT_REVIEWED: "Open",
    DigestColumn.BUILD: "Build",
    DigestColumn.JENKINS: "Jenkins",
    DigestColumn.ROOTCOZ: "rootcoz",
}


def _row_template_vars(row: JobRow) -> dict[str, str]:
    jenkins_link = _link("Jenkins", row.jenkins_url)
    rootcoz_link = _link("rootcoz", row.rootcoz_url)
    return {
        "job_id": row.job_id,
        "job_name": row.job_name,
        "tier": row.tier,
        "team": row.team or "-",
        "failures": str(row.failure_count),
        "reviewed": str(row.reviewed_count),
        "not_reviewed": str(row.not_reviewed),
        "build": str(row.build_number) if row.build_number is not None else "-",
        "jenkins_url": row.jenkins_url,
        "rootcoz_url": row.rootcoz_url,
        "jenkins_link": jenkins_link,
        "rootcoz_link": rootcoz_link,
        "jenkins_part": f" · {jenkins_link}" if jenkins_link else "",
        "rootcoz_part": f" · {rootcoz_link}" if rootcoz_link else "",
    }


def format_rows_text(
    rows: list[JobRow],
    columns: list[DigestColumn],
    message: MessageConfig,
    *,
    mrkdwn: bool,
) -> str:
    """Render job rows using columns and/or row_template."""
    if not rows:
        return (
            "_No completed jobs with failures in this window._"
            if mrkdwn
            else "No completed jobs with failures in this window."
        )

    # Prefer explicit column table when using blocks/mrkdwn defaults.
    if message.table_code_fence and columns:
        return _format_column_table(rows, columns, mrkdwn=mrkdwn)

    lines = [message.row_template.format(**_row_template_vars(row)) for row in rows]
    return "\n".join(lines)


def _format_column_table(
    rows: list[JobRow],
    columns: list[DigestColumn],
    *,
    mrkdwn: bool,
) -> str:
    """Build a simple aligned table; link columns listed after the fence when mrkdwn."""
    link_cols = {DigestColumn.JENKINS, DigestColumn.ROOTCOZ}
    text_cols = [c for c in columns if c not in link_cols]
    if not text_cols:
        text_cols = [c for c in columns]

    headers = [_COLUMN_HEADERS[c] for c in text_cols]
    widths = [max(len(h), 5) for h in headers]
    for row in rows:
        for i, col in enumerate(text_cols):
            widths[i] = max(widths[i], len(_column_value(row, col, mrkdwn=False)))

    def fmt_line(cells: list[str]) -> str:
        parts = [cell[: widths[i]].ljust(widths[i]) for i, cell in enumerate(cells)]
        return " ".join(parts)

    body_lines = [fmt_line(headers), fmt_line(["-" * w for w in widths])]
    for row in rows:
        body_lines.append(fmt_line([_column_value(row, c, mrkdwn=False) for c in text_cols]))

    if not mrkdwn:
        # Append raw URLs for link columns
        extra: list[str] = []
        for row in rows:
            bits = [row.job_name]
            for col in columns:
                if col in link_cols:
                    bits.append(_column_value(row, col, mrkdwn=False))
            extra.append(" | ".join(bits))
        return "\n".join(body_lines + extra)

    fenced = "```\n" + "\n".join(body_lines) + "\n```"
    link_lines: list[str] = []
    for row in rows:
        parts = [f"• *{row.job_name}*"]
        for col in columns:
            if col is DigestColumn.JENKINS and row.jenkins_url:
                parts.append(_link("Jenkins", row.jenkins_url))
            elif col is DigestColumn.ROOTCOZ and row.rootcoz_url:
                parts.append(_link("rootcoz", row.rootcoz_url))
        if len(parts) > 1:
            link_lines.append(" · ".join(parts))
    if link_lines:
        return fenced + "\n" + "\n".join(link_lines)
    return fenced


def build_message(
    *,
    window: WeekWindow,
    rows: list[JobRow],
    max_rows: int,
    sort_by: SortBy,
    columns: list[DigestColumn],
    message: MessageConfig,
    mention: str = "",
) -> list[dict[str, object]] | str:
    """Build Slack blocks or a single text body from rootcoz API rows.

    Returns Block Kit list for ``blocks`` format, otherwise a string.
    """
    ordered = sort_rows(rows, sort_by)
    total_failures = sum(r.failure_count for r in ordered)
    total_reviewed = sum(r.reviewed_count for r in ordered)
    total_jobs = len(ordered)
    shown = ordered[:max_rows]
    omitted = max(len(ordered) - len(shown), 0)

    mention_suffix = ""
    if message.include_mentions and mention:
        mention_suffix = f" — cc {mention}"

    header = message.header_template.format(
        week_label=window.label,
        mention_suffix=mention_suffix,
        mention=mention,
    )
    totals = message.totals_template.format(
        total_jobs=total_jobs,
        total_failures=total_failures,
        total_reviewed=total_reviewed,
        week_label=window.label,
    )
    mrkdwn = message.format is not MessageFormat.PLAIN
    body = format_rows_text(shown, columns, message, mrkdwn=mrkdwn)
    omitted_text = ""
    if omitted:
        omitted_text = message.omitted_template.format(omitted=omitted)

    if message.format is MessageFormat.BLOCKS:
        blocks: list[dict[str, object]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": totals}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
        ]
        if omitted_text:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": omitted_text}],
                }
            )
        return blocks

    parts = [header, totals, body]
    if omitted_text:
        parts.append(omitted_text)
    return "\n\n".join(parts)


# Back-compat name used by older call sites / tests
def build_blocks(
    *,
    window: WeekWindow,
    rows: list[JobRow],
    max_rows: int,
    sort_by: SortBy,
    mention: str = "",
    columns: list[DigestColumn] | None = None,
    message: MessageConfig | None = None,
) -> list[dict[str, object]]:
    """Build Block Kit only (forces ``message.format = blocks``)."""
    msg = message or MessageConfig()
    msg = msg.model_copy(update={"format": MessageFormat.BLOCKS})
    result = build_message(
        window=window,
        rows=rows,
        max_rows=max_rows,
        sort_by=sort_by,
        columns=columns or list(DEFAULT_COLUMNS),
        message=msg,
        mention=mention,
    )
    assert isinstance(result, list)
    return result


def blocks_to_fallback_text(blocks: list[dict[str, object]]) -> str:
    """Plain-text fallback for notifications / webhook top-level text."""
    parts: list[str] = []
    for block in blocks:
        text = block.get("text")
        if isinstance(text, dict) and "text" in text:
            parts.append(str(text["text"]))
    return "\n".join(parts) if parts else "rootcoz weekly digest"


def payload_fallback_text(payload: list[dict[str, object]] | str) -> str:
    """Fallback text for either blocks or string payloads."""
    if isinstance(payload, str):
        return payload
    return blocks_to_fallback_text(payload)
