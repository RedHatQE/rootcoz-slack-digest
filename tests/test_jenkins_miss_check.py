"""Tests for Jenkins team map, miss-check reconcile, and Slack annotations."""

from __future__ import annotations

from datetime import date

import httpx

from fakes import FakeRootcozClient, StaticUsergroupResolver
from rootcoz_slack_digest.jenkins_client import (
    JenkinsBuildRef,
    extract_rootcoz_url,
    map_jenkins_team,
)
from rootcoz_slack_digest.jenkins_miss_check import (
    find_missing_builds,
    jenkins_build_to_job_row,
    normalize_jenkins_url,
)
from rootcoz_slack_digest.models import (
    AppConfig,
    JenkinsConfig,
    JenkinsMissCheckConfig,
    JobRow,
    SlackTargetConfig,
    Target,
)
from rootcoz_slack_digest.service import run_digest
from rootcoz_slack_digest.slack_format import (
    COMMENT_BOTH_DOWN,
    COMMENT_JENKINS_DOWN,
    append_slack_comment,
    comment_rootcoz_down,
)


def _build(
    *,
    name: str = "job-a-gating",
    number: int = 1,
    team: str = "virt-node",
    team_display: str = "REPLACE Display",
    rootcoz_url: str = "",
    bundle: str = "v4.20.21.rhel9-10",
) -> JenkinsBuildRef:
    return JenkinsBuildRef(
        job_name=name,
        build_number=number,
        jenkins_url=f"https://jenkins.example/job/{name}/{number}/",
        result="FAILURE",
        timestamp_ms=1,
        team_display=team_display,
        team=team,
        rootcoz_url=rootcoz_url,
        bundle=bundle,
        labels=("gate",),
    )


def test_same_origin_normalizes_default_https_port() -> None:
    from rootcoz_slack_digest.jenkins_client import (
        _relative_api_path_from_urls,
        _same_origin,
    )

    assert _same_origin("https://jenkins.example/", "https://jenkins.example:443/job/a/")
    assert not _same_origin("https://jenkins.example/", "https://evil.example/job/a/")
    assert (
        _relative_api_path_from_urls(
            "https://jenkins.example/jenkins/",
            "https://jenkins.example/jenkins/job/a/",
        )
        == "job/a/api/json"
    )
    assert (
        _relative_api_path_from_urls(
            "https://jenkins.example/jenkins/",
            "https://jenkins.example/jenkins2/job/a/",
        )
        is None
    )


def test_map_jenkins_team_uses_config_map() -> None:
    assert map_jenkins_team("REPLACE Display", {"REPLACE Display": "virt-node"}) == "virt-node"
    assert map_jenkins_team("unknown", {"REPLACE Display": "virt-node"}) == ""
    # Slug passthrough must not work — only explicit display→slug keys.
    assert map_jenkins_team("virt-node", {"REPLACE Display": "virt-node"}) == ""


def test_extract_rootcoz_url_from_text() -> None:
    text = "see https://rootcoz.example/results/abc-123 for details"
    assert (
        extract_rootcoz_url(text, r"https?://[^\s\"'<>]+/results/[^\s\"'<>]+")
        == "https://rootcoz.example/results/abc-123"
    )
    assert (
        extract_rootcoz_url(
            text,
            r"https?://[^\s\"'<>]+/results/[^\s\"'<>]+",
            allowed_hosts=["other.example"],
        )
        == ""
    )
    assert (
        extract_rootcoz_url(
            text,
            r"https?://[^\s\"'<>]+/results/[^\s\"'<>]+",
            allowed_hosts=[],
        )
        == ""
    )


def test_extract_rootcoz_url_rejects_userinfo() -> None:
    text = "see https://leak:secret@rootcoz.example/results/abc-123 for details"
    assert (
        extract_rootcoz_url(
            text,
            r"https?://[^\s\"'<>]+/results/[^\s\"'<>]+",
            allowed_hosts=["rootcoz.example"],
        )
        == ""
    )


def test_view_path_rejects_traversal() -> None:
    from rootcoz_slack_digest.jenkins_client import JenkinsClient

    client = JenkinsClient(
        JenkinsConfig(
            url="https://jenkins.example",
            user="u",
            token="t",
            miss_check=JenkinsMissCheckConfig(view_path="/view/foo/../../../secrets/"),
        )
    )
    try:
        try:
            client._view_api_path()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    finally:
        client.close()


