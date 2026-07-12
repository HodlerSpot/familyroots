import hashlib
from datetime import timedelta

import pytest

from .conftest import TestingSession, signup


@pytest.mark.parametrize(
    "bad",
    [
        "short1!A",  # fine length but... actually valid; replaced below
        "alllowercase1!",  # no uppercase
        "ALLUPPERCASE1!",  # no lowercase
        "NoNumbersHere!",  # no digit
        "NoSymbols123",  # no symbol
        "Ab1!",  # too short
    ],
)
def test_signup_rejects_weak_passwords(client, bad):
    if bad == "short1!A":
        pytest.skip("valid example placeholder")
    r = client.post(
        "/auth/signup",
        json={"email": "weak@example.com", "display_name": "W", "password": bad},
    )
    assert r.status_code == 422, bad


def get_reset_token(client, tmp_path, monkeypatch, email):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))
    r = client.post("/auth/forgot-password", json={"email": email})
    assert r.status_code == 204
    emails = sorted(outbox.glob("*.txt"))
    if not emails:
        return None
    content = emails[-1].read_text(encoding="utf-8")
    return content.split("/reset-password/")[1].split()[0]


def test_forgot_password_full_flow(client, tmp_path, monkeypatch):
    signup(client, "parent@example.com", "Pat")
    token = get_reset_token(client, tmp_path, monkeypatch, "parent@example.com")
    assert token

    r = client.post(
        "/auth/reset-password", json={"token": token, "new_password": "NewSecret9$"}
    )
    assert r.status_code == 204

    # old password dead, new one works
    assert (
        client.post(
            "/auth/login", json={"email": "parent@example.com", "password": "Password123!"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": "parent@example.com", "password": "NewSecret9$"}
        ).status_code
        == 200
    )

    # token is single-use
    r = client.post(
        "/auth/reset-password", json={"token": token, "new_password": "Another1_pw"}
    )
    assert r.status_code == 400


def test_forgot_password_never_leaks_accounts(client, tmp_path, monkeypatch):
    token = get_reset_token(client, tmp_path, monkeypatch, "nobody@example.com")
    assert token is None  # 204 either way, but no email sent


def test_reset_rejects_weak_password_and_bad_token(client, tmp_path, monkeypatch):
    signup(client, "parent@example.com")
    token = get_reset_token(client, tmp_path, monkeypatch, "parent@example.com")
    r = client.post("/auth/reset-password", json={"token": token, "new_password": "weakpw"})
    assert r.status_code == 422
    r = client.post(
        "/auth/reset-password", json={"token": "forged-token", "new_password": "NewSecret9$"}
    )
    assert r.status_code == 400


def test_expired_reset_token_rejected(client, tmp_path, monkeypatch):
    from app.models import PasswordReset, utcnow

    signup(client, "parent@example.com")
    token = get_reset_token(client, tmp_path, monkeypatch, "parent@example.com")
    with TestingSession() as db:
        reset = (
            db.query(PasswordReset)
            .filter(PasswordReset.token_hash == hashlib.sha256(token.encode()).hexdigest())
            .one()
        )
        reset.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    r = client.post(
        "/auth/reset-password", json={"token": token, "new_password": "NewSecret9$"}
    )
    assert r.status_code == 400


def test_change_password(client):
    headers = signup(client, "parent@example.com")

    # wrong current password refused
    r = client.post(
        "/auth/change-password",
        json={"current_password": "Wrong123!", "new_password": "NewSecret9$"},
        headers=headers,
    )
    assert r.status_code == 403

    # weak new password refused
    r = client.post(
        "/auth/change-password",
        json={"current_password": "Password123!", "new_password": "weak"},
        headers=headers,
    )
    assert r.status_code == 422

    # success
    r = client.post(
        "/auth/change-password",
        json={"current_password": "Password123!", "new_password": "NewSecret9$"},
        headers=headers,
    )
    assert r.status_code == 204
    assert (
        client.post(
            "/auth/login", json={"email": "parent@example.com", "password": "NewSecret9$"}
        ).status_code
        == 200
    )

    # requires auth
    r = client.post(
        "/auth/change-password",
        json={"current_password": "x", "new_password": "NewSecret9$"},
    )
    assert r.status_code == 401
