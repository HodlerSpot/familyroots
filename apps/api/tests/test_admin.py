from .conftest import TestingSession, add_child, create_family, signup


def make_admin(client, email="admin@example.com"):
    headers = signup(client, email, "Admin")
    from app.models import User, UserRole

    with TestingSession() as db:
        u = db.query(User).filter(User.email == email).first()
        u.role = UserRole.admin
        db.commit()
    return headers


def test_admin_gate_blocks_regular_users(client):
    user = signup(client, "user@example.com")
    assert client.get("/admin/overview", headers=user).status_code == 403
    assert client.get("/admin/users", headers=user).status_code == 403
    assert client.get("/admin/overview").status_code == 401


def test_overview_metrics(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id, "Emma")

    r = client.get("/admin/overview", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["users"] >= 2
    assert body["admins"] == 1
    assert body["families"] >= 1
    assert body["children"] >= 1
    assert any(u["email"] == "parent@example.com" for u in body["recent_signups"])


def test_users_and_family_detail(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Testers")
    add_child(client, parent, family_id, "Emma")

    r = client.get("/admin/users", headers=admin)
    assert r.status_code == 200
    assert r.json()["total"] >= 2
    parent_row = next(u for u in r.json()["items"] if u["email"] == "parent@example.com")
    assert parent_row["family_count"] == 1
    assert parent_row["child_count"] == 1

    r = client.get(f"/admin/families/{family_id}", headers=admin)
    assert r.status_code == 200
    assert r.json()["name"] == "The Testers"
    assert r.json()["children"][0]["first_name"] == "Emma"


def test_role_management_and_self_protection(client):
    admin = make_admin(client)
    from app.models import User

    with TestingSession() as db:
        admin_id = str(db.query(User).filter(User.email == "admin@example.com").first().id)
    target = signup(client, "promote-me@example.com")
    with TestingSession() as db:
        target_id = str(db.query(User).filter(User.email == "promote-me@example.com").first().id)

    # promote a user to admin
    r = client.post(f"/admin/users/{target_id}/role", json={"role": "admin"}, headers=admin)
    assert r.status_code == 200 and r.json()["role"] == "admin"

    # an admin cannot strip their own admin access (avoid lockout)
    r = client.post(f"/admin/users/{admin_id}/role", json={"role": "user"}, headers=admin)
    assert r.status_code == 400

    # audit log recorded the promotion
    from app.models import AdminAuditLog

    with TestingSession() as db:
        assert db.query(AdminAuditLog).filter(AdminAuditLog.action == "role_changed").count() >= 1