def test_normalize_and_find_missing() -> None:
    assert normalize_jenkins_url("https://Jenkins.Example/job/a/1/") == (
        "https://jenkins.example/job/a/1"
    )
    assert normalize_jenkins_url("https://jenkins.example:443/job/a/1/") == (
        "https://jenkins.example/job/a/1"
    )
    known = [
        JobRow(
            job_id="1",
            job_name="job-a",
            build_number=1,
            jenkins_url="https://jenkins.example/job/job-a/1/",
        )
    ]
    builds = [_build(name="job-a", number=1), _build(name="job-b", number=2)]
    missing = find_missing_builds(builds, known)
    assert len(missing) == 1
    assert missing[0].job_name == "job-b"


def test_find_missing_prefers_url_over_name_collision() -> None:
    """Same job_name+build_number with different URLs must not hide a miss."""
    known = [
        JobRow(
            job_id="1",
            job_name="nightly-gating",
            build_number=42,
            jenkins_url="https://jenkins.example/job/folder-a/job/nightly-gating/42/",
        )
    ]
    builds = [
        _build(
            name="nightly-gating",
            number=42,
            team="virt-node",
        ),
    ]
    # _build uses /job/{name}/{number}/ — different path than folder-a URL above.
    missing = find_missing_builds(builds, known)
    assert len(missing) == 1
    assert missing[0].build_number == 42


def test_find_missing_name_match_when_rootcoz_lacks_jenkins_url() -> None:
    """Inventory row without jenkins_url still matches by name+build."""
    known = [
        JobRow(
            job_id="1",
            job_name="job-a-gating",
            build_number=1,
            jenkins_url="",
        )
    ]
    builds = [_build(name="job-a-gating", number=1)]
    assert find_missing_builds(builds, known) == []


def test_path_traversal_rejected_in_relative_api_path() -> None:
    from rootcoz_slack_digest.jenkins_client import _relative_api_path_from_urls

    assert (
        _relative_api_path_from_urls(
            "https://jenkins.example/jenkins/",
            "https://jenkins.example/jenkins/job/../../secrets/",
        )
        is None
    )
    assert (
        _relative_api_path_from_urls(
            "https://jenkins.example/jenkins/",
            "https://jenkins.example/jenkins/job/%2e%2e/secrets/",
        )
        is None
    )
    assert (
        _relative_api_path_from_urls(
            "https://jenkins.example/jenkins/",
            "https://jenkins.example/jenkins/job/%2e%2e%2fsecrets/",
        )
        is None
    )


def test_normalize_jenkins_url_invalid_port_does_not_raise() -> None:
    assert normalize_jenkins_url("https://jenkins.example:abc/job/a/1/") == ""
    known = [
        JobRow(
            job_id="1",
            job_name="job-a",
            build_number=1,
            jenkins_url="https://jenkins.example:abc/job/a/1/",
        )
    ]
    builds = [_build(name="job-b", number=2)]
    missing = find_missing_builds(builds, known)
    assert len(missing) == 1


def test_extract_rootcoz_url_strips_default_https_port() -> None:
    text = "see https://rootcoz.example:443/results/abc-123 for details"
    assert (
        extract_rootcoz_url(
            text,
            r"https?://[^\s\"'<>]+/results/[^\s\"'<>]+",
            allowed_hosts=["rootcoz.example"],
        )
        == "https://rootcoz.example:443/results/abc-123"
    )


def test_extract_rootcoz_url_bare_host_port_scheme_agnostic() -> None:
    """allowed_hosts host:80 / host:443 must match http(s) default-port URLs."""
    pattern = r"https?://[^\s\"'<>]+/results/[^\s\"'<>]+"
    http_text = "see http://rootcoz.example/results/abc-123 for details"
    assert (
        extract_rootcoz_url(
            http_text,
            pattern,
            allowed_hosts=["rootcoz.example:80"],
        )
        == "http://rootcoz.example/results/abc-123"
    )
    https_text = "see https://rootcoz.example/results/abc-123 for details"
    assert (
        extract_rootcoz_url(
            https_text,
            pattern,
            allowed_hosts=["rootcoz.example:443"],
        )
        == "https://rootcoz.example/results/abc-123"
    )


