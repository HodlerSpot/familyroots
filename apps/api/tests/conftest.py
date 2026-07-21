import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.deps import get_db
from app.main import app

# SQLite in-memory keeps tests dependency-free; the schema is portable
# (native_enum=False, Uuid) by design. Integration runs against Postgres
# happen via FUTUREROOTS_DATABASE_URL when needed.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def isolated_outbox(tmp_path, monkeypatch):
    """Keep test emails out of the real dev outbox (apps/api/var/outbox)."""
    from app.services import email as email_module

    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(tmp_path))


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Keep test media out of the real dev media dir (apps/api/var/media)."""
    from app.services import storage as storage_module

    monkeypatch.setattr(
        storage_module, "_storage", storage_module.LocalDiskStorage(tmp_path / "media")
    )


@pytest.fixture()
def client():
    Base.metadata.create_all(engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def signup(client, email: str, name: str = "Test User") -> dict:
    """Create a user and return auth headers."""
    r = client.post(
        "/auth/signup",
        json={"email": email, "display_name": name, "password": "Password123!"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def media_token(client, headers: dict) -> str:
    """Exchange a session for the short-lived media-scoped token that media
    URLs carry as ?token= (the only credential /media/{id} accepts there)."""
    r = client.post("/auth/media-token", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["media_token"]


def create_family(client, headers: dict, name: str = "The Salignas") -> str:
    r = client.post("/families", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add_child(client, headers: dict, family_id: str, first_name: str = "Emma") -> str:
    r = client.post(
        f"/families/{family_id}/children",
        json={"first_name": first_name, "birthdate": "2018-05-01", "parental_consent": True},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_member(
    client,
    parent: dict,
    family_id: str,
    role: str,
    email: str,
    name: str = "Member",
) -> dict:
    """Run the full invite -> signup -> accept flow for any FamilyRole and
    return the new member's auth headers. Generalizes the per-role helpers
    (make_grandparent / make_supporter)."""
    from app.models import FamilyInvite

    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": email, "role": role},
        headers=parent,
    )
    assert r.status_code == 201, r.text
    with TestingSession() as db:
        token = db.query(FamilyInvite).filter(FamilyInvite.email == email).first().token
    member = signup(client, email, name)
    r = client.post("/invites/accept", json={"token": token}, headers=member)
    assert r.status_code == 200, r.text
    return member


def make_premium(client, parent_headers: dict, family_id: str, plan: str = "annual") -> None:
    """Upgrade a family to Premium under the local payment provider, which
    settles synchronously through the same settlement functions as the
    Stripe webhook."""
    r = client.post(
        f"/families/{family_id}/premium/checkout",
        json={"plan": plan},
        headers=parent_headers,
    )
    assert r.status_code == 200, r.text


def setup_fund(client, guardian_headers: dict, child_id: str) -> None:
    """Activate the child's Future Fund under the local provider: start setup
    (instant local Connect account), then poll status once (local accounts
    onboard instantly, so this flips the account to active)."""
    r = client.post(f"/children/{child_id}/fund/setup", headers=guardian_headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/children/{child_id}/fund/setup/status", headers=guardian_headers)
    assert r.status_code == 200, r.text
    assert r.json()["account_status"] == "active"
