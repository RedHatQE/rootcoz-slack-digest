"""Reconcile Jenkins builds against rootcoz inventory; build fallback rows."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from rootcoz_slack_digest.jenkins_client import JenkinsBuildRef
from rootcoz_slack_digest.models import JobRow


def normalize_jenkins_url(url: str) -> str:
    """Normalize Jenkins URL for equality checks."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/")
    host = (parsed.hostname or "").lower()
    if not host:
        return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))
    try:
        port = parsed.port
    except ValueError:
        return ""
    scheme = (parsed.scheme or "https").lower()
    if port is None or (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        netloc = host
    else:
        netloc = f"{host}:{port}"
    return urlunparse((scheme, netloc, path, "", "", ""))


def rootcoz_inventory_keys(rows: list[JobRow]) -> set[tuple[str, int | str]]:
    """Keys used to detect Jenkins builds already present in rootcoz.

    Presence is global (not per-team): the same Jenkins job/build is unique, and
    a rootcoz row for any team means analysis landed. Team-scoping these keys
    would create false misses when metadata.team disagrees with Jenkins team_map.
    """
    keys: set[tuple[str, int | str]] = set()
    for row in rows:
        name = row.job_name.strip().lower()
        if name and row.build_number is not None:
            keys.add((name, row.build_number))
        norm = normalize_jenkins_url(row.jenkins_url)
        if norm:
            keys.add(("url", norm))
    return keys


def find_missing_builds(
    jenkins_builds: list[JenkinsBuildRef],
    rootcoz_rows: list[JobRow],
) -> list[JenkinsBuildRef]:
    """Return Jenkins builds not found in rootcoz inventory.

    When the Jenkins build has a URL, prefer normalized URL identity so two
    different URLs that share ``job_name``+``build_number`` cannot hide each
    other. If URL is absent from inventory, also accept a rootcoz row with the
    same name/number and **empty** ``jenkins_url`` (API often omits it).
    """
    known = rootcoz_inventory_keys(rootcoz_rows)
    name_keys_without_url: set[tuple[str, int | str]] = set()
    for row in rootcoz_rows:
        name = row.job_name.strip().lower()
        if not name or row.build_number is None:
            continue
        if not normalize_jenkins_url(row.jenkins_url):
            name_keys_without_url.add((name, row.build_number))
    missing: list[JenkinsBuildRef] = []
    for build in jenkins_builds:
        url_norm = normalize_jenkins_url(build.jenkins_url)
        name_key = (build.job_name.strip().lower(), build.build_number)
        if url_norm:
            if ("url", url_norm) in known:
                continue
            if name_key in name_keys_without_url:
                continue
            missing.append(build)
            continue
        if name_key in known:
            continue
        missing.append(build)
    return missing


def builds_for_team(builds: list[JenkinsBuildRef], team: str) -> list[JenkinsBuildRef]:
    """Filter builds whose mapped team slug matches ``team``."""
    return [b for b in builds if b.team == team]


def unmapped_builds(builds: list[JenkinsBuildRef]) -> list[JenkinsBuildRef]:
    """Builds with a display team that did not map to a TARGETS slug."""
    return [b for b in builds if b.team_display and not b.team]


def jenkins_build_to_job_row(
    build: JenkinsBuildRef,
    *,
    tier: str,
    rootcoz_missing: bool = False,
) -> JobRow:
    """Convert a Jenkins build into a digest row (review counts unknown)."""
    return JobRow(
        job_id=f"jenkins:{build.job_name}:{build.build_number}",
        job_name=build.job_name,
        tier=tier,
        team=build.team,
        failure_count=0,
        reviewed_count=0,
        build_number=build.build_number,
        jenkins_url=build.jenkins_url,
        rootcoz_url="" if rootcoz_missing else build.rootcoz_url,
        version=build.version,
        bundle=build.bundle,
        rootcoz_missing=rootcoz_missing,
    )