def test_gating_name_and_label_filters() -> None:
    from rootcoz_slack_digest.jenkins_client import JenkinsClient

    client = JenkinsClient(
        JenkinsConfig(
            url="https://jenkins.example",
            user="u",
            token="t",
            miss_check=JenkinsMissCheckConfig(
                require_name_substring="gating",
                require_labels=["gate"],
                build_results=["FAILURE", "UNSTABLE"],
            ),
        )
    )
    try:
        assert client._name_allowed("test-ssp-cnv-4.20-gating")
        assert not client._name_allowed("test-ssp-cnv-4.18")
        assert client._labels_allowed(("gate", "tier1"))
        assert not client._labels_allowed(("smoke",))
        assert client._result_allowed("FAILURE", {"FAILURE", "UNSTABLE"})
        assert client._result_allowed("UNSTABLE", {"FAILURE", "UNSTABLE"})
        assert not client._result_allowed("SUCCESS", {"FAILURE", "UNSTABLE"})
        assert not client._result_allowed("SUCCESS", set())
        assert client._result_allowed("ABORTED", set())
    finally:
        client.close()


def test_miss_rows_merged_into_digest_table() -> None:
    row = jenkins_build_to_job_row(
        _build(rootcoz_url="https://rootcoz.example/results/x", bundle="v4.20.1"),
        tier="gating",
        rootcoz_missing=True,
    )
    assert row.rootcoz_missing is True
    assert row.rootcoz_url == ""
    assert row.bundle == "v4.20.1"


def test_jenkins_build_to_job_row_includes_bundle() -> None:
    row = jenkins_build_to_job_row(_build(bundle="v4.18.0"), tier="gating")
    assert row.bundle == "v4.18.0"


class _FakeJenkins:
    def __init__(self, builds: list[JenkinsBuildRef] | None = None, *, fail: bool = False) -> None:
        self._builds = builds or []
        self._fail = fail

    def fetch_builds_in_window(self, window: object) -> list[JenkinsBuildRef]:
        del window
        if self._fail:
            msg = "jenkins down"
            raise httpx.ConnectError(msg)
        return list(self._builds)

    def close(self) -> None:
        return None


class _RaisingRootcoz(FakeRootcozClient):
    def fetch_job_rows(self, *args: object, **kwargs: object) -> list[JobRow]:
        del args, kwargs
        msg = "rootcoz down"
        raise httpx.ConnectError(msg)


def _cfg_miss_enabled() -> AppConfig:
    return AppConfig(
        jenkins=JenkinsConfig(
            url="https://jenkins.example",
            user="u",
            token="t",
            miss_check=JenkinsMissCheckConfig(enabled=True, scopes=["gating"]),
            team_map={"REPLACE Display": "virt-node"},
        )
    )


def test_miss_rows_merged_into_same_table_per_team() -> None:
    cfg = _cfg_miss_enabled()
    rootcoz_rows = [
        JobRow(
            job_id="1",
            job_name="present",
            team="virt-node",
            tier="gating",
            failure_count=2,
            reviewed_count=0,
            build_number=1,
            jenkins_url="https://jenkins.example/job/present/1/",
            rootcoz_url="https://rootcoz.example/results/1",
            bundle="v4.20.0",
        )
    ]
    jenkins = _FakeJenkins(
        [
            _build(name="present", number=1, team="virt-node"),
            _build(name="missing-job", number=9, team="virt-node", bundle="v4.21.0"),
            _build(name="other-team", number=3, team="network"),
        ]
    )
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        targets=[
            Target(
                team="virt-node",
                slack=SlackTargetConfig(channel="C1", usergroup="g"),
            )
        ],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        rootcoz_client=FakeRootcozClient(unreviewed=rootcoz_rows, all_jobs=rootcoz_rows),
        jenkins_client=jenkins,  # type: ignore[arg-type]
    )
    assert "Missing from rootcoz" not in str(result.payload)
    names = [r.job_name for r in result.rows]
    assert "present" in names
    assert "missing-job" in names
    assert "other-team" not in names
    miss = next(r for r in result.rows if r.job_name == "missing-job")
    assert miss.rootcoz_missing is True
    assert miss.bundle == "v4.21.0"
    # Block Kit table contains both jobs; miss rootcoz cell is "missing"
    payload = result.payload
    assert isinstance(payload, list)
    tables = [b for b in payload if b.get("type") == "table"]
    assert tables
    cell_texts = []
    for table in tables:
        for row in table["rows"][1:]:  # type: ignore[index]
            for cell in row:
                if isinstance(cell, dict) and cell.get("type") == "raw_text":
                    cell_texts.append(cell["text"])
                elif isinstance(cell, dict) and cell.get("type") == "rich_text":
                    els = cell["elements"][0]["elements"]  # type: ignore[index]
                    if els and els[0].get("type") == "link":
                        cell_texts.append(els[0]["text"])
    assert "missing" in cell_texts
    assert "missing-job" in cell_texts
    assert "present" in cell_texts


