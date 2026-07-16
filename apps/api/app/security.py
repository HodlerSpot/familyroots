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


def create_access_token(user_id: uuid.UUID) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


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


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        # Scoped tokens (aud-bearing, e.g. media tokens) are never sessions.
        # PyJWT already raises InvalidAudienceError for an unexpected aud claim;
        # this explicit check keeps the invariant even if decode options change.
        if "aud" in payload:
            return None
        return uuid.UUID(payload["sub"])
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
