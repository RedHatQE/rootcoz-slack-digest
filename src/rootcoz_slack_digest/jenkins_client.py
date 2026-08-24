"""HTTP client for Jenkins view / job / build APIs (miss-check + fallback)."""

from __future__ import annotations

import json
import logging
import posixpath
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict

from rootcoz_slack_digest.models import JenkinsConfig, WeekWindow

logger = logging.getLogger(__name__)


class JenkinsBuildRef(BaseModel):
    """One Jenkins build considered for digest reconciliation."""

    model_config = ConfigDict(frozen=True)

    job_name: str
    build_number: int
    jenkins_url: str
    result: str
    timestamp_ms: int
    team_display: str = ""
    team: str = ""
    rootcoz_url: str = ""
    version: str = ""
    bundle: str = ""
    labels: tuple[str, ...] = ()


def map_jenkins_team(team_display: str, team_map: dict[str, str]) -> str:
    """Map Jenkins JOB_METADATA.team display name → rootcoz/TARGETS slug.

    Only explicit ``team_map`` keys are accepted — slug passthrough via map
    values is rejected so a job cannot self-assign another team's TARGETS slug.
    """
    if not team_display:
        return ""
    mapped = team_map.get(team_display, "")
    return mapped.strip() if mapped else ""


def _canonical_host(url_or_host: str) -> str:
    """Hostname with default ports omitted for allowlist matching.

    Bare ``host`` / ``host:port`` entries are scheme-agnostic: ports 80 and 443
    are stripped so ``rootcoz.example:80`` matches ``http://rootcoz.example/...``.
    Full URLs keep scheme-aware defaults (http/80, https/443).
    """
    raw = url_or_host.strip()
    if not raw:
        return ""
    if "://" not in raw:
        host_port = raw.split("/", 1)[0]
        if host_port.startswith("[") and "]" in host_port:
            # Rare IPv6 literal; keep bracketed host, optional :port after ].
            bracket, _, rest = host_port.partition("]")
            host = f"{bracket}]".lower()
            if rest.startswith(":") and rest[1:].isdigit():
                port = int(rest[1:])
                if port in (80, 443):
                    return host
                return f"{host}:{port}"
            return host if not rest else ""
        if host_port.count(":") == 1:
            host, port_s = host_port.rsplit(":", 1)
            if port_s.isdigit():
                port = int(port_s)
                host = host.lower()
                if port in (80, 443):
                    return host
                return f"{host}:{port}"
        return host_port.lower()
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if not host:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    scheme = (parsed.scheme or "https").lower()
    if port is None or (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        return host
    return f"{host}:{port}"


def extract_rootcoz_url(
    text: str,
    pattern: str,
    *,
    allowed_hosts: list[str] | None = None,
) -> str:
    """Return first rootcoz ``/results/`` URL in text, or empty.

    When ``allowed_hosts`` is provided:
    - empty list → deny all (fail closed)
    - non-empty → only matching hosts (default ports ignored) are accepted
    When ``allowed_hosts`` is ``None``, host filtering is skipped (unit tests).
    """
    if not text or not pattern:
        return ""
    if allowed_hosts is not None and not allowed_hosts:
        return ""
    try:
        match = re.search(pattern, text)
    except re.error:
        logger.warning("Invalid jenkins.miss_check.rootcoz_link_regex")
        return ""
    if not match:
        return ""
    url = match.group(0).rstrip(").,;\"'")
    parsed_url = urlparse(url)
    if parsed_url.username is not None or parsed_url.password is not None:
        return ""
    if allowed_hosts is not None:
        key = _canonical_host(url)
        allowed = {_canonical_host(h) for h in allowed_hosts if h}
        if not key or key not in allowed:
            return ""
    return url


def _effective_port(parsed: object) -> int:
    port = getattr(parsed, "port", None)
    if port is not None:
        return int(port)
    return 443 if str(getattr(parsed, "scheme", "")).lower() == "https" else 80


def _same_origin(base_url: str, candidate: str) -> bool:
    """True when candidate shares scheme+host+effective port with base_url."""
    base = urlparse(base_url)
    other = urlparse(candidate)
    if not base.scheme or not base.hostname or not other.scheme or not other.hostname:
        return False
    if base.scheme.lower() != other.scheme.lower():
        return False
    if base.hostname.lower() != other.hostname.lower():
        return False
    return _effective_port(base) == _effective_port(other)


def _path_segments_unsafe(path: str) -> bool:
    """True when path has ``.`` / ``..`` or encoded slash tricks."""
    for seg in path.split("/"):
        if not seg:
            continue
        decoded = unquote(unquote(seg)).strip()
        if decoded in {".", ".."}:
            return True
        if "/" in decoded or "\\" in decoded:
            return True
    return False


def _normalize_url_path(path: str) -> str | None:
    """Return posix-normalized path, or None if unsafe."""
    if _path_segments_unsafe(path):
        return None
    # Decode once more for normpath of remaining encodings, then re-check.
    decoded = unquote(path)
    if _path_segments_unsafe(decoded):
        return None
    normalized = posixpath.normpath(decoded or "/")
    if normalized != "/" and _path_segments_unsafe(normalized):
        return None
    if ".." in normalized.split("/"):
        return None
    return normalized


def _relative_api_path_from_urls(base_url: str, resource_url: str) -> str | None:
    """Return API path under Jenkins base, or None if off-host/off-prefix."""
    if not _same_origin(base_url, resource_url):
        return None
    base_parsed = urlparse(base_url)
    resource = urlparse(resource_url)
    base_norm = _normalize_url_path(base_parsed.path or "/")
    res_norm = _normalize_url_path(resource.path or "/")
    if base_norm is None or res_norm is None:
        return None
    base_path = base_norm.rstrip("/")
    res_path = res_norm.rstrip("/") if res_norm != "/" else ""
    if base_path:
        if not (res_path == base_path or res_path.startswith(base_path + "/")):
            return None
        path = res_path[len(base_path) :] + "/api/json"
    else:
        path = res_path + "/api/json"
    if not path.startswith("/"):
        path = "/" + path
    if _path_segments_unsafe(path) or _normalize_url_path(path) is None:
        return None
    return path.lstrip("/")


def _parse_job_metadata(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class JenkinsClient:
    """Authenticate and list failed builds from a Jenkins view."""

    def __init__(
        self,
        config: JenkinsConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        if not config.url:
            msg = "jenkins.url is required (or JENKINS_URL)"
            raise ValueError(msg)
        if not config.user or not config.token:
            msg = "jenkins.user and jenkins.token are required (or JENKINS_USER / JENKINS_TOKEN)"
            raise ValueError(msg)
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.url.rstrip("/") + "/",
            auth=(config.user, config.token),
            verify=config.verify_ssl,
            timeout=float(config.timeout),
        )

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> JenkinsClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _view_api_path(self) -> str:
        view = self._config.miss_check.view_path.strip()
        if not view.startswith("/"):
            view = "/" + view
        if not view.endswith("/"):
            view += "/"
        if _path_segments_unsafe(view) or _normalize_url_path(view) is None:
            msg = "jenkins.miss_check.view_path contains unsafe path segments"
            raise ValueError(msg)
        parts = [quote(p, safe="%") for p in view.strip("/").split("/") if p]
        return "/".join(parts) + "/api/json"

    def _relative_api_path(self, resource_url: str) -> str | None:
        """Return path under configured Jenkins base, or None if off-host."""
        path = _relative_api_path_from_urls(str(self._client.base_url), resource_url)
        if path is None:
            logger.warning("Ignoring off-base Jenkins URL (same-origin required)")
        return path

    def list_view_jobs(self) -> list[dict[str, str]]:
        """Return ``{name, url}`` entries from the configured view."""
        path = self._view_api_path()
        resp = self._client.get(path, params={"tree": "jobs[name,url]"})
        resp.raise_for_status()
        payload = resp.json()
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            return []
        out: list[dict[str, str]] = []
        base = str(self._client.base_url)
        for job in jobs:
            if not isinstance(job, dict):
                continue
            name = str(job.get("name") or "")
            url = str(job.get("url") or "")
            if name and url and _same_origin(base, url):
                out.append({"name": name, "url": url})
            elif name and url:
                logger.warning("Skipping view job with off-base URL: %s", name)
        return out

    def _metadata_from_params(
        self,
        params: list[Any],
        *,
        team_display: str,
        version: str,
        labels: tuple[str, ...],
        bundle: str,
    ) -> tuple[str, str, tuple[str, ...], str]:
        mc = self._config.miss_check
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "")
            value = param.get("value")
            if name == mc.bundle_param and value is not None and str(value).strip():
                bundle = str(value).strip()
                continue
            if name != mc.job_metadata_param:
                continue
            meta = _parse_job_metadata(value)
            team_display = str(meta.get("team") or team_display)
            version = str(meta.get("version") or version)
            raw_labels = meta.get("labels")
            if isinstance(raw_labels, list):
                labels = tuple(str(x) for x in raw_labels if x is not None and str(x).strip())
        return team_display, version, labels, bundle

    def _read_job_defaults(self, job_url: str) -> tuple[str, str, tuple[str, ...], str, str]:
        """Return (team, version, labels, bundle, rootcoz_url) from job defaults."""
        mc = self._config.miss_check
        path = self._relative_api_path(job_url)
        if path is None:
            return "", "", (), "", ""
        resp = self._client.get(
            path,
            params={
                "tree": (
                    "description,property[parameterDefinitions[name,defaultParameterValue[value]]]"
                )
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        team_display = ""
        version = ""
        labels: tuple[str, ...] = ()
        bundle = ""
        desc = str(payload.get("description") or "")
        rootcoz_url = extract_rootcoz_url(
            desc,
            mc.rootcoz_link_regex,
            allowed_hosts=list(mc.allowed_rootcoz_hosts),
        )
        for prop in payload.get("property") or []:
            if not isinstance(prop, dict):
                continue
            defaults: list[Any] = []
            for param in prop.get("parameterDefinitions") or []:
                if not isinstance(param, dict):
                    continue
                default = param.get("defaultParameterValue")
                if isinstance(default, dict):
                    defaults.append({"name": param.get("name"), "value": default.get("value")})
            team_display, version, labels, bundle = self._metadata_from_params(
                defaults,
                team_display=team_display,
                version=version,
                labels=labels,
                bundle=bundle,
            )
        return team_display, version, labels, bundle, rootcoz_url

    def _read_build_overrides(
        self,
        build_url: str,
        *,
        team_display: str,
        version: str,
        labels: tuple[str, ...],
        bundle: str,
        rootcoz_url: str,
    ) -> tuple[str, str, tuple[str, ...], str, str]:
        """Prefer build-time params and description rootcoz links."""
        mc = self._config.miss_check
        path = self._relative_api_path(build_url)
        if path is None:
            return team_display, version, labels, bundle, rootcoz_url
        resp = self._client.get(
            path,
            params={"tree": "description,actions[parameters[name,value]]"},
        )
        resp.raise_for_status()
        payload = resp.json()
        desc = str(payload.get("description") or "")
        from_desc = extract_rootcoz_url(
            desc,
            mc.rootcoz_link_regex,
            allowed_hosts=list(mc.allowed_rootcoz_hosts),
        )
        if from_desc:
            rootcoz_url = from_desc
        for action in payload.get("actions") or []:
            if not isinstance(action, dict):
                continue
            params = action.get("parameters")
            if not isinstance(params, list):
                continue
            team_display, version, labels, bundle = self._metadata_from_params(
                params,
                team_display=team_display,
                version=version,
                labels=labels,
                bundle=bundle,
            )
        return team_display, version, labels, bundle, rootcoz_url

    def _result_allowed(self, result: str, allowed: set[str]) -> bool:
        """True for finished non-success builds matching configured results."""
        normalized = (result or "").upper()
        if not normalized or normalized == "SUCCESS":
            return False
        if not allowed:
            return True
        return normalized in allowed

    def _labels_allowed(self, labels: tuple[str, ...]) -> bool:
        required = [r.strip().lower() for r in self._config.miss_check.require_labels if r.strip()]
        if not required:
            return True
        have = {lab.strip().lower() for lab in labels if lab.strip()}
        return all(r in have for r in required)

    def _name_allowed(self, job_name: str) -> bool:
        needle = self._config.miss_check.require_name_substring.strip().lower()
        if not needle:
            return True
        return needle in job_name.lower()

    def _builds_in_window(
        self,
        job_url: str,
        window: WeekWindow,
        *,
        results: set[str],
    ) -> list[dict[str, Any]]:
        path = self._relative_api_path(job_url)
        if path is None:
            return []
        resp = self._client.get(
            path,
            params={"tree": "builds[number,url,timestamp,result]"},
        )
        resp.raise_for_status()
        payload = resp.json()
        builds = payload.get("builds") if isinstance(payload, dict) else None
        if not isinstance(builds, list):
            return []
        start = datetime(
            window.date_from.year,
            window.date_from.month,
            window.date_from.day,
            tzinfo=UTC,
        )
        # Exclusive end: next UTC midnight after date_to (includes full final second).
        end = datetime(
            window.date_to.year,
            window.date_to.month,
            window.date_to.day,
            tzinfo=UTC,
        ) + timedelta(days=1)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        matched: list[dict[str, Any]] = []
        for build in builds:
            if not isinstance(build, dict):
                continue
            result = str(build.get("result") or "")
            if not self._result_allowed(result, results):
                continue
            ts = build.get("timestamp")
            try:
                ts_i = int(ts)
            except TypeError, ValueError:
                continue
            if ts_i < start_ms:
                # Builds are newest-first; older than window → stop.
                break
            if ts_i < end_ms:
                matched.append(build)
        return matched

    def fetch_builds_in_window(self, window: WeekWindow) -> list[JenkinsBuildRef]:
        """List non-success gating builds in the week window from the view."""
        mc = self._config.miss_check
        results = {r.upper() for r in mc.build_results if r.strip()}
        team_map = dict(self._config.team_map)
        refs: list[JenkinsBuildRef] = []
        jobs = self.list_view_jobs()
        logger.info("Jenkins view jobs: %d", len(jobs))
        base = str(self._client.base_url)
        for job in jobs:
            name = job["name"]
            if not self._name_allowed(name):
                continue
            job_url = job["url"]
            try:
                (
                    team_display,
                    version,
                    labels,
                    bundle,
                    job_rootcoz,
                ) = self._read_job_defaults(job_url)
                # Do not skip the job when defaults lack labels — build params may
                # carry JOB_METADATA.labels. Only skip when defaults explicitly
                # present labels that fail the require_labels check.
                if labels and not self._labels_allowed(labels):
                    continue
                builds = self._builds_in_window(job_url, window, results=results)
            except httpx.HTTPError as exc:
                logger.warning("Jenkins job fetch failed for %s: %s", name, exc)
                continue
            for build in builds:
                number = build.get("number")
                try:
                    build_number = int(number)
                except TypeError, ValueError:
                    continue
                build_url = str(build.get("url") or "")
                if not build_url:
                    job_base = job_url if job_url.endswith("/") else f"{job_url}/"
                    build_url = urljoin(job_base, f"{build_number}/")
                if not _same_origin(base, build_url):
                    logger.warning("Skipping off-base build URL for %s", name)
                    continue
                b_team, b_ver, b_labels, b_bundle, b_rootcoz = (
                    team_display,
                    version,
                    labels,
                    bundle,
                    job_rootcoz,
                )
                try:
                    b_team, b_ver, b_labels, b_bundle, b_rootcoz = self._read_build_overrides(
                        build_url,
                        team_display=team_display,
                        version=version,
                        labels=labels,
                        bundle=bundle,
                        rootcoz_url=job_rootcoz,
                    )
                except httpx.HTTPError as exc:
                    logger.warning(
                        "Jenkins build fetch failed for %s #%s: %s",
                        name,
                        build_number,
                        exc,
                    )
                if not self._labels_allowed(b_labels):
                    continue
                team = map_jenkins_team(b_team, team_map)
                refs.append(
                    JenkinsBuildRef(
                        job_name=name,
                        build_number=build_number,
                        jenkins_url=build_url,
                        result=str(build.get("result") or ""),
                        timestamp_ms=int(build.get("timestamp") or 0),
                        team_display=b_team,
                        team=team,
                        rootcoz_url=b_rootcoz,
                        version=b_ver,
                        bundle=b_bundle,
                        labels=b_labels,
                    )
                )
        logger.info(
            "Jenkins non-success gating builds in window (results=%s): %d",
            sorted(results) if results else "any-non-SUCCESS",
            len(refs),
        )
        return refs
