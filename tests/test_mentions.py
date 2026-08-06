"""Tests for Slack usergroup mention formatting."""

from rootcoz_slack_digest.mentions import (
    StaticUsergroupResolver,
    format_usergroup_mention,
    mention_for_handle,
)


def test_format_usergroup_mention() -> None:
    assert format_usergroup_mention("S123") == "<!subteam^S123>"


def test_mention_for_handle_resolves() -> None:
    resolver = StaticUsergroupResolver({"network-qe": "S99"})
    assert mention_for_handle(resolver, "@network-qe") == "<!subteam^S99>"


def test_mention_for_handle_missing_returns_empty() -> None:
    resolver = StaticUsergroupResolver({})
    assert mention_for_handle(resolver, "missing") == ""


def test_mention_for_handle_none() -> None:
    resolver = StaticUsergroupResolver({"x": "S1"})
    assert mention_for_handle(resolver, None) == ""
