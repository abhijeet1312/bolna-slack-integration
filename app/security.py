"""Security: IP whitelist + shared-secret token check for the webhook."""

from __future__ import annotations

import hmac
from collections.abc import Iterable

from fastapi import HTTPException, Request, status

from app.config import Settings
from app.logging_config import get_logger

logger = get_logger("security")


def _parse_allowed_ips(raw: str) -> set[str]:
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


def _client_ip(request: Request, trust_xff: bool) -> str:
    if trust_xff:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Take the leftmost (original client) entry.
            return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def verify_ip(request: Request, settings: Settings) -> None:
    allowed: Iterable[str] = _parse_allowed_ips(settings.allowed_ips)
    if not allowed:
        return  # check disabled

    ip = _client_ip(request, settings.trust_forwarded_for)
    if ip not in allowed:
        logger.warning("ip_rejected", ip=ip, path=request.url.path)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="IP not allowed"
        )


def verify_token(request: Request, settings: Settings) -> None:
    """
    Bolna doesn't sign webhook payloads, so we use a shared secret in either:
      - X-Webhook-Token header
      - ?token=... query param  (handy because Bolna only takes a URL)
    """
    if settings.webhook_secret is None:
        return  # check disabled

    expected = settings.webhook_secret.get_secret_value()
    provided = request.headers.get("x-webhook-token") or request.query_params.get(
        "token"
    )

    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning("token_rejected", has_token=bool(provided))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
