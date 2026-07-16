"""Media auth hardening: media URLs carry a short-lived media-ONLY token, never
the account's session JWT. The scoped token works solely on GET /media/{id};
the session JWT no longer works in any query string."""

import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings
from app.security import MEDIA_TOKEN_AUDIENCE, decode_access_token

from .conftest import add_child, create_family, media_token, signup
from .test_vault import PNG_BYTES, upload_photo


def _setup_media(client):
    """Parent + child + one uploaded photo; returns (parent_headers, media_id)."""
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    return parent, upload_photo(client, parent, child_id)


def test_media_token_grants_media_access(client):
    parent, media_id = _setup_media(client)
    tok = media_token(client, parent)
    r = client.get(f"/media/{media_id}?token={tok}")
    assert r.status_code == 200
    assert r.content == PNG_BYTES


def test_minting_requires_a_session(client):
    assert client.post("/auth/media-token").status_code == 401


def test_access_jwt_rejected_in_media_query_string(client):
    """The old pattern — full session JWT as ?token= — must be dead."""
    parent, media_id = _setup_media(client)
    access_jwt = parent["Authorization"].removeprefix("Bearer ")
    assert client.get(f"/media/{media_id}?token={access_jwt}").status_code == 401


def test_bearer_access_token_still_works_for_api_clients(client):
    """Non-browser clients keep header auth on the media route."""
    parent, media_id = _setup_media(client)
    assert client.get(f"/media/{media_id}", headers=parent).status_code == 200


def test_media_token_rejected_as_bearer_on_other_endpoints(client):
    """The scoped token is NOT a session: the standard bearer decode refuses it
    everywhere else, so a leaked media URL can never operate the account."""
    parent, _ = _setup_media(client)
    tok = media_token(client, parent)
    scoped = {"Authorization": f"Bearer {tok}"}
    assert client.get("/auth/me", headers=scoped).status_code == 401
    assert client.get("/families", headers=scoped).status_code == 401
    # ...and it can't even mint a fresh media token for itself.
    assert client.post("/auth/media-token", headers=scoped).status_code == 401
    # unit-level: the access-token decoder returns None for it
    assert decode_access_token(tok) is None


def test_media_token_rejected_as_bearer_on_media_route(client):
    """Belt and suspenders: even in the Authorization header, only a real
    session works — the scoped token lives in the query string alone."""
    parent, media_id = _setup_media(client)
    tok = media_token(client, parent)
    r = client.get(f"/media/{media_id}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_expired_media_token_rejected(client):
    parent, media_id = _setup_media(client)
    me = client.get("/auth/me", headers=parent).json()
    expired = jwt.encode(
        {
            "sub": me["id"],
            "aud": MEDIA_TOKEN_AUDIENCE,
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert client.get(f"/media/{media_id}?token={expired}").status_code == 401


def test_forged_audience_or_garbage_tokens_rejected(client):
    parent, media_id = _setup_media(client)
    me = client.get("/auth/me", headers=parent).json()
    wrong_aud = jwt.encode(
        {
            "sub": me["id"],
            "aud": "futureroots:something-else",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert client.get(f"/media/{media_id}?token={wrong_aud}").status_code == 401
    assert client.get(f"/media/{media_id}?token=not-a-jwt").status_code == 401


def test_media_token_of_outsider_cannot_reach_foreign_media(client):
    """Authorization semantics are unchanged: the token authenticates, but
    every fetch still runs the full per-media access checks — an outsider's
    perfectly valid media token gets a 404 (existence never leaks)."""
    _, media_id = _setup_media(client)
    outsider = signup(client, "outsider@example.com")
    tok = media_token(client, outsider)
    assert client.get(f"/media/{media_id}?token={tok}").status_code == 404


def test_media_token_for_unknown_user_rejected(client):
    """A validly signed token whose subject no longer exists is a 401."""
    _, media_id = _setup_media(client)
    ghost = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": MEDIA_TOKEN_AUDIENCE,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert client.get(f"/media/{media_id}?token={ghost}").status_code == 401


def test_mint_response_shape(client):
    parent = signup(client, "parent@example.com")
    body = client.post("/auth/media-token", headers=parent).json()
    assert body["expires_in_seconds"] == settings.media_token_ttl_minutes * 60
    # the token really is aud-scoped (decoded without signature verification
    # only to inspect claims)
    claims = jwt.decode(body["media_token"], options={"verify_signature": False})
    assert claims["aud"] == MEDIA_TOKEN_AUDIENCE
