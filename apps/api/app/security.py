import re
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

PASSWORD_RULES = [
    (r".{8,}", "at least 8 characters"),
    (r"[a-z]", "a lowercase letter"),
    (r"[A-Z]", "an uppercase letter"),
    (r"[0-9]", "a number"),
    (r"[^A-Za-z0-9]", "a symbol"),
]


def validate_password_complexity(password: str) -> str:
    """Pydantic-compatible validator; raises ValueError listing what's missing."""
    missing = [label for pattern, label in PASSWORD_RULES if not re.search(pattern, password)]
    if missing:
        raise ValueError(f"Password needs {', '.join(missing)}")
    return password


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


class SessionExpiredError(Exception):
    """Raised by ``decode_access_token(..., raise_on_expired=True)`` when a
    token's signature is valid but its session window has passed. Lets
    ``deps.get_current_user`` answer with a distinguishable ``session_expired``
    401 (so the web can show a warm timeout note and re-login) rather than the
    generic invalid-token 401 a garbage credential earns."""


def session_ttl_seconds(remember: bool) -> int:
    """Lifetime, in seconds, of a session token for the given window — the
    ``expires_in_seconds`` the client uses to schedule its silent refresh."""
    if remember:
        return settings.remember_me_ttl_days * 24 * 60 * 60
    return settings.session_ttl_minutes * 60


def create_access_token(user_id: uuid.UUID, *, remember: bool = False) -> str:
    """Mint a session token. The default (unremembered) window is
    ``session_ttl_minutes``; ``remember=True`` ("Stay logged in") uses
    ``remember_me_ttl_days``. The ``rmb`` claim records which window was chosen
    so ``/auth/refresh`` can renew the SAME window without re-authenticating —
    and never escalate a short session into a long one."""
    now = datetime.now(timezone.utc)
    expires_at = (
        now + timedelta(days=settings.remember_me_ttl_days)
        if remember
        else now + timedelta(minutes=settings.session_ttl_minutes)
    )
    payload = {
        "sub": str(user_id),
        "rmb": remember,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def read_remember_claim(token: str) -> bool:
    """Read the ``rmb`` window flag from a session token. Called by
    ``/auth/refresh`` (after ``get_current_user`` has already validated the
    token) to renew the same window — a missing/false claim means the 30-minute
    window, so a short token can never be refreshed into a remembered one."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.InvalidTokenError, ValueError):
        return False
    return bool(payload.get("rmb", False))


def token_is_impersonation(token: str) -> bool:
    """True if this (signature-verified) token carries an ``imp`` claim, i.e. it
    is an admin impersonation token rather than a first-class session. Used by
    ``/auth/refresh`` to REFUSE refreshing an impersonation session: those have a
    deliberate hard time cap and an audit marker, and re-minting via the ordinary
    session path would both slide them indefinitely and strip the ``imp`` claim.
    Returns ``False`` for any invalid token (the caller's auth gate handles those)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (jwt.InvalidTokenError, ValueError):
        return False
    return "imp" in payload


def create_impersonation_token(user_id: uuid.UUID, admin_id: uuid.UUID, minutes: int = 30) -> str:
    """Short-lived token for an admin to view the app as a user. Carries an
    'imp' claim naming the acting admin for traceability; the product treats
    the holder as `user_id`."""
    payload = {
        "sub": str(user_id),
        "imp": str(admin_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str, *, raise_on_expired: bool = False) -> uuid.UUID | None:
    """Return the session's user id, or ``None`` for any invalid token.

    When ``raise_on_expired`` is set, a token whose signature is valid but whose
    session has expired raises ``SessionExpiredError`` instead of collapsing to
    ``None`` — the one case a caller may want to treat distinctly (a warm
    "session timed out" 401 vs. a generic invalid-credential 401). The default
    preserves the original None-on-any-failure contract for callers (e.g. the
    testnet optional-auth path) that don't care about the distinction."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        # Scoped tokens (aud-bearing, e.g. media tokens) are never sessions.
        # PyJWT already raises InvalidAudienceError for an unexpected aud claim;
        # this explicit check keeps the invariant even if decode options change.
        if "aud" in payload:
            return None
        return uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError:
        # ExpiredSignatureError subclasses InvalidTokenError, so this branch
        # must precede the generic one below.
        if raise_on_expired:
            raise SessionExpiredError from None
        return None
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


# --- media tokens ---
# <img>/<video>/<audio> tags can't send an Authorization header, so media URLs
# must carry a credential in the query string — a leak surface (proxy logs,
# browser history, Referer). Trade-off: we keep the query string but make the
# credential a short-lived token honored ONLY by GET /media/{id}. It is useless
# as an access token (decode_access_token rejects its aud claim), it is
# read-only by construction, and the media route still runs its full per-media
# authorization on every fetch — so a leaked URL exposes at most what its owner
# could already view, and only until the token expires.

MEDIA_TOKEN_AUDIENCE = "futureroots:media"


def create_media_token(user_id: uuid.UUID) -> str:
    """Short-lived, media-scoped credential for <img>/<video> URLs. Carries
    only the user id; per-media access checks still happen at fetch time."""
    payload = {
        "sub": str(user_id),
        "aud": MEDIA_TOKEN_AUDIENCE,
        "exp": datetime.now(timezone.utc)
        + timedelta(minutes=settings.media_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_media_token(token: str) -> uuid.UUID | None:
    """Accepts ONLY media-scoped tokens: requiring aud == MEDIA_TOKEN_AUDIENCE
    makes PyJWT reject ordinary access tokens (which carry no aud claim), so a
    full session JWT pasted into a media URL never works."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=MEDIA_TOKEN_AUDIENCE,
        )
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
