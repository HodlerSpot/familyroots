from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

from .conftest import signup


def _claims(token: str) -> dict:
    """Inspect a token's claims without verifying its signature."""
    return jwt.decode(token, options={"verify_signature": False})


def test_signup_login_me(client):
    signup(client, "parent@example.com", "Pat Parent")

    r = client.post(
        "/auth/login", json={"email": "parent@example.com", "password": "Password123!"}
    )
    assert r.status_code == 200
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "parent@example.com"
    assert r.json()["display_name"] == "Pat Parent"


def test_duplicate_email_rejected(client):
    signup(client, "parent@example.com")
    r = client.post(
        "/auth/signup",
        json={"email": "parent@example.com", "display_name": "X", "password": "Password123!"},
    )
    assert r.status_code == 409


def test_wrong_password_rejected(client):
    signup(client, "parent@example.com")
    r = client.post("/auth/login", json={"email": "parent@example.com", "password": "wrongpass1"})
    assert r.status_code == 401


def test_welcome_email_on_signup(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(tmp_path))
    signup(client, "newfamily@example.com", "Pat Parent")

    emails = list(tmp_path.glob("*.txt"))
    assert len(emails) == 1
    content = emails[0].read_text(encoding="utf-8")
    assert "To: newfamily@example.com" in content
    assert "Welcome to FutureRoots, Pat Parent" in content
    assert "/family" in content
    # Brand rule: no crypto vocabulary in user-facing text
    for banned in ("wallet", "blockchain", "crypto", "token", "web3"):
        assert banned not in content.lower()


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401
    r = client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
    # a garbage token is a generic 401 — NOT flagged as a timed-out session
    assert r.json()["detail"] != {"code": "session_expired"}


def test_expired_session_token_is_flagged_session_expired(client):
    """An expired-but-valid token earns a distinguishable 401 the web keys on
    to show a warm timeout note, unlike a garbage-token 401."""
    parent = signup(client, "parent@example.com")
    me = client.get("/auth/me", headers=parent).json()
    expired = jwt.encode(
        {
            "sub": me["id"],
            "rmb": False,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401
    assert r.json()["detail"] == {"code": "session_expired"}


def test_login_default_issues_short_session(client):
    signup(client, "parent@example.com")
    r = client.post(
        "/auth/login", json={"email": "parent@example.com", "password": "Password123!"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in_seconds"] == settings.session_ttl_minutes * 60
    assert _claims(body["access_token"])["rmb"] is False


def test_login_remember_me_issues_long_session(client):
    signup(client, "parent@example.com")
    r = client.post(
        "/auth/login",
        json={
            "email": "parent@example.com",
            "password": "Password123!",
            "remember_me": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in_seconds"] == settings.remember_me_ttl_days * 24 * 60 * 60
    assert _claims(body["access_token"])["rmb"] is True


def test_refresh_preserves_the_remember_window(client):
    """Refresh renews the SAME window — a short token can never be escalated
    into a remembered one, and a remembered token stays remembered."""
    signup(client, "parent@example.com")

    # default (30-min) session refreshes to another 30-min session
    login = client.post(
        "/auth/login", json={"email": "parent@example.com", "password": "Password123!"}
    ).json()
    short = client.post(
        "/auth/refresh", headers={"Authorization": f"Bearer {login['access_token']}"}
    )
    assert short.status_code == 200
    body = short.json()
    assert body["expires_in_seconds"] == settings.session_ttl_minutes * 60
    assert _claims(body["access_token"])["rmb"] is False

    # remembered (30-day) session refreshes to another 30-day session
    login = client.post(
        "/auth/login",
        json={
            "email": "parent@example.com",
            "password": "Password123!",
            "remember_me": True,
        },
    ).json()
    long = client.post(
        "/auth/refresh", headers={"Authorization": f"Bearer {login['access_token']}"}
    )
    assert long.status_code == 200
    body = long.json()
    assert body["expires_in_seconds"] == settings.remember_me_ttl_days * 24 * 60 * 60
    assert _claims(body["access_token"])["rmb"] is True


def test_refresh_requires_a_valid_unexpired_token(client):
    # no credentials at all
    assert client.post("/auth/refresh").status_code == 401

    parent = signup(client, "parent@example.com")
    me = client.get("/auth/me", headers=parent).json()

    # a still-valid session can refresh
    assert client.post("/auth/refresh", headers=parent).status_code == 200

    # an expired token cannot — it is rejected with the session_expired 401
    expired = jwt.encode(
        {
            "sub": me["id"],
            "rmb": False,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    r = client.post("/auth/refresh", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401
    assert r.json()["detail"] == {"code": "session_expired"}


def test_refresh_refuses_impersonation_tokens(client):
    """An admin impersonation token authenticates as the user, but must NOT be
    refreshable: doing so would slide it past its hard time cap and strip its
    'imp' audit marker (laundering it into a first-class session)."""
    import uuid

    from app.security import create_impersonation_token

    parent = signup(client, "parent@example.com")
    me = client.get("/auth/me", headers=parent).json()

    imp_token = create_impersonation_token(uuid.UUID(me["id"]), uuid.uuid4())
    imp_headers = {"Authorization": f"Bearer {imp_token}"}

    # the impersonation token still works as an ordinary credential...
    assert client.get("/auth/me", headers=imp_headers).status_code == 200
    # ...but cannot be refreshed into a fresh (imp-stripped) session token.
    r = client.post("/auth/refresh", headers=imp_headers)
    assert r.status_code == 403
