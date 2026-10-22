import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

log = logging.getLogger("smartspend.email")

# Tests read this outbox; it is only populated when SMTP is not configured.
OUTBOX: list[dict] = []


def send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    if not s.smtp_host:
        OUTBOX.append({"to": to, "subject": subject, "body": body})
        del OUTBOX[:-50]
        if s.environment != "test":
            log.warning("SMTP not configured - email to %s: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
        smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)
