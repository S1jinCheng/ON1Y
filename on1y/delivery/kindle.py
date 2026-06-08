"""Send documents to Amazon Kindle via email (Send to Kindle)."""

from __future__ import annotations

import logging
import smtplib
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from on1y.delivery.smtp_settings import get_resolved_smtp_settings
from on1y.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def send_epub_to_kindle(
    epub_path: Path,
    *,
    to_address: str,
    subject: str,
    settings: object | None = None,
) -> None:
    """Email an EPUB to a @kindle.com address (must send from approved Amazon email)."""
    _ = settings  # legacy callers may still pass Settings; SMTP is per-user now
    path = Path(epub_path)
    if not path.is_file():
        raise FileNotFoundError(f"EPUB not found: {path}")
    to_addr = to_address.strip()
    if not to_addr.endswith("@kindle.com"):
        logger.warning("Kindle address %s does not end with @kindle.com", to_addr)

    smtp_cfg = get_resolved_smtp_settings()
    if not smtp_cfg.configured:
        raise ConfigurationError(
            "SMTP not configured. Open Settings → Delivery and set your mail server "
            "(Gmail needs an App Password). FROM must be approved in Amazon Kindle settings."
        )
    host, port, user, password, from_addr, use_tls = (
        smtp_cfg.host,
        smtp_cfg.port,
        smtp_cfg.user,
        smtp_cfg.password,
        smtp_cfg.from_addr,
        smtp_cfg.use_tls,
    )
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
