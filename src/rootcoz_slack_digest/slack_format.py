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
        "version": row.version,
        "bundle": row.bundle,
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


def _version_sort_key(version: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple. Handles v4.22.6.rhel9-9."""
    if not version:
        return (0,)
    cleaned = version.lstrip("v")
    parts: list[int] = []
    for part in cleaned.split("."):
        # Handle parts like "rhel9-9" by extracting leading digits
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        try:
            parts.append(int(digits) if digits else 0)
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _format_grouped_by_tier(rows: list[JobRow]) -> str:
    """Format rows grouped by tier with inline mrkdwn links.

    Order: gating → release-checklist → other tiers alphabetically.
    Within each tier, sorted by bundle descending, then failure_count descending.
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
        tier_rows = sorted(
            groups[tier],
            key=lambda r: (
                _version_sort_key(r.version),
                _version_sort_key(r.bundle.lstrip("v")),
                r.failure_count,
            ),
            reverse=True,
        )
        lines = [f"*{tier}*"] if len(sorted_tiers) > 1 else []
        for row in tier_rows:
            if row.jenkins_url:
                name_part = _link(row.job_name, row.jenkins_url)
            else:
                name_part = f"*{row.job_name}*"

            bundle_part = f" [{row.bundle}]" if row.bundle else ""
            reviewed = f"{row.reviewed_count}/{row.failure_count} reviewed"
            parts = [f"• {name_part}{bundle_part} {reviewed}"]
            if row.rootcoz_url:
                parts.append(_link("rootcoz", row.rootcoz_url))

            lines.append(" · ".join(parts))
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _link_cell(url: str, text: str) -> dict[str, object]:
    """Build a rich_text table cell with a single link."""
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_section",
                "elements": [{"type": "link", "url": url, "text": text}],
            }
        ],
    }


def _build_table_blocks(
    rows: list[JobRow],
    tiers: list[str] | None = None,
    *,
    total_jobs: int = 0,
    total_reviewed: int = 0,
    total_failures: int = 0,
) -> list[dict[str, object]]:
    """Build Slack table blocks grouped by tier with links."""
    groups: dict[str, list[JobRow]] = {}
    for row in rows:
        groups.setdefault(row.tier, []).append(row)

    sorted_tiers = sorted(
        groups.keys(),
        key=lambda t: (_TIER_ORDER.get(t, 99), t),
    )

    blocks: list[dict[str, object]] = []
    show_tier_header = len(sorted_tiers) > 1

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

        if show_tier_header:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{tier}*"},
                }
            )

        header_row: list[dict[str, object]] = [
            {"type": "raw_text", "text": f"Jobs ({total_jobs})"},
            {"type": "raw_text", "text": "Bundle"},
            {"type": "raw_text", "text": f"Reviewed ({total_reviewed}/{total_failures})"},
            {"type": "raw_text", "text": "rootcoz"},
        ]

        data_rows: list[list[dict[str, object]]] = []
        for row in tier_rows:
            if row.jenkins_url:
                job_cell: dict[str, object] = _link_cell(row.jenkins_url, row.job_name)
            else:
                job_cell = {"type": "raw_text", "text": row.job_name}

            bundle_cell: dict[str, object] = {
                "type": "raw_text",
                "text": row.bundle or "-",
            }
            reviewed_cell: dict[str, object] = {
                "type": "raw_text",
                "text": f"{row.reviewed_count}/{row.failure_count}",
            }
            if row.rootcoz_url:
                rootcoz_cell: dict[str, object] = _link_cell(row.rootcoz_url, "view")
            else:
                rootcoz_cell = {"type": "raw_text", "text": "-"}

            data_rows.append([job_cell, bundle_cell, reviewed_cell, rootcoz_cell])

        table_block: dict[str, object] = {
            "type": "table",
            "column_settings": [
                {"is_wrapped": True},  # Job — wrap long names
                {},  # Bundle
                {"align": "right"},  # Reviewed — right-aligned
                {},  # rootcoz
            ],
            "rows": [header_row] + data_rows,
        }
        blocks.append(table_block)

    return blocks


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


def build_message(
    *,
    window: WeekWindow,
    rows: list[JobRow],
    max_rows: int,
    sort_by: SortBy,
    columns: list[DigestColumn],
    message: MessageConfig,
    mention: str = "",
    tiers: list[str] | None = None,
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
        mention_suffix = f" — {mention}"

    lanes = ", ".join(tiers) if tiers else ""
    header = _safe_format(
        message.header_template,
        "header",
        week_label=window.label,
        mention_suffix=mention_suffix,
        mention=mention,
        lanes=lanes,
    )
    totals = _safe_format(
        message.totals_template,
        "totals",
        total_jobs=total_jobs,
        total_failures=total_failures,
        total_reviewed=total_reviewed,
        week_label=window.label,
    )
    omitted_text = ""
    if omitted:
        omitted_text = _safe_format(message.omitted_template, "omitted", omitted=omitted)

    if message.format is MessageFormat.BLOCKS:
        table_blocks = _build_table_blocks(
            shown,
            tiers,
            total_jobs=total_jobs,
            total_reviewed=total_reviewed,
            total_failures=total_failures,
        )

        blocks: list[dict[str, object]] = []

        # Mention in context block (mrkdwn) so <!subteam^...> renders
        if message.include_mentions and mention:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": mention}],
                }
            )

        blocks.extend(table_blocks)

        if omitted_text:
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": omitted_text}],
                }
            )
        return blocks

    mrkdwn = message.format is not MessageFormat.PLAIN
    body = format_rows_text(shown, columns, message, mrkdwn=mrkdwn)
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
    tiers: list[str] | None = None,
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
        tiers=tiers,
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
        caption = block.get("caption")
        if isinstance(caption, str) and caption.strip():
            parts.append(caption)
        elements = block.get("elements")
        if isinstance(elements, list):
            for el in elements:
                if isinstance(el, dict) and "text" in el:
                    parts.append(str(el["text"]))
    return "\n".join(parts) if parts else "rootcoz weekly digest"


def payload_fallback_text(payload: list[dict[str, object]] | str) -> str:
    """Fallback text for either blocks or string payloads."""
    if isinstance(payload, str):
        return payload
    return blocks_to_fallback_text(payload)
