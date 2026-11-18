"""Email adapter. Dev/test default: log the token; production: set EMAIL_SMTP_URL."""
from __future__ import annotations

import logging

from src.core.config import get_settings

logger = logging.getLogger("vasoolkaro.email")


def send_recovery_email(email: str, raw_token: str | None) -> None:
    settings = get_settings()
    if raw_token is None:
        return
    if not settings.email_smtp_url:
        # Dev/test adapter: never expose the token through the API; log for local
        # testing convenience only.
        logger.info("password recovery requested for %s; dev token: %s", email, raw_token)
        return
    # Production SMTP adapter (clean interface; configure EMAIL_SMTP_URL).
    import smtplib
    from email.message import EmailMessage
    from urllib.parse import urlparse

    parsed = urlparse(settings.email_smtp_url)
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = email
    msg["Subject"] = "Reset your VasoolKaro password"
    msg.set_content(
        f"Use this one-time token to reset your password (valid 1 hour):\n\n{raw_token}\n"
    )
    with smtplib.SMTP(parsed.hostname, parsed.port or 587) as smtp:
        if parsed.scheme == "smtps":
            smtp.starttls()
        user = parsed.username
        pwd = parsed.password
        if user and pwd:
            smtp.login(user, pwd)
        smtp.send_message(msg)
