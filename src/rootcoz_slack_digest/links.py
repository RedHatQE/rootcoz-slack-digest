"""URL builders for Jenkins and rootcoz result pages."""

from __future__ import annotations

from urllib.parse import quote


def rootcoz_result_url(base_url: str, job_id: str) -> str:
    """Link to a single rootcoz analysis result."""
    base = base_url.rstrip("/")
    return f"{base}/results/{quote(job_id, safe='')}"


def jenkins_job_url(jenkins_base: str, job_name: str, build_number: int | None) -> str:
    """Best-effort Jenkins job/build URL.

    ``job_name`` may contain folders (``folder/job``); path segments are quoted.
    """
    base = jenkins_base.rstrip("/")
    if not base or not job_name:
        return ""
    parts = [quote(p, safe="") for p in job_name.split("/") if p]
    path = "/job/" + "/job/".join(parts)
    if build_number and build_number > 0:
        return f"{base}{path}/{build_number}/"
    return f"{base}{path}/"
