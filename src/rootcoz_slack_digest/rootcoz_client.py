"""HTTP client for rootcoz reports APIs."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rootcoz_slack_digest.field_resolver import extract_tier, resolve_path, resolve_template
from rootcoz_slack_digest.models import JobRow, RootcozConfig, WeekWindow

logger = logging.getLogger(__name__)


class RootcozClient:
    """Authenticate and fetch job data from rootcoz."""

    def __init__(
        self,
        config: RootcozConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not config.url:
            msg = "rootcoz.url is required (or ROOTCOZ_URL)"
            raise ValueError(msg)
        if not config.api_key:
            msg = "rootcoz.api_key is required (or ROOTCOZ_API_KEY)"
            raise ValueError(msg)
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.api_key}"},
            verify=config.verify_ssl,
            timeout=60.0,
        )

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> RootcozClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_job_rows(
        self,
        window: WeekWindow,
        *,
        exclude_tags: list[str] | None = None,
        exclude_labels: list[str] | None = None,
        exclude_job_patterns: list[str] | None = None,
    ) -> list[JobRow]:
        """Fetch jobs using configured endpoint, params, and field mapping."""
        fm = self._config.field_map
        params = dict(self._config.params)
        params["from"] = window.date_from.isoformat()
        params["to"] = window.date_to.isoformat()

        resp = self._client.get(self._config.endpoint, params=params)
        resp.raise_for_status()
        payload: Any = resp.json()
        if not isinstance(payload, list):
            payload = payload.get("jobs") or payload.get("results") or []

        config_vars = {"url": self._config.url.rstrip("/")}
        rows: list[JobRow] = []
        for job in payload:
            if not isinstance(job, dict):
                continue
            job_id = str(resolve_path(job, fm.job_id) or "")
            job_name = str(resolve_path(job, fm.job_name) or job_id)
            team = str(resolve_path(job, fm.team) or "")

            tier_raw = resolve_path(job, fm.tier)
            tier = extract_tier(tier_raw, self._config.tier_labels.labels)

            build_raw = resolve_path(job, fm.build)
            try:
                build_int = int(build_raw) if build_raw is not None else None
            except (TypeError, ValueError):
                build_int = None

            failures = int(resolve_path(job, fm.failures) or 0)
            reviewed = int(resolve_path(job, fm.reviewed) or 0)
            created_at = str(resolve_path(job, fm.created_at) or "")

            resolved_fields = {
                "job_id": job_id,
                "job_name": job_name,
                "build": str(build_int or ""),
            }

            if "{" in fm.jenkins:
                jenkins_url = resolve_template(fm.jenkins, resolved_fields, config_vars)
            else:
                jenkins_url = str(resolve_path(job, fm.jenkins) or "")

            if "{" in fm.rootcoz:
                rootcoz_url = resolve_template(fm.rootcoz, resolved_fields, config_vars)
            else:
                rootcoz_url = str(resolve_path(job, fm.rootcoz) or "")

            # Check job name exclusions
            if exclude_job_patterns and any(pat in job_name for pat in exclude_job_patterns):
                continue

            metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
            job_tags = [str(t) for t in (job.get("tags") or [])]
            job_labels = [str(lb) for lb in (metadata.get("labels") or [])]

            if exclude_tags and any(pat in tag for pat in exclude_tags for tag in job_tags):
                continue
            if exclude_labels and any(
                pat in label for pat in exclude_labels for label in job_labels
            ):
                continue

            rows.append(
                JobRow(
                    job_id=job_id,
                    job_name=job_name,
                    tier=tier,
                    team=team,
                    failure_count=failures,
                    reviewed_count=reviewed,
                    build_number=build_int,
                    jenkins_url=jenkins_url,
                    rootcoz_url=rootcoz_url,
                    created_at=created_at,
                )
            )
        logger.info("Fetched %d jobs from rootcoz (%s)", len(rows), self._config.endpoint)
        return rows
