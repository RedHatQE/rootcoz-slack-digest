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
                    "metadata": {"team": "network", "labels": ["gating"]},
                    "failure_count": 2,
                    "reviewed_count": 0,
                    "build_number": 9,
                    "jenkins_url": "https://jenkins.example/job/tier2-network/9/",
                    "created_at": "2026-08-01T00:00:00Z",
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
    params = httpx.URL(captured["url"]).params
    assert params.get("team") == "network"
    assert params.get("date_from") == "2026-07-26"
    assert params.get("date_to") == "2026-08-01"
    assert params.get_list("label") == ["gating", "release-checklist"]
    assert params.get_list("exclude_label") == ["s390x"]
    assert params.get("review_status") == "not_reviewed"
