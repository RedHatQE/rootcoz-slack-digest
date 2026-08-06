"""Post Block Kit messages to Slack."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rootcoz_slack_digest.models import SlackConfig
from rootcoz_slack_digest.slack_format import blocks_to_fallback_text

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

    def post_blocks(self, blocks: list[dict[str, object]]) -> None:
        """Post blocks using configured mode."""
        text = blocks_to_fallback_text(blocks)
        if self._config.mode == "webhook":
            self._post_webhook(text, blocks)
            return
        self._post_chat(text, blocks)

    def _post_webhook(self, text: str, blocks: list[dict[str, object]]) -> None:
        if not self._config.webhook_url:
            msg = "slack.webhook_url (or SLACK_WEBHOOK_URL) is required for webhook mode"
            raise ValueError(msg)
        resp = self._client.post(
            self._config.webhook_url,
            json={"text": text, "blocks": blocks},
        )
        resp.raise_for_status()
        logger.info("Posted digest via Slack webhook")

    def _post_chat(self, text: str, blocks: list[dict[str, object]]) -> None:
        if not self._config.bot_token:
            msg = "slack.bot_token (or SLACK_BOT_TOKEN) is required for bot mode"
            raise ValueError(msg)
        if not self._config.channel:
            msg = "slack.channel is required for bot mode"
            raise ValueError(msg)
        payload: dict[str, Any] = {
            "channel": self._config.channel,
            "text": text,
            "blocks": blocks,
        }
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
        logger.info("Posted digest to Slack channel %s", self._config.channel)
