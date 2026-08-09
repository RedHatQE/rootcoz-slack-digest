"""Tests for SMTP email client (stdlib smtplib doubled in tests)."""

from __future__ import annotations

from typing import Any

from rootcoz_slack_digest.email_client import EmailClient
from rootcoz_slack_digest.models import EmailConfig


class _FakeSMTP:
    instances: list[_FakeSMTP] = []

    def __init__(self, host: str, port: int, timeout: int = 30) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.sent: list[tuple[str, list[str], str]] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        self.sent.append((from_addr, to_addrs, msg))


def test_email_client_send(monkeypatch: Any) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr("rootcoz_slack_digest.email_client.smtplib.SMTP", _FakeSMTP)
    cfg = EmailConfig(
        enabled=True,
        smtp_host="smtp.test",
        smtp_port=2525,
        from_address="digest@test",
        use_tls=True,
    )
    client = EmailClient(cfg)
    client.send(
        recipients=["a@test"],
        cc=["b@test"],
        subject="subj",
        html_body="<p>hi</p>",
        plain_body="hi",
    )
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.host == "smtp.test"
    assert smtp.port == 2525
    assert smtp.started_tls is True
    assert len(smtp.sent) == 1
    from_addr, to_addrs, msg = smtp.sent[0]
    assert from_addr == "digest@test"
    assert to_addrs == ["a@test", "b@test"]
    assert "Subject: subj" in msg
    assert "<p>hi</p>" in msg
