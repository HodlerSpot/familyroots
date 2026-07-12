from .conftest import TestingSession, signup


def make_admin(client, email="admin@example.com"):
    headers = signup(client, email, "Admin")
    from app.models import User, UserRole

    with TestingSession() as db:
        u = db.query(User).filter(User.email == email).first()
        u.role = UserRole.admin
        db.commit()
    return headers


def test_issue_report_lands_in_admin_bugs(client):
    user = signup(client, "family@example.com", "Casey")
    r = client.post(
        "/issues", json={"title": "Photo upload spins forever", "body": "On the vault page."},
        headers=user,
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"

    admin = make_admin(client)
    bugs = client.get("/admin/bugs", headers=admin).json()
    mine = next(b for b in bugs if b["title"] == "Photo upload spins forever")
    assert "Casey" in mine["reporter"] and "family@example.com" in mine["reporter"]

    # admin can verify a user-reported issue (no points on the main site)
    r = client.post(f"/admin/bugs/{mine['id']}/verify", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "verified"


def test_issue_requires_auth(client):
    assert client.post("/issues", json={"title": "x", "body": "y"}).status_code == 401


def test_last_login_recorded(client):
    admin = make_admin(client)
    signup(client, "late@example.com", "Late Riser")

    row = next(
        u for u in client.get("/admin/users", headers=admin).json()["items"]
        if u["email"] == "late@example.com"
    )
    assert row["last_login_at"] is None  # signup issues a token but isn't a login

    client.post("/auth/login", json={"email": "late@example.com", "password": "Password123!"})
    row = next(
        u for u in client.get("/admin/users", headers=admin).json()["items"]
        if u["email"] == "late@example.com"
    )
    assert row["last_login_at"] is not None
