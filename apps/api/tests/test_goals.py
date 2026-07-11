from .conftest import TestingSession, add_child, create_family, signup


def make_grandparent(client, parent, family_id, email="gran@example.com", name="Gran"):
    from app.models import FamilyInvite

    client.post(
        f"/families/{family_id}/invites",
        json={"email": email, "role": "grandparent"},
        headers=parent,
    )
    with TestingSession() as db:
        token = (
            db.query(FamilyInvite).filter(FamilyInvite.email == email).first().token
        )
    gran = signup(client, email, name)
    client.post("/invites/accept", json={"token": token}, headers=gran)
    return gran


def create_goal(client, headers, child_id, reward_type="badge", **kwargs):
    body = {"title": "Read 10 books", "reward_type": reward_type, **kwargs}
    return client.post(f"/children/{child_id}/goals", json=body, headers=headers)


def test_parent_creates_and_completes_goal_with_badge(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")

    r = create_goal(client, parent, child_id, reward_type="badge")
    assert r.status_code == 201, r.text
    goal_id = r.json()["id"]
    assert r.json()["status"] == "active"

    r = client.post(f"/goals/{goal_id}/complete", json={}, headers=parent)
    assert r.status_code == 200
    assert r.json()["status"] == "completed"
    assert r.json()["completed_at"] is not None

    # Badge awarded
    r = client.get(f"/children/{child_id}/badges", headers=parent)
    assert len(r.json()) == 1
    assert r.json()[0]["label"] == "Read 10 books"

    # Achievement on the feed
    r = client.get(f"/families/{family_id}/feed", headers=parent)
    assert r.json()[0]["type"] == "achievement"
    assert r.json()[0]["payload"]["title"] == "Read 10 books"


def test_goal_cannot_complete_twice(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    goal_id = create_goal(client, parent, child_id).json()["id"]

    assert client.post(f"/goals/{goal_id}/complete", json={}, headers=parent).status_code == 200
    assert client.post(f"/goals/{goal_id}/complete", json={}, headers=parent).status_code == 409


def test_money_reward_requires_amount(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    r = create_goal(client, parent, child_id, reward_type="fund_contribution")
    assert r.status_code == 422
    r = create_goal(
        client, parent, child_id, reward_type="fund_contribution", reward_amount_cents=500
    )
    assert r.status_code == 201


def test_grandparent_cannot_manage_goals(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    goal_id = create_goal(client, parent, child_id).json()["id"]
    gran = make_grandparent(client, parent, family_id)

    assert create_goal(client, gran, child_id).status_code == 403
    assert client.post(f"/goals/{goal_id}/complete", json={}, headers=gran).status_code == 403
    # ...but grandparents can see the goals
    assert client.get(f"/children/{child_id}/goals", headers=gran).status_code == 200


def test_outsider_cannot_see_goals(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    outsider = signup(client, "outsider@example.com")
    assert client.get(f"/children/{child_id}/goals", headers=outsider).status_code == 404
    assert create_goal(client, outsider, child_id).status_code == 404


def test_goal_completion_never_writes_ledger(client):
    """Money discipline: only settled payments reach the ledger."""
    from app.models import FundLedgerEntry

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    goal_id = create_goal(
        client, parent, child_id, reward_type="fund_contribution", reward_amount_cents=2500
    ).json()["id"]
    client.post(f"/goals/{goal_id}/complete", json={}, headers=parent)

    with TestingSession() as db:
        assert db.query(FundLedgerEntry).count() == 0
