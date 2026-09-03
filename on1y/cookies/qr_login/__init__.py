"""Platform QR / app-scan cookie login sessions."""

from on1y.cookies.qr_login.service import (
    QR_LOGIN_PLATFORMS,
    cancel_qr_login,
    poll_qr_login,
    start_qr_login,
)

__all__ = [
    "QR_LOGIN_PLATFORMS",
    "cancel_qr_login",
    "poll_qr_login",
    "start_qr_login",
]