def test_jenkins_down_adds_comment_still_digest() -> None:
    cfg = _cfg_miss_enabled()
    rows = [
        JobRow(
            job_id="1",
            job_name="present",
            team="virt-node",
            tier="gating",
            failure_count=1,
            reviewed_count=0,
            jenkins_url="https://jenkins.example/job/present/1/",
            rootcoz_url="https://rootcoz.example/results/1",
        )
    ]
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        targets=[Target(team="virt-node", slack=SlackTargetConfig(channel="C1", usergroup="g"))],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        rootcoz_client=FakeRootcozClient(unreviewed=rows, all_jobs=rows),
        jenkins_client=_FakeJenkins(fail=True),  # type: ignore[arg-type]
    )
    blob = str(result.payload)
    assert COMMENT_JENKINS_DOWN in blob
    assert "present" in blob


def test_both_down_posts_comment() -> None:
    cfg = _cfg_miss_enabled()
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        targets=[Target(team="virt-node", slack=SlackTargetConfig(channel="C1", usergroup="g"))],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        rootcoz_client=_RaisingRootcoz(),
        jenkins_client=_FakeJenkins(fail=True),  # type: ignore[arg-type]
    )
    assert COMMENT_BOTH_DOWN in str(result.payload)
    assert result.rows == []


def test_celebration_fetch_all_jobs_failure_triggers_jenkins_fallback() -> None:
    """Empty unreviewed + failing fetch_all_jobs must not abort; use Jenkins fallback."""

    class _FailAllJobs(FakeRootcozClient):
        def fetch_job_rows(self, *args: object, **kwargs: object) -> list[JobRow]:
            del args, kwargs
            return []

        def fetch_all_jobs(self, *args: object, **kwargs: object) -> list[JobRow]:
            del args, kwargs
            msg = "rootcoz all-jobs down"
            raise httpx.ConnectError(msg)

    cfg = _cfg_miss_enabled()
    jenkins = _FakeJenkins(
        [_build(name="gate-job", number=9, team="virt-node", rootcoz_url="")]
    )
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        targets=[Target(team="virt-node", slack=SlackTargetConfig(channel="C1", usergroup="g"))],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        rootcoz_client=_FailAllJobs(),
        jenkins_client=jenkins,  # type: ignore[arg-type]
    )
    assert "gate-job" in str(result.payload)
    assert comment_rootcoz_down(["gating"]) in str(result.payload)
    cfg = _cfg_miss_enabled()
    jenkins = _FakeJenkins(
        [
            _build(
                name="gate-job",
                number=5,
                team="virt-node",
                rootcoz_url="https://rootcoz.example/results/from-jenkins",
            )
        ]
    )
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        targets=[Target(team="virt-node", slack=SlackTargetConfig(channel="C1", usergroup="g"))],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        rootcoz_client=_RaisingRootcoz(),
        jenkins_client=jenkins,  # type: ignore[arg-type]
    )
    blob = str(result.payload)
    assert comment_rootcoz_down(["gating"]) in blob
    assert "gate-job" in blob
    assert "https://rootcoz.example/results/from-jenkins" in blob


def test_append_slack_comment_blocks() -> None:
    payload: list[dict[str, object]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "hello"}}
    ]
    out = append_slack_comment(payload, "note")
    assert isinstance(out, list)
    assert out[-1]["text"]["text"] == "note"  # type: ignore[index]


def test_celebration_jobs_kept_when_merging_misses() -> None:
    """All-reviewed celebration must not be replaced by a miss-only table."""
    cfg = _cfg_miss_enabled()
    reviewed = [
        JobRow(
            job_id="s1",
            job_name="test-pytest-cnv-4.13-storage-gating",
            team="storage-platform",
            tier="gating",
            failure_count=2,
            reviewed_count=2,
            build_number=1193,
            jenkins_url="https://jenkins.example/job/test-pytest-cnv-4.13-storage-gating/1193/",
            rootcoz_url="https://rootcoz.example/results/s1",
            bundle="v4.13.15.rhel9-8",
        )
    ]
    jenkins = _FakeJenkins(
        [
            _build(
                name="really-missing-storage",
                number=9,
                team="storage-platform",
                bundle="v4.20.0",
            )
        ]
    )
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        targets=[
            Target(
                team="storage-platform",
                slack=SlackTargetConfig(channel="C1", usergroup="g"),
            )
        ],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        rootcoz_client=FakeRootcozClient(unreviewed=[], all_jobs=reviewed),
        jenkins_client=jenkins,  # type: ignore[arg-type]
    )
    names = [r.job_name for r in result.rows]
    assert "test-pytest-cnv-4.13-storage-gating" in names
    assert "really-missing-storage" in names
    reviewed_row = next(r for r in result.rows if r.job_name.startswith("test-pytest"))
    miss_row = next(r for r in result.rows if r.job_name.startswith("really-missing"))
    assert reviewed_row.rootcoz_missing is False
    assert miss_row.rootcoz_missing is True


