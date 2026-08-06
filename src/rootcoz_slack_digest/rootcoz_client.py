"""HTTP client for rootcoz reports APIs."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rootcoz_slack_digest.links import jenkins_job_url, rootcoz_result_url
from rootcoz_slack_digest.models import JobRow, RootcozConfig, WeekWindow

logger = logging.getLogger(__name__)


class RootcozClient:
    """Authenticate and fetch weekly job totals from rootcoz."""

    def __init__(
        self,
        config: RootcozConfig,
        *,
        jenkins_base_url: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        if not config.url:
            msg = "rootcoz.url is required (or ROOTCOZ_URL)"
            raise ValueError(msg)
        self._config = config
        self._jenkins_base = jenkins_base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.url.rstrip("/"),
            verify=config.verify_ssl,
            timeout=60.0,
        )
        self._metadata_by_job: dict[str, dict[str, Any]] | None = None

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> RootcozClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def login(self) -> None:
        """Session-cookie login with username + API key."""
        if not self._config.username or not self._config.api_key:
            msg = "rootcoz.username and rootcoz.api_key (or env) are required"
            raise ValueError(msg)
        resp = self._client.post(
            "/api/auth/login",
            json={
                "username": self._config.username,
                "api_key": self._config.api_key,
            },
        )
        resp.raise_for_status()
        logger.info("Authenticated to rootcoz as %s", self._config.username)

    def fetch_job_rows(
        self,
        window: WeekWindow,
        *,
        teams: list[str] | None = None,
        tiers: list[str] | None = None,
    ) -> list[JobRow]:
        """Fetch completed-job totals for the week and map to JobRow."""
        params: dict[str, str] = {
            "from": window.date_from.isoformat(),
            "to": window.date_to.isoformat(),
            "status": "completed",
        }
        if teams:
            params["team"] = ",".join(teams)
        if tiers:
            params["tier"] = ",".join(tiers)

        resp = self._client.get("/api/reports/totals", params=params)
        resp.raise_for_status()
        payload = resp.json()
        jobs = payload.get("jobs") or []
        meta = self._job_metadata()
        rows: list[JobRow] = []
        for job in jobs:
            job_id = str(job.get("job_id") or "")
            job_name = str(job.get("job_name") or job_id)
            meta_row = meta.get(job_name, {})
            tier = str(meta_row.get("tier") or job.get("tier") or "other")
            team = str(meta_row.get("team") or job.get("team") or "")
            build_number = job.get("build_number")
            try:
                build_int = int(build_number) if build_number is not None else None
            except (TypeError, ValueError):
                build_int = None
            jenkins = str(job.get("jenkins_url") or "")
            if not jenkins and self._jenkins_base:
                jenkins = jenkins_job_url(self._jenkins_base, job_name, build_int)
            rows.append(
                JobRow(
                    job_id=job_id,
                    job_name=job_name,
                    tier=tier,
                    team=team,
                    failure_count=int(job.get("failure_count") or 0),
                    reviewed_count=int(job.get("reviewed_count") or 0),
                    jenkins_url=jenkins,
                    rootcoz_url=rootcoz_result_url(self._config.url, job_id),
                )
            )
        return rows

    def _job_metadata(self) -> dict[str, dict[str, Any]]:
        """Cache job_name → metadata from ``/api/jobs/metadata`` when available."""
        if self._metadata_by_job is not None:
            return self._metadata_by_job
        mapping: dict[str, dict[str, Any]] = {}
        try:
            resp = self._client.get("/api/jobs/metadata")
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    name = item.get("job_name") or item.get("name")
                    if name:
                        mapping[str(name)] = item
        except httpx.HTTPError:
            logger.warning("Could not load /api/jobs/metadata; tier/team may be empty")
        self._metadata_by_job = mapping
        return mapping
