"""Digest run result types shared by service and Jenkins Slack paths."""

from __future__ import annotations

from dataclasses import dataclass, field

from rootcoz_slack_digest.models import JobRow, Target


@dataclass(frozen=True)
class TargetResult:
    """Result for one target."""

    target: Target
    payload: list[dict[str, object]] | str
    rows: list[JobRow]
    total_jobs: int = 0
    celebration_jobs: list[JobRow] = field(default_factory=list)


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
        """First target blocks when payload is Block Kit."""
        payload = self.payload
        if isinstance(payload, list):
            return payload
        return []
