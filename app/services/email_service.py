
import logging
import os
import smtplib
from pathlib import Path
from email.message import EmailMessage
from dotenv import load_dotenv



# Load .env from the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email and return True only when SMTP accepts it."""

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL", "").strip() or username
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not host or not username or not password or not from_email:
        logger.error("Email not sent: SMTP configuration is incomplete.")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            # Identify this client to the SMTP server.
            server.ehlo()

            if use_tls:
                server.starttls()
                # Negotiate SMTP capabilities again after TLS.
                server.ehlo()

            if "auth" not in server.esmtp_features:
                raise RuntimeError(
                    "SMTP AUTH is not advertised after TLS. "
                    "Check SMTP host, port, and network configuration."
                )

            server.login(username, password)
            server.send_message(message)

        logger.info("Email sent successfully to %s", to_email)
        return True

    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        return False


def send_email_safely(
    to_email: str, subject: str, body: str
) -> None:
    """Background-task wrapper that logs failures without raising."""
    try:
        send_email(to_email, subject, body)
    except Exception:
        logger.exception(
            "Unexpected notification error for %s", to_email
        )