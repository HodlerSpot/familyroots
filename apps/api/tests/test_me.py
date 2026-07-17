"""Notification preferences (email discipline) and the caller's own
contribution history."""

from app.services.notifications import DEFAULT_PREFS

from .conftest import add_child, create_family, setup_fund, signup
from .test_goals import make_grandparent


def prefs(**overrides) -> dict:
    """A full 20-field preferences payload for PUT /me/notifications, starting
    from the product defaults."""
    payload = dict(DEFAULT_PREFS)
    payload.update(overrides)
    return payload


def test_notification_defaults(client):
    parent = signup(client, "parent@example.com")
    r = client.get("/me/notifications", headers=parent)
    assert r.status_code == 200
    body = r.json()
    # Defaults + the read-only VAPID public key ("" ⇒ push dark in dev/tests).
    assert body == {**DEFAULT_PREFS, "push_public_key": ""}


def test_notification_prefs_persist(client):
    parent = signup(client, "parent@example.com")
    payload = prefs(
        email_new_member=False,
        email_milestone=False,
        email_memory=True,
        email_legacy=True,
        push_call_live=False,
        push_announcements=False,
    )
    r = client.put("/me/notifications", json=payload, headers=parent)
    assert r.status_code == 200
    expected = {**payload, "push_public_key": ""}
    assert r.json() == expected
    assert client.get("/me/notifications", headers=parent).json() == expected


def test_milestone_email_respects_opt_out(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    # Gran opts out of milestone emails
    client.put("/me/notifications", json=prefs(email_milestone=False), headers=gran)
    for f in outbox.glob("*.txt"):
        f.unlink()

    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    # Nobody left to email: Pat is the actor, Gran opted out
    assert list(outbox.glob("*.txt")) == []


def test_new_memory_email_opt_in(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_grandparent(client, parent, family_id, name="Gran")
    # Memory emails are off by default; Gran opts in
    client.put("/me/notifications", json=prefs(email_memory=True), headers=gran)
    for f in outbox.glob("*.txt"):
        f.unlink()

    client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "A little moment"},
        headers=parent,
    )
    emails = [f.read_text(encoding="utf-8") for f in outbox.glob("*.txt")]
    assert len(emails) == 1
    assert "To: gran@example.com" in emails[0]


def test_new_member_email_to_existing_members(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    for f in outbox.glob("*.txt"):
        f.unlink()
    # Gran joining emails Pat (an existing member, default on)
    make_grandparent(client, parent, family_id, name="Gran")
    emails = [f.read_text(encoding="utf-8") for f in outbox.glob("*.txt")]
    joined = [e for e in emails if "joined" in e]
    assert any("To: parent@example.com" in e for e in joined)


def test_my_contributions(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent, "The Salignas")
    child_id = add_child(client, parent, family_id, "Emma")
    setup_fund(client, parent, child_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")

    client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": 2500, "message": "For you"},
        headers=gran,
    )

    r = client.get("/me/contributions", headers=gran)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["child_name"] == "Emma"
    assert rows[0]["family_name"] == "The Salignas"
    assert rows[0]["amount_cents"] == 2500
    assert rows[0]["fee_cents"] == 103  # what the platform kept, visible to the giver
    assert rows[0]["message"] == "For you"
    assert rows[0]["refunded_cents"] == 0

    # Only your own contributions — the parent made none
    assert client.get("/me/contributions", headers=parent).json() == []
