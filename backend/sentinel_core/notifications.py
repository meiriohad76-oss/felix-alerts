from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage as MimeEmailMessage
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Protocol, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

from .models import AlertRecord, NotificationRecord

DISCLAIMER = (
    "Sentinel is software that follows a published methodology. "
    "It is not investment advice. You are responsible for your own trading decisions."
)


@dataclass(frozen=True)
class EmailMessage:
    subject: str
    text_body: str


class EmailProvider(Protocol):
    def send(self, message: EmailMessage, recipients: Tuple[str, ...]) -> str:
        ...


class TelegramProvider(Protocol):
    def send(self, chat_id: str, text: str) -> str:
        ...


class SmtpEmailProvider:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sender: str,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        timeout_seconds: int = 15,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.timeout_seconds = timeout_seconds

    def send(self, message: EmailMessage, recipients: Tuple[str, ...]) -> str:
        if not recipients:
            raise ValueError("email recipients are required")
        mime = MimeEmailMessage()
        mime["From"] = self.sender
        mime["To"] = ", ".join(recipients)
        mime["Subject"] = message.subject
        mime.set_content(message.text_body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(mime)
        return "smtp-sent"


class TelegramBotProvider:
    def __init__(self, *, bot_token: str, timeout_seconds: int = 15) -> None:
        self.bot_token = bot_token
        self.timeout_seconds = timeout_seconds

    def send(self, chat_id: str, text: str) -> str:
        if not chat_id:
            raise ValueError("telegram chat id is required")
        payload = urlencode(
            {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        url = "https://api.telegram.org/bot%s/sendMessage" % self.bot_token
        with urlopen(url, data=payload, timeout=self.timeout_seconds) as response:
            return "telegram-%s" % response.status


def render_alert_email(alert: AlertRecord) -> EmailMessage:
    explanation = alert.explanation
    subject = "[Sentinel] %s: %s %s" % (
        alert.result.kind.upper(),
        alert.result.ticker,
        alert.result.rule_id,
    )
    ticket_text = alert.ticket.copy_text if alert.ticket else "No broker ticket is required for this alert."
    body = "\n\n".join(
        [
            "%s - %s" % (explanation.rule_id, explanation.title),
            "What triggered:\n%s" % explanation.what_triggered,
            "Why this rule exists:\n%s" % explanation.rule_rationale,
            "Recommended action:\n%s" % explanation.recommended_action,
            "Manual broker ticket:\n%s" % ticket_text,
            DISCLAIMER,
        ]
    )
    return EmailMessage(subject=subject, text_body=body)


def _single_line(value: object, *, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def render_alert_telegram(alert: AlertRecord, *, stock_url: str = "") -> str:
    explanation = alert.explanation
    lines = [
        "Sentinel alert: %s / %s" % (alert.result.ticker, explanation.rule_id),
        "Severity: %s" % alert.result.severity,
        "What triggered: %s" % _single_line(explanation.what_triggered),
        "Recommended action: %s" % _single_line(explanation.recommended_action),
    ]
    if stock_url:
        lines.append("Open stock detail: %s" % stock_url)
    lines.append(
        "Sentinel does not place broker orders. You are responsible for your own trading decisions."
    )
    message = "\n".join(lines)
    if len(message) > 3900:
        return message[:3897].rstrip() + "..."
    return message


def notification_id_for_alert(alert: AlertRecord, channel: str = "in_app"):
    return uuid5(NAMESPACE_URL, "sentinel:notification:%s:%s" % (alert.alert_id, channel))


def notification_for_alert(
    alert: AlertRecord,
    *,
    channel: str = "in_app",
    created_at: Optional[datetime] = None,
) -> NotificationRecord:
    email = render_alert_email(alert)
    body = email.text_body
    subject = email.subject
    if channel == "telegram":
        body = render_alert_telegram(alert)
        subject = "[Sentinel] Telegram alert %s %s" % (alert.result.ticker, alert.result.rule_id)
    return NotificationRecord(
        notification_id=notification_id_for_alert(alert, channel),
        portfolio_id=alert.result.portfolio_id,
        alert_id=alert.alert_id,
        ticker=alert.result.ticker,
        rule_id=alert.result.rule_id,
        channel=channel,
        status="sent" if channel == "in_app" else "queued",
        subject=subject,
        body=body,
        created_at=created_at or datetime.utcnow(),
    )


def notifications_for_alerts(alerts: Iterable[AlertRecord], *, channel: str = "in_app") -> Tuple[NotificationRecord, ...]:
    return tuple(notification_for_alert(alert, channel=channel) for alert in alerts)


def normalize_email_recipients(value) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw_items = value.replace(";", ",").split(",")
    else:
        raw_items = list(value)
    recipients = []
    seen = set()
    for item in raw_items:
        recipient = str(item).strip()
        if not recipient or recipient in seen:
            continue
        recipients.append(recipient)
        seen.add(recipient)
    return tuple(recipients)


def external_notifications_for_alerts(
    alerts: Iterable[AlertRecord],
    settings: dict,
) -> Tuple[NotificationRecord, ...]:
    records = []
    email_recipients = normalize_email_recipients(settings.get("email_recipients"))
    if settings.get("email_enabled") and email_recipients:
        records.extend(notifications_for_alerts(alerts, channel="email"))
    if settings.get("telegram_enabled") and str(settings.get("telegram_chat_id") or "").strip():
        records.extend(notifications_for_alerts(alerts, channel="telegram"))
    return tuple(records)


def email_provider_from_environment(env: Optional[dict] = None) -> Optional[SmtpEmailProvider]:
    source = env or os.environ
    host = source.get("SENTINEL_EMAIL_HOST", "").strip()
    sender = source.get("SENTINEL_EMAIL_FROM", "").strip()
    if not host or not sender:
        return None
    return SmtpEmailProvider(
        host=host,
        port=int(source.get("SENTINEL_EMAIL_PORT", "587")),
        sender=sender,
        username=source.get("SENTINEL_EMAIL_USERNAME", "").strip(),
        password=source.get("SENTINEL_EMAIL_PASSWORD", ""),
        use_tls=source.get("SENTINEL_EMAIL_TLS", "1").strip().lower() not in {"0", "false", "no"},
        timeout_seconds=int(source.get("SENTINEL_EMAIL_TIMEOUT_SECONDS", "15")),
    )


def telegram_provider_from_environment(env: Optional[dict] = None) -> Optional[TelegramBotProvider]:
    source = env or os.environ
    token = source.get("SENTINEL_TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None
    return TelegramBotProvider(
        bot_token=token,
        timeout_seconds=int(source.get("SENTINEL_TELEGRAM_TIMEOUT_SECONDS", "15")),
    )
