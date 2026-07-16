from .conftest import TestingSession, add_child, create_family, setup_fund, signup


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


def _succeeded_contribution(client, parent, child_id, amount=2500):
    c = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": amount}, headers=parent
    ).json()
    client.post(f"/contributions/{c['id']}/confirm", headers=parent)
    return c


def test_refund_reverses_ledger(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    c = _succeeded_contribution(client, parent, child_id, 2500)

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 2500 - 103  # net of the 2.9% + 30¢ fee

    r = client.post(f"/admin/contributions/{c['id']}/refund", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "refunded"

    fund = client.get(f"/children/{child_id}/fund", headers=parent).json()
    assert fund["balance_cents"] == 0  # compensating entry reverses it
    assert len(fund["entries"]) == 2  # original + adjustment (append-only)

    # a second refund is refused (not succeeded anymore)
    assert client.post(f"/admin/contributions/{c['id']}/refund", headers=admin).status_code == 409


def test_partial_refunds_accumulate(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    c = _succeeded_contribution(client, parent, child_id, 3000)  # net 2883 after 117 fee

    assert client.get(f"/children/{child_id}/fund", headers=parent).json()["balance_cents"] == 2883

    # partial refund of 1000 gross -> ~961 net reversed
    r = client.post(f"/admin/contributions/{c['id']}/refund", json={"amount_cents": 1000}, headers=admin)
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"  # still partially live
    assert r.json()["refunded_cents"] == 1000
    assert client.get(f"/children/{child_id}/fund", headers=parent).json()["balance_cents"] == 2883 - 961

    # over-refund is rejected
    assert client.post(
        f"/admin/contributions/{c['id']}/refund", json={"amount_cents": 5000}, headers=admin
    ).status_code == 422

    # refund the remaining 2000 -> fully refunded, balance exactly 0
    r = client.post(f"/admin/contributions/{c['id']}/refund", json={"amount_cents": 2000}, headers=admin)
    assert r.json()["status"] == "refunded" and r.json()["refunded_cents"] == 3000
    assert client.get(f"/children/{child_id}/fund", headers=parent).json()["balance_cents"] == 0


def test_contribution_status_filter_and_csv(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    _succeeded_contribution(client, parent, child_id)

    r = client.get("/admin/contributions?status=succeeded", headers=admin)
    assert r.status_code == 200 and r.json()["total"] >= 1
    assert client.get("/admin/contributions?status=refunded", headers=admin).json()["total"] == 0

    csv_resp = client.get("/admin/contributions.csv", headers=admin)
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "contributor_email" in csv_resp.text


def test_impersonation(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com", "Pat")
    from app.models import User

    with TestingSession() as db:
        parent_id = str(db.query(User).filter(User.email == "parent@example.com").first().id)
        admin_id = str(db.query(User).filter(User.email == "admin@example.com").first().id)

    r = client.post(f"/admin/users/{parent_id}/impersonate", headers=admin)
    assert r.status_code == 200
    imp_token = r.json()["access_token"]
    # the token acts as the impersonated user
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {imp_token}"})
    assert me.json()["email"] == "parent@example.com"
    # cannot impersonate another admin
    assert client.post(f"/admin/users/{admin_id}/impersonate", headers=admin).status_code == 400


def test_audit_log_lists_actions(client):
    admin = make_admin(client)
    parent = signup(client, "parent@example.com")
    from app.models import User

    with TestingSession() as db:
        parent_id = str(db.query(User).filter(User.email == "parent@example.com").first().id)
    client.post(f"/admin/users/{parent_id}/impersonate", headers=admin)

    r = client.get("/admin/audit", headers=admin)
    assert r.status_code == 200
    actions = [row["action"] for row in r.json()["items"]]
    assert "impersonate" in actions
    assert all(row["admin_email"] == "admin@example.com" for row in r.json()["items"])

    # action filter narrows the list
    r = client.get("/admin/audit?action=impersonate", headers=admin)
    assert r.status_code == 200 and r.json()["total"] >= 1
    assert all(row["action"] == "impersonate" for row in r.json()["items"])
    assert client.get("/admin/audit?action=nope_none", headers=admin).json()["total"] == 0

    # distinct actions + CSV
    assert "impersonate" in client.get("/admin/audit/actions", headers=admin).json()
    csv_resp = client.get("/admin/audit.csv", headers=admin)
    assert csv_resp.status_code == 200 and "text/csv" in csv_resp.headers["content-type"]


def test_disable_and_enable_user(client):
    admin = make_admin(client)
    signup(client, "target@example.com")
    from app.models import User

    with TestingSession() as db:
        tid = str(db.query(User).filter(User.email == "target@example.com").first().id)
        aid = str(db.query(User).filter(User.email == "admin@example.com").first().id)

    # disable -> login blocked (403) and any live token is rejected
    assert client.post(f"/admin/users/{tid}/status", json={"disabled": True}, headers=admin).status_code == 200
    login = client.post("/auth/login", json={"email": "target@example.com", "password": "Password123!"})
    assert login.status_code == 403

    # re-enable -> can log in again
    assert client.post(f"/admin/users/{tid}/status", json={"disabled": False}, headers=admin).status_code == 200
    assert client.post(
        "/auth/login", json={"email": "target@example.com", "password": "Password123!"}
    ).status_code == 200

    # an admin can't disable themselves (lockout guard)
    assert client.post(f"/admin/users/{aid}/status", json={"disabled": True}, headers=admin).status_code == 400


def test_reconcile_pending_contribution(client, monkeypatch):
    # local provider reports "succeeded"; a pending contribution reconciles to settled
    from app.services import payments as pay

    admin = make_admin(client)
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    # create (pending) but do NOT confirm -> stuck pending like a missed webhook
    c = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 1000}, headers=parent
    ).json()

    monkeypatch.setattr(pay._provider, "payment_status", lambda contribution: "canceled")
    r = client.post(f"/admin/contributions/{c['id']}/reconcile", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "failed"


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


def test_void_premium_grant_clears_message(client):
    """Voiding a refunded gift also nulls its free-text message (which may name
    a child) — a voided grant is no longer displayed and shouldn't retain PII.
    voided_at + message-null are the only permitted mutations."""
    import uuid
    from datetime import timedelta

    from app.models import PremiumGrant, User, utcnow

    admin = make_admin(client)
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Salignas")

    with TestingSession() as db:
        parent_id = db.query(User).filter(User.email == "parent@example.com").one().id
        grant = PremiumGrant(
            id=uuid.uuid4(),
            family_id=uuid.UUID(family_id),
            source="gift",
            granted_by_user_id=parent_id,
            stripe_checkout_session_id="cs_void_test",
            amount_cents=9900,
            currency="USD",
            message="For Emma's recital videos",
            starts_at=utcnow(),
            ends_at=utcnow() + timedelta(days=365),
        )
        db.add(grant)
        db.commit()
        grant_id = str(grant.id)

    r = client.post(f"/admin/premium-grants/{grant_id}/void", headers=admin)
    assert r.status_code == 200, r.text

    with TestingSession() as db:
        row = db.query(PremiumGrant).filter(PremiumGrant.id == uuid.UUID(grant_id)).one()
        assert row.voided_at is not None
        assert row.voided_by_user_id is not None
        assert row.message is None  # PII cleared

    # Idempotency: a second void is a 409 (already voided), message stays null.
    r = client.post(f"/admin/premium-grants/{grant_id}/void", headers=admin)
    assert r.status_code == 409
