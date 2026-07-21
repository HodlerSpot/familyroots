"""Unit tests for the session-token layer: TTL windows, the `rmb` remember
claim, and the expired-vs-invalid decode split that powers the `session_expired`
401. Endpoint-level flows (login remember_me, /auth/refresh) live in test_auth."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.security import (
    SessionExpiredError,
    create_access_token,
    decode_access_token,
    read_remember_claim,
    session_ttl_seconds,
)


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


def _exp_seconds_from_now(token: str) -> float:
    exp = datetime.fromtimestamp(_claims(token)["exp"], tz=timezone.utc)
    return (exp - datetime.now(timezone.utc)).total_seconds()


def test_default_session_is_thirty_minutes():
    # founder-locked default
    assert settings.session_ttl_minutes == 30
    token = create_access_token(uuid.uuid4())
    assert _claims(token)["rmb"] is False
    assert abs(_exp_seconds_from_now(token) - settings.session_ttl_minutes * 60) < 120
    assert session_ttl_seconds(False) == settings.session_ttl_minutes * 60


def test_remembered_session_is_thirty_days():
    assert settings.remember_me_ttl_days == 30
    token = create_access_token(uuid.uuid4(), remember=True)
    assert _claims(token)["rmb"] is True
    expected = settings.remember_me_ttl_days * 24 * 60 * 60
    assert abs(_exp_seconds_from_now(token) - expected) < 120
    assert session_ttl_seconds(True) == expected


def test_read_remember_claim_roundtrips():
    assert read_remember_claim(create_access_token(uuid.uuid4())) is False
    assert read_remember_claim(create_access_token(uuid.uuid4(), remember=True)) is True


def test_read_remember_claim_defaults_false_for_garbage():
    assert read_remember_claim("not-a-jwt") is False


def test_valid_token_decodes_to_its_subject():
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid)) == uid


def test_expired_token_distinguishable_only_when_asked():
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "rmb": False,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    # default contract preserved: expired collapses to None like any failure
    assert decode_access_token(expired) is None
    # opt-in: expired raises so the caller can answer session_expired
    with pytest.raises(SessionExpiredError):
        decode_access_token(expired, raise_on_expired=True)


def test_garbage_token_never_raises_even_with_flag():
    assert decode_access_token("not-a-jwt") is None
    assert decode_access_token("not-a-jwt", raise_on_expired=True) is None
