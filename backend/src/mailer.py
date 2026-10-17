"""Wysyłka powiadomień e-mail przez SMTP (biblioteka standardowa, wywoływana w osobnym wątku)."""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from .config import settings

logger = logging.getLogger(__name__)


class MailNotConfiguredError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.smtp_host and (settings.smtp_from or settings.smtp_user))


def _send_sync(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_user
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    smtp_cls = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    with smtp_cls(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as smtp:
        if settings.smtp_starttls and not settings.smtp_ssl:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)


async def send_email(recipient: str, subject: str, body: str) -> None:
    if not is_configured():
        raise MailNotConfiguredError("Serwer SMTP nie jest skonfigurowany (SMTP_HOST, SMTP_FROM)")
    await asyncio.to_thread(_send_sync, recipient, subject, body)
    logger.info("Wysłano powiadomienie e-mail (temat=%r)", subject)
