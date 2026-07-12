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


def decode_access_token(token: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
