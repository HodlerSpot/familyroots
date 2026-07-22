"""Native (iOS/Android) push delivery via the Expo Push API.

The web VAPID path (``notify._deliver_push``) and this native path are two
transports for the SAME notification batch. ``notify._deliver_push`` calls
``deliver_native(db, batch)`` over the identical ``batch.push_user_ids``, so the
22-boolean ``NotificationPreference`` matrix and the ``_DELIVERY`` TTL/urgency
map govern native pushes exactly as they govern web pushes — there are no
native-specific preferences and no ``notify()`` call-site changes.

Transport specifics:

- We POST to a HARDCODED Expo host (``https://exp.host/--/api/v2/push/send``).
  The URL is never derived from user input, so — unlike the web push endpoint,
  which is a client-supplied URL guarded by ``push_targets`` — there is no SSRF
  surface here and no allowlist to maintain.
- Messages are sent in chunks of 100 (Expo's documented per-request cap).
- Expo returns one receipt (``ticket``) per message, positionally aligned with
  the request array. A ticket with ``status == "error"`` and
  ``details.error == "DeviceNotRegistered"`` means the token is dead; we prune
  those rows, mirroring the web dead-subscription pruning. Any other failure is
  logged and swallowed so one bad token never breaks the fan-out or the user's
  original action.
- ``settings.expo_access_token`` is OPTIONAL: when set we send it as a bearer
  token (for Expo projects that enforce authenticated sends); when empty we send
  unauthenticated, which Expo allows by default. Native push is therefore
  feature-dark simply by having no enrolled tokens — no key needs configuring.
"""

import logging
import uuid

import httpx

from ..config import settings
from ..models import NativePushToken

logger = logging.getLogger(__name__)

# Hardcoded — never user-controlled, so no SSRF surface (see module docstring).
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_CHUNK = 100  # Expo's documented per-request message cap
_TIMEOUT = 10  # seconds; the whole POST, matching the web path's best-effort stance


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def deliver_native(db, batch) -> None:
    """POST ``batch``'s payload to the Expo push token(s) of every push-enabled
    recipient. Best-effort: ``DeviceNotRegistered`` tokens are pruned; every
    other error is logged and swallowed. No-op when no recipient has a token
    (feature-dark)."""
    tokens = (
        db.query(NativePushToken)
        .filter(NativePushToken.user_id.in_(batch.push_user_ids))
        .all()
    )
    if not tokens:
        return  # feature dark: no native devices enrolled

    # Imported lazily to avoid a circular import (notify imports this module).
    from .notify import _DEFAULT_TTL, _DEFAULT_URGENCY, _DELIVERY

    ttl, urgency = _DELIVERY.get(batch.kind, (_DEFAULT_TTL, _DEFAULT_URGENCY))
    # Expo priority is "default" | "high"; map our web Urgency to it. Only the
    # short-lived, high-urgency call_live maps to "high"; everything else is
    # "default" (normal).
    priority = "high" if urgency == "high" else "default"
    data = {"url": batch.url or "/", "tag": batch.kind.value}

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.expo_access_token:
        headers["Authorization"] = f"Bearer {settings.expo_access_token}"

    dead: list[uuid.UUID] = []
    for chunk in _chunks(tokens, _CHUNK):
        messages = [
            {
                "to": tok.expo_push_token,
                "title": batch.title,
                "body": batch.body,
                "data": data,
                "ttl": ttl,
                "priority": priority,
            }
            for tok in chunk
        ]
        try:
            response = httpx.post(
                EXPO_PUSH_URL, json=messages, headers=headers, timeout=_TIMEOUT
            )
            response.raise_for_status()
            receipts = response.json().get("data", [])
        except Exception as exc:  # noqa: BLE001 — deliberately best-effort
            logger.warning("native push send error: %r", exc)
            continue
        # Receipts are positionally aligned with the messages we sent.
        for tok, receipt in zip(chunk, receipts):
            if not isinstance(receipt, dict) or receipt.get("status") != "error":
                continue
            details = receipt.get("details") or {}
            if details.get("error") == "DeviceNotRegistered":
                dead.append(tok.id)  # token is gone — prune it
            else:
                logger.warning("native push receipt error: %r", receipt.get("message"))

    if dead:
        db.query(NativePushToken).filter(NativePushToken.id.in_(dead)).delete(
            synchronize_session=False
        )
        db.commit()
