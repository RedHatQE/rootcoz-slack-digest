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
    DigestColumn.TIER: "Lane",
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
        "created_at": row.created_at,
        "date": row.created_at[:10] if row.created_at else "",
    }


def format_rows_text(
    rows: list[JobRow],
    columns: list[DigestColumn],
    message: MessageConfig,
    *,
    mrkdwn: bool,
) -> str:
    """Render job rows grouped by tier with inline links (mrkdwn) or as a table."""
    if not rows:
        return (
            "_No completed jobs with failures in this window._"
            if mrkdwn
            else "No completed jobs with failures in this window."
        )

    if mrkdwn:
        return _format_grouped_by_tier(rows)

    # Plain/non-mrkdwn: keep the column table
    if message.table_code_fence and columns:
        return _format_column_table(rows, columns, mrkdwn=False)

    lines = [_safe_format(message.row_template, "row", **_row_template_vars(row)) for row in rows]
    return "\n".join(lines)


# Tier display order: gating first, then release-checklist, then everything else
_TIER_ORDER = {"gating": 0, "release-checklist": 1}


def _format_grouped_by_tier(rows: list[JobRow]) -> str:
    """Format rows grouped by tier with inline mrkdwn links.

    Order: gating → release-checklist → other tiers alphabetically.
    Within each tier, sorted by failure_count descending.
    """
    groups: dict[str, list[JobRow]] = {}
    for row in rows:
        groups.setdefault(row.tier, []).append(row)

    sorted_tiers = sorted(
        groups.keys(),
        key=lambda t: (_TIER_ORDER.get(t, 99), t),
    )

    sections: list[str] = []
    for tier in sorted_tiers:
        tier_rows = sorted(groups[tier], key=lambda r: -r.failure_count)
        lines = [f"*{tier}*"]
        for row in tier_rows:
            if row.jenkins_url:
                name_part = _link(row.job_name, row.jenkins_url)
            else:
                name_part = f"*{row.job_name}*"

            date_str = row.created_at[:10] if row.created_at else ""
            date_part = f" · {date_str}" if date_str else ""
            stats = f"fail {row.failure_count} / rev {row.reviewed_count}{date_part}"
            parts = [f"• {name_part} — {stats}"]
            if row.rootcoz_url:
                parts.append(_link("rootcoz", row.rootcoz_url))

            lines.append(" · ".join(parts))
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _format_column_table(
    rows: list[JobRow],
    columns: list[DigestColumn],
    *,
    mrkdwn: bool,
) -> str:
    """Build a simple aligned table for plain (non-mrkdwn) output."""
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
        # Append raw URLs for link columns (only if any link columns selected)
        link_selected = [col for col in columns if col in link_cols]
        if link_selected:
            extra: list[str] = []
            for row in rows:
                bits = [row.job_name]
                for col in columns:
                    if col in link_cols:
                        bits.append(_column_value(row, col, mrkdwn=False))
                extra.append(" | ".join(bits))
            return "\n".join(body_lines + extra)
        return "\n".join(body_lines)

    fenced = "```\n" + "\n".join(body_lines) + "\n```"
    return fenced


def _safe_format(template: str, template_name: str, **kwargs: object) -> str:
    """Format a template string with clear error on unknown placeholders."""
    try:
        return template.format(**kwargs)
    except KeyError as exc:
        allowed = ", ".join(sorted(str(k) for k in kwargs))
        msg = f"{template_name} template has unknown placeholder {exc}; allowed: {allowed}"
        raise ValueError(msg) from exc


def _split_blocks(
    text: str, block_type: str = "section", max_chars: int = 2900
) -> list[dict[str, object]]:
    """Split long text into multiple Slack blocks at tier-group boundaries."""
    if len(text) <= max_chars:
        return [{"type": block_type, "text": {"type": "mrkdwn", "text": text}}]

    # Prefer splitting between tier groups (double-newline separated)
    if "\n\n" in text:
        groups = text.split("\n\n")
        blocks: list[dict[str, object]] = []
        chunk_parts: list[str] = []
        chunk_len = 0

        for group in groups:
            if len(group) > max_chars:
                if chunk_parts:
                    blocks.append(
                        {
                            "type": block_type,
                            "text": {"type": "mrkdwn", "text": "\n\n".join(chunk_parts)},
                        }
                    )
                    chunk_parts = []
                    chunk_len = 0
                blocks.extend(_split_by_lines(group, block_type, max_chars))
                continue

            sep = 2 if chunk_parts else 0
            if chunk_parts and chunk_len + sep + len(group) > max_chars:
                blocks.append(
                    {
                        "type": block_type,
                        "text": {"type": "mrkdwn", "text": "\n\n".join(chunk_parts)},
                    }
                )
                chunk_parts = [group]
                chunk_len = len(group)
            else:
                chunk_len += sep + len(group)
                chunk_parts.append(group)

        if chunk_parts:
            blocks.append(
                {
                    "type": block_type,
                    "text": {"type": "mrkdwn", "text": "\n\n".join(chunk_parts)},
                }
            )
        return blocks

    return _split_by_lines(text, block_type, max_chars)


def _split_by_lines(text: str, block_type: str, max_chars: int) -> list[dict[str, object]]:
    """Split text by line boundaries."""
    if len(text) <= max_chars:
        return [{"type": block_type, "text": {"type": "mrkdwn", "text": text}}]

    blocks: list[dict[str, object]] = []
    lines = text.split("\n")
    chunk: list[str] = []
    chunk_len = 0

    for line in lines:
        line_len = len(line) + 1
        if chunk and chunk_len + line_len > max_chars:
            blocks.append(
                {
                    "type": block_type,
                    "text": {"type": "mrkdwn", "text": "\n".join(chunk)},
                }
            )
            chunk = []
            chunk_len = 0
        chunk.append(line)
        chunk_len += line_len

    if chunk:
        blocks.append(
            {
                "type": block_type,
                "text": {"type": "mrkdwn", "text": "\n".join(chunk)},
            }
        )

    return blocks


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
    shown = ordered[:max_rows] if max_rows > 0 else ordered
    omitted = max(len(ordered) - len(shown), 0)

    mention_suffix = ""
    if message.include_mentions and mention:
        mention_suffix = f" — cc {mention}"

    header = _safe_format(
        message.header_template,
        "header",
        week_label=window.label,
        mention_suffix=mention_suffix,
        mention=mention,
    )
    totals = _safe_format(
        message.totals_template,
        "totals",
        total_jobs=total_jobs,
        total_failures=total_failures,
        total_reviewed=total_reviewed,
        week_label=window.label,
    )
    mrkdwn = message.format is not MessageFormat.PLAIN
    body = format_rows_text(shown, columns, message, mrkdwn=mrkdwn)
    omitted_text = ""
    if omitted:
        omitted_text = _safe_format(message.omitted_template, "omitted", omitted=omitted)

    if message.format is MessageFormat.BLOCKS:
        blocks: list[dict[str, object]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": totals}},
            {"type": "divider"},
            *_split_blocks(body),
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
