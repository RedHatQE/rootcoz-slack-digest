"""Send digest emails via SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from rootcoz_slack_digest.models import EmailConfig

logger = logging.getLogger(__name__)


class EmailClient:
    """Send HTML digest emails via SMTP (no auth for internal relay)."""

    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    def send(
        self,
        *,
        recipients: list[str],
        cc: list[str] | None = None,
        subject: str,
        html_body: str,
        plain_body: str = "",
    ) -> None:
        """Send an email with HTML body and optional plain text fallback."""
        msg = MIMEMultipart("alternative")
        msg["From"] = self._config.from_address
        msg["To"] = ", ".join(recipients)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject

        if plain_body:
            msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        all_recipients = list(recipients) + (cc or [])
        with smtplib.SMTP(
            self._config.smtp_host,
            self._config.smtp_port,
            timeout=self._config.timeout,
        ) as server:
            if self._config.use_tls:
                server.starttls()
            if self._config.smtp_username:
                server.login(self._config.smtp_username, self._config.smtp_password)
            server.sendmail(self._config.from_address, all_recipients, msg.as_string())

        logger.info("Sent digest email to %s", ", ".join(recipients))
