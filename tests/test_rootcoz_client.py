"""Tests for rootcoz API client query params."""

from datetime import date
from typing import Any

import httpx

from rootcoz_slack_digest.models import RootcozConfig, WeekWindow
from rootcoz_slack_digest.rootcoz_client import RootcozClient
from rootcoz_slack_digest.week import week_from_dates


def test_fetch_job_rows_sends_server_side_filters() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "job_id": "j1",
                    "job_name": "tier2-network",
                    "metadata": {
                        "team": "network",
                        "version": "4.22",
                        "labels": ["gating"],
                    },
                    "failure_count": 2,
                    "reviewed_count": 0,
                    "build_number": 9,
                    "jenkins_url": "https://jenkins.example/job/tier2-network/9/",
                    "created_at": "2026-08-01T00:00:00Z",
                    "tags": ["cnv", "v4.22.6.rhel9-9", "other"],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://rootcoz.example")
    cfg = RootcozConfig(url="https://rootcoz.example", api_key="test-key")
    window: WeekWindow = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))

    with RootcozClient(cfg, client=http) as client:
        rows = client.fetch_job_rows(
            window,
            team="network",
            labels=["gating", "release-checklist"],
            exclude_labels=["s390x"],
        )

    assert len(rows) == 1
    assert rows[0].team == "network"
    assert rows[0].version == "4.22"
    assert rows[0].bundle == "v4.22.6.rhel9-9"
    params = httpx.URL(captured["url"]).params
    assert params.get("team") == "network"
    assert params.get("date_from") == "2026-07-26"
    assert params.get("date_to") == "2026-08-01"
    assert params.get_list("label") == ["gating", "release-checklist"]
    assert params.get_list("exclude_label") == ["s390x"]
    assert params.get("review_status") == "not_reviewed"


def test_fetch_all_jobs_omits_review_status() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json=[
                {"job_id": "j1", "job_name": "job-one"},
                {"job_id": "j2", "job_name": "job-two"},
                {"job_id": "j3", "job_name": "job-three"},
            ],
        )

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://rootcoz.example")
    cfg = RootcozConfig(url="https://rootcoz.example", api_key="test-key")
    window: WeekWindow = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))

    with RootcozClient(cfg, client=http) as client:
        rows = client.fetch_all_jobs(
            window,
            team="network",
            labels=["gating"],
            exclude_labels=["s390x"],
        )

    assert len(rows) == 3
    assert rows[0].job_id == "j1"
    assert rows[0].rootcoz_url == "https://rootcoz.example/results/j1"
    params = httpx.URL(captured["url"]).params
    assert "review_status" not in params
    assert params.get("team") == "network"
    assert params.get_list("label") == ["gating"]
    assert params.get_list("exclude_label") == ["s390x"]


def test_fetch_job_rows_excludes_versions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[
                {
                    "job_id": "j1",
                    "job_name": "keep-me",
                    "metadata": {"team": "network", "version": "4.22", "labels": ["gating"]},
                    "failure_count": 1,
                    "reviewed_count": 0,
                },
                {
                    "job_id": "j2",
                    "job_name": "drop-test-version",
                    "metadata": {"team": "network", "version": "4.99", "labels": ["gating"]},
                    "failure_count": 3,
                    "reviewed_count": 0,
                },
                {
                    "job_id": "j3",
                    "job_name": "drop-unreleased",
                    "metadata": {"team": "network", "version": "5.0", "labels": ["gating"]},
                    "failure_count": 2,
                    "reviewed_count": 0,
                },
            ],
        )

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://rootcoz.example")
    cfg = RootcozConfig(url="https://rootcoz.example", api_key="test-key")
    window: WeekWindow = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))

    with RootcozClient(cfg, client=http) as client:
        rows = client.fetch_job_rows(
            window,
            team="network",
            exclude_versions=["4.99", "5.0"],
        )

    assert [r.job_id for r in rows] == ["j1"]
    assert rows[0].version == "4.22"


def test_fetch_all_jobs_excludes_versions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[
                {
                    "job_id": "j1",
                    "job_name": "keep-me",
                    "metadata": {"version": "4.22"},
                },
                {
                    "job_id": "j2",
                    "job_name": "drop-me",
                    "metadata": {"version": "5.99"},
                },
            ],
        )

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://rootcoz.example")
    cfg = RootcozConfig(url="https://rootcoz.example", api_key="test-key")
    window: WeekWindow = week_from_dates(date(2026, 7, 26), date(2026, 8, 1))

    with RootcozClient(cfg, client=http) as client:
        rows = client.fetch_all_jobs(window, exclude_versions=["5.99"])

    assert [r.job_id for r in rows] == ["j1"]
