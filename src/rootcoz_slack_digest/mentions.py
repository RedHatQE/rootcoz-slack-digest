"""Resolve Slack usergroup handles to mention tokens.

Teams own usergroup membership in Slack. This module only maps a configured
handle → ``<!subteam^ID>``. Missing groups yield an empty string (no ping).
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


class UsergroupResolver(Protocol):
    """Lookup Slack usergroup id by handle."""

    def resolve(self, handle: str) -> str | None:
        """Return usergroup id (``S…``) or None if not found."""
        ...


def format_usergroup_mention(usergroup_id: str) -> str:
    """Slack mrkdwn mention for a usergroup id."""
    return f"<!subteam^{usergroup_id}>"


def mention_for_handle(resolver: UsergroupResolver, handle: str | None) -> str:
    """Resolve handle to a mention token, or empty if unavailable."""
    if not handle:
        return ""
    cleaned = handle.lstrip("@").strip()
    if not cleaned:
        return ""
    gid = resolver.resolve(cleaned)
    if not gid:
        logger.warning("Slack usergroup handle %r not found; skipping mention", cleaned)
        return ""
    return format_usergroup_mention(gid)


class SlackUsergroupResolver:
    """Resolve handles via ``usergroups.list`` (cached for one run)."""

    def __init__(
        self,
        token: str,
        *,
        api_base_url: str = "https://slack.com/api",
        timeout: int = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._cache: dict[str, str] | None = None

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> SlackUsergroupResolver:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._api_base_url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=float(self._timeout),
            )
        return self._client

    def _load(self) -> dict[str, str]:
        if self._cache is not None:
            return self._cache
        resp = self._http().get("/usergroups.list", params={"include_users": "false"})
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            msg = data.get("error", "usergroups.list failed")
            raise RuntimeError(f"Slack API error: {msg}")
        mapping: dict[str, str] = {}
        for group in data.get("usergroups", []):
            handle = group.get("handle")
            gid = group.get("id")
            if handle and gid:
                mapping[str(handle)] = str(gid)
        self._cache = mapping
        return mapping

    def resolve(self, handle: str) -> str | None:
        """Return usergroup id for handle, or None."""
        return self._load().get(handle.lstrip("@"))
