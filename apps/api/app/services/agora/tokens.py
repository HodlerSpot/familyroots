"""Mint short-lived Agora RTC tokens for family video calls.

The App ID is public and safe to hand to clients. The App Certificate is a
SECRET, read from settings.agora_app_certificate (env
FUTUREROOTS_AGORA_APP_CERTIFICATE). It is used only here, to HMAC-sign tokens,
and must never appear in a response, a log line, or an error message.
"""

import time

from fastapi import HTTPException, status

from ...config import settings
from .RtcTokenBuilder2 import RtcTokenBuilder, Role_Publisher


def mint_rtc_token(channel_name: str, agora_uid: int, ttl_seconds: int) -> tuple[str, int]:
    """Build a publisher RTC token for one participant on one channel.

    Returns (token, expires_at_epoch_seconds). Raises 503 when video calling
    isn't configured (no certificate) — the App ID alone can't sign a token.
    """
    cert = settings.agora_app_certificate
    # An Agora App Certificate is a 32-char hex string. If it's missing or
    # malformed the builder would silently return an empty token; fail loudly
    # (and closed) instead so a misconfiguration can't ship a broken call.
    if len(cert) != 32 or not all(c in "0123456789abcdefABCDEF" for c in cert):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Video calling isn't set up yet"
        )
    token = RtcTokenBuilder.build_token_with_uid(
        settings.agora_app_id,
        settings.agora_app_certificate,
        channel_name,
        agora_uid,
        Role_Publisher,
        ttl_seconds,
        ttl_seconds,
    )
    return token, int(time.time()) + ttl_seconds
