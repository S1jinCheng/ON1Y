"""Send documents to Amazon Kindle via email (Send to Kindle)."""

from __future__ import annotations

import logging
import smtplib
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from on1y.config import Settings, get_settings
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def _smtp_settings(settings: Settings) -> tuple[str, int, str, str, str, bool]:
    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_user or "").strip()
    password = (settings.smtp_password or "").replace(" ", "").strip()
    from_addr = (settings.smtp_from or user or "").strip()
    if not host or not user or not password or not from_addr:
        raise ConfigurationError(
            "SMTP not configured. Set ON1Y_SMTP_HOST, ON1Y_SMTP_USER, "
            "ON1Y_SMTP_PASSWORD, ON1Y_SMTP_FROM in .env (FROM must be approved on Amazon Kindle)."
        )
    return host, int(settings.smtp_port), user, password, from_addr, settings.smtp_use_tls


def send_epub_to_kindle(
    epub_path: Path,
    *,
    to_address: str,
    subject: str,
    settings: Settings | None = None,
) -> None:
    """Email an EPUB to a @kindle.com address (must send from approved Amazon email)."""
    settings = settings or get_settings()
    path = Path(epub_path)
    if not path.is_file():
        raise FileNotFoundError(f"EPUB not found: {path}")
    to_addr = to_address.strip()
    if not to_addr.endswith("@kindle.com"):
        logger.warning("Kindle address %s does not end with @kindle.com", to_addr)

    host, port, user, password, from_addr, use_tls = _smtp_settings(settings)
    body = (
        "Sent from On1y — The Economist weekly EPUB.\n"
        "If conversion fails, convert to MOBI or use Amazon's Send to Kindle app."
    )
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject[:200]
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with path.open("rb") as fh:
        part = MIMEApplication(fh.read(), _subtype="epub")
    part.add_header("Content-Disposition", "attachment", filename=path.name)
    msg.attach(part)

    logger.info("Sending %s to Kindle %s via %s", path.name, to_addr, host)
    if use_tls:
        with smtplib.SMTP(host, port, timeout=60) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP_SSL(host, port, timeout=60) as smtp:
            smtp.login(user, password)
            smtp.sendmail(from_addr, [to_addr], msg.as_string())
    logger.info("Kindle email sent: %s", subject)
