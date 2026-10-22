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
    try:
        # Port 465 is implicit TLS; anything else (normally 587) upgrades with STARTTLS.
        if s.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=10)
        else:
            smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10)
        with smtp:
            if s.smtp_port != 465:
                smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError):
        # Never let a mail outage break the request (or reveal whether an account exists); the log says why.
        log.exception("Sending email to %s failed (SMTP %s:%s)", to, s.smtp_host, s.smtp_port)


def dev_mailbox_enabled() -> bool:
    s = get_settings()
    return s.environment == "development" and not s.smtp_host
