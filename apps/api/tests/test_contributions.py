from .conftest import TestingSession, add_child, create_family, setup_fund, signup
from .test_goals import make_grandparent


def contribute(client, headers, child_id, amount_cents=2500, **kwargs):
    r = client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": amount_cents, **kwargs},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_grandparent_contribution_full_flow(client, tmp_path, monkeypatch):
    """The north star: contribute → verified settle → ledger → feed → parents told."""
    from app.services import email as email_module

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    setup_fund(client, parent, child_id)
    gran = make_grandparent(client, parent, family_id, name="Grandma Rose")
    for f in outbox.glob("*.txt"):
        f.unlink()

    c = contribute(client, gran, child_id, amount_cents=2500, message="So proud of you!")
    assert c["status"] == "pending"
    assert c["fee_cents"] == 103  # ceil(2.9% of 2500) + 30¢

    r = client.post(f"/contributions/{c['id']}/confirm", headers=gran)
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"

    # Ledger: net of fee, balance derived
    r = client.get(f"/children/{child_id}/fund", headers=parent)
    assert r.status_code == 200
    fund = r.json()
    assert fund["balance_cents"] == 2500 - 103
    assert fund["account_status"] == "active"
    assert fund["setup_by_name"] == "Pat"
    assert len(fund["entries"]) == 1
    assert fund["entries"][0]["contributor_name"] == "Grandma Rose"
    assert fund["entries"][0]["message"] == "So proud of you!"

    # Feed shows the celebration
    r = client.get(f"/families/{family_id}/feed", headers=parent)
    assert r.json()[0]["type"] == "contribution"
    assert r.json()[0]["payload"]["amount_cents"] == 2500

    # Pat (parent) was emailed; Grandma Rose (actor) was not
    emails = [f.read_text(encoding="utf-8") for f in sorted(outbox.glob("*.txt"))]
    assert len(emails) == 1
    assert "To: parent@example.com" in emails[0]
    assert "Emma" in emails[0]


def test_confirm_is_idempotent(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    c = contribute(client, parent, child_id)

    assert client.post(f"/contributions/{c['id']}/confirm", headers=parent).status_code == 200
    assert client.post(f"/contributions/{c['id']}/confirm", headers=parent).status_code == 409

    r = client.get(f"/children/{child_id}/fund", headers=parent)
    assert len(r.json()["entries"]) == 1  # exactly one ledger entry


def test_balance_accumulates_across_contributions(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)

    expected = 0
    for amount in (1000, 2500, 5000):
        c = contribute(client, parent, child_id, amount_cents=amount)
        client.post(f"/contributions/{c['id']}/confirm", headers=parent)
        expected += amount - (-(-amount * 290 // 10_000) + 30)

    r = client.get(f"/children/{child_id}/fund", headers=parent)
    assert r.json()["balance_cents"] == expected
    assert len(r.json()["entries"]) == 3


def test_outsider_cannot_contribute_or_view_fund(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)

    outsider = signup(client, "outsider@example.com")
    r = client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": 2500},
        headers=outsider,
    )
    assert r.status_code == 404
    assert client.get(f"/children/{child_id}/fund", headers=outsider).status_code == 404


def test_cannot_confirm_someone_elses_contribution(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    gran = make_grandparent(client, parent, family_id)
    c = contribute(client, gran, child_id)

    # Even another family member can't settle someone else's payment
    assert client.post(f"/contributions/{c['id']}/confirm", headers=parent).status_code == 404


def test_minimum_contribution_enforced(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    r = client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": 50},
        headers=parent,
    )
    assert r.status_code == 422


def test_ledger_is_append_only_no_updates(client):
    """Guard the discipline at the ORM level: simulate a correction and verify
    it's a new compensating entry, never an update."""
    from app.models import FundLedgerEntry, LedgerEntryType

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    setup_fund(client, parent, child_id)
    c = contribute(client, parent, child_id, amount_cents=1000)
    client.post(f"/contributions/{c['id']}/confirm", headers=parent)

    with TestingSession() as db:
        entry = db.query(FundLedgerEntry).one()
        db.add(
            FundLedgerEntry(
                account_id=entry.account_id,
                amount_cents=-entry.amount_cents,
                entry_type=LedgerEntryType.adjustment,
            )
        )
        db.commit()

    r = client.get(f"/children/{child_id}/fund", headers=parent)
    assert r.json()["balance_cents"] == 0
    assert len(r.json()["entries"]) == 2
