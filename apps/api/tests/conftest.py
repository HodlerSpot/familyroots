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
        json={"email": email, "display_name": name, "password": "password123"},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


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