def test_injected_rows_skip_jenkins_even_if_enabled() -> None:
    """Offline ``rows=`` mode must not contact Jenkins."""
    cfg = _cfg_miss_enabled()
    rows = [
        JobRow(
            job_id="1",
            job_name="present",
            team="virt-node",
            tier="gating",
            failure_count=1,
            reviewed_count=0,
        )
    ]
    result = run_digest(
        cfg,
        dry_run=True,
        date_from=date(2026, 7, 27),
        date_to=date(2026, 8, 2),
        rows=rows,
        targets=[Target(team="virt-node", slack=SlackTargetConfig(channel="C1", usergroup="g"))],
        usergroup_resolver=StaticUsergroupResolver({"g": "S1"}),
        jenkins_client=_FakeJenkins(fail=True),  # type: ignore[arg-type]
    )
    assert COMMENT_JENKINS_DOWN not in str(result.payload)
    assert "Missing from rootcoz" not in str(result.payload)


def test_annotate_misses_filters_before_max_miss_rows() -> None:
    """exclude_job_patterns must run before max_miss_rows capping."""
    from rootcoz_slack_digest.digest_result import TargetResult
    from rootcoz_slack_digest.jenkins_digest import annotate_slack_with_misses
    from rootcoz_slack_digest.models import DigestConfig
    from rootcoz_slack_digest.week import week_from_dates

    cfg = AppConfig(
        digest=DigestConfig(exclude_job_patterns=["excluded-"]),
        jenkins=JenkinsConfig(
            url="https://jenkins.example",
            user="u",
            token="t",
            miss_check=JenkinsMissCheckConfig(
                enabled=True,
                scopes=["gating"],
                max_miss_rows=1,
                attach_to_slack=True,
            ),
            team_map={"REPLACE Display": "virt-node"},
        ),
    )
    target = Target(team="virt-node", slack=SlackTargetConfig(channel="C1"))
    tr = TargetResult(target=target, payload="base", rows=[], total_jobs=0)
    misses = [
        _build(name="excluded-gating", number=1, team="virt-node"),
        _build(name="kept-gating", number=2, team="virt-node"),
    ]
    updated = annotate_slack_with_misses(
        [tr],
        misses=misses,
        unmapped=[],
        cfg=cfg,
        window=week_from_dates(date(2026, 7, 27), date(2026, 8, 2)),
        resolver=None,
    )
    names = [r.job_name for r in updated[0].rows]
    assert names == ["kept-gating"]


def test_jenkins_fallback_applies_exclude_job_patterns() -> None:
    """Rootcoz-down fallback must honor digest.exclude_job_patterns."""
    from rootcoz_slack_digest.jenkins_digest import build_jenkins_fallback_targets
    from rootcoz_slack_digest.models import DigestConfig
    from rootcoz_slack_digest.week import week_from_dates

    cfg = AppConfig(
        digest=DigestConfig(exclude_job_patterns=["foo-"]),
        jenkins=JenkinsConfig(
            url="https://jenkins.example",
            user="u",
            token="t",
            miss_check=JenkinsMissCheckConfig(enabled=True, scopes=["gating"]),
            team_map={"REPLACE Display": "virt-node"},
        ),
    )
    targets = [Target(team="virt-node", slack=SlackTargetConfig(channel="C1"))]
    builds = [
        _build(name="foo-gating", number=1, team="virt-node"),
        _build(name="bar-gating", number=2, team="virt-node"),
    ]
    results, all_rows = build_jenkins_fallback_targets(
        cfg=cfg,
        window=week_from_dates(date(2026, 7, 27), date(2026, 8, 2)),
        targets=targets,
        builds=builds,
        resolver=None,
    )
    names = [r.job_name for r in results[0].rows]
    assert names == ["bar-gating"]
    assert [r.job_name for r in all_rows] == ["bar-gating"]
