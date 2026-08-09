"""Test doubles for digest orchestration and mentions."""

from __future__ import annotations

from rootcoz_slack_digest.models import JobRow, WeekWindow


class StaticUsergroupResolver:
    """Test/double resolver with a fixed handle → id map."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = {k.lstrip("@"): v for k, v in mapping.items()}

    def resolve(self, handle: str) -> str | None:
        """Return usergroup id for handle, or None."""
        return self._mapping.get(handle.lstrip("@"))


class FakeRootcozClient:
    """In-memory rootcoz client for celebration / empty-unreviewed paths."""

    def __init__(
        self,
        *,
        unreviewed: list[JobRow] | None = None,
        all_jobs: list[JobRow] | None = None,
    ) -> None:
        self.unreviewed = unreviewed or []
        self.all_jobs = all_jobs or []

    def fetch_job_rows(
        self,
        window: WeekWindow,
        *,
        team: str = "",
        labels: list[str] | None = None,
        exclude_labels: list[str] | None = None,
    ) -> list[JobRow]:
        del window, labels, exclude_labels
        return [r for r in self.unreviewed if not team or r.team == team]

    def fetch_all_jobs(
        self,
        window: WeekWindow,
        *,
        team: str = "",
        labels: list[str] | None = None,
        exclude_labels: list[str] | None = None,
    ) -> list[JobRow]:
        del window, labels, exclude_labels
        return [r for r in self.all_jobs if not team or r.team == team]

    def close(self) -> None:
        """No-op for protocol compatibility."""
