"""Tests for JSON path resolution and tier extraction."""

from rootcoz_slack_digest.field_resolver import extract_tier, resolve_path, resolve_template


def test_resolve_path_simple() -> None:
    assert resolve_path({"a": 1}, "a") == 1


def test_resolve_path_nested() -> None:
    assert resolve_path({"a": {"b": {"c": 3}}}, "a.b.c") == 3


def test_resolve_path_missing() -> None:
    assert resolve_path({"a": 1}, "b") is None


def test_resolve_path_none_intermediate() -> None:
    assert resolve_path({"a": None}, "a.b") is None


def test_resolve_template() -> None:
    result = resolve_template(
        "{url}/results/{job_id}",
        {"job_id": "abc"},
        {"url": "https://example.com"},
    )
    assert result == "https://example.com/results/abc"


def test_resolve_template_missing_key() -> None:
    result = resolve_template("{url}/x/{missing}", {}, {"url": "https://x.com"})
    assert result == "https://x.com/x/"


def test_extract_tier_list() -> None:
    labels = {"gating": "gating", "release-checklist": "release-checklist"}
    assert extract_tier(["gating", "other-label"], labels) == "gating"
    assert extract_tier(["unknown"], labels) == "other"


def test_extract_tier_string() -> None:
    labels = {"gating": "gating"}
    assert extract_tier("gating", labels) == "gating"
    assert extract_tier("unknown", labels) == "unknown"


def test_extract_tier_none() -> None:
    assert extract_tier(None, {}) == "other"


def test_extract_tier_custom_default() -> None:
    assert extract_tier(["unknown"], {}, default="misc") == "misc"
    assert extract_tier(None, {}, default="misc") == "misc"
    assert extract_tier("", {}, default="misc") == "misc"
