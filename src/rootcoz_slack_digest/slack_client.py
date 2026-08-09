"""Post messages to Slack (Block Kit or plain/mrkdwn text)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rootcoz_slack_digest.models import SlackConfig
from rootcoz_slack_digest.slack_format import payload_fallback_text

logger = logging.getLogger(__name__)


class SlackClient:
    """Send digests via bot token or incoming webhook."""

    def __init__(
        self,
        config: SlackConfig,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> SlackClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def post(
        self,
        payload: list[dict[str, object]] | str,
        channel: str | None = None,
    ) -> None:
        """Post blocks or text using configured mode."""
        text = payload_fallback_text(payload)
        blocks = payload if isinstance(payload, list) else None
        if self._config.mode == "webhook":
            self._post_webhook(text, blocks)
            return
        self._post_chat(text, blocks, channel=channel)

    def post_blocks(self, blocks: list[dict[str, object]], channel: str | None = None) -> None:
        """Backward-compatible alias for ``post`` with Block Kit."""
        self.post(blocks, channel=channel)

    def _post_webhook(self, text: str, blocks: list[dict[str, object]] | None) -> None:
        if not self._config.webhook_url:
            msg = "slack.webhook_url (or SLACK_WEBHOOK_URL) is required for webhook mode"
            raise ValueError(msg)
        body: dict[str, Any] = {"text": text}
        if blocks is not None:
            body["blocks"] = blocks
        resp = self._client.post(self._config.webhook_url, json=body)
        resp.raise_for_status()
        logger.info("Posted digest via Slack webhook")

    def _post_chat(
        self,
        text: str,
        blocks: list[dict[str, object]] | None,
        channel: str | None = None,
    ) -> None:
        if not self._config.bot_token:
            msg = "slack.bot_token (or SLACK_BOT_TOKEN) is required for bot mode"
            raise ValueError(msg)
        ch = channel or ""
        if not ch:
            msg = "channel is required for bot mode (pass channel from TARGETS)"
            raise ValueError(msg)
        payload: dict[str, Any] = {
            "channel": ch,
            "text": text,
        }
        if blocks is not None:
            payload["blocks"] = blocks
        resp = self._client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {self._config.bot_token}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            msg = data.get("error", "chat.postMessage failed")
            raise RuntimeError(f"Slack API error: {msg}")
        logger.info("Posted digest to Slack channel %s", ch)
