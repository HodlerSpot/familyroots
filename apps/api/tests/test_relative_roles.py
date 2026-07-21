"""Aunt / Uncle / Cousin are relative-tier roles: permission-identical to
`relative`. This is the parity matrix proving each behaves exactly like a full
(non-supporter) family member, plus a supporter no-regression guard."""

import pytest

from .conftest import (
    TestingSession,
    add_child,
    create_family,
    make_member,
    setup_fund,
    signup,
)
from .test_capsules import seal_capsule

RELATIVE_TIER_ROLES = ["aunt", "uncle", "cousin"]


@pytest.fixture()
def family_with_child(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    return parent, family_id, child_id


@pytest.mark.parametrize("role", RELATIVE_TIER_ROLES)
def test_relative_tier_reaches_family_only_surfaces(client, family_with_child, role):
    """(a) require_not_supporter surfaces — funds, capsules, goals, legacy — are
    all visible, and non-supporter writes (memory, capsule) are allowed."""
    parent, family_id, child_id = family_with_child
    member = make_member(client, parent, family_id, role, f"{role}@example.com", role.title())

    assert client.get(f"/children/{child_id}/fund", headers=member).status_code == 200
    assert client.get(f"/children/{child_id}/capsules", headers=member).status_code == 200
    assert client.get(f"/children/{child_id}/goals", headers=member).status_code == 200
    assert client.get(f"/children/{child_id}/badges", headers=member).status_code == 200
    assert client.get(f"/families/{family_id}/legacy", headers=member).status_code == 200

    assert client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": "So proud of you"},
        headers=member,
    ).status_code == 201
    assert seal_capsule(client, member, child_id).status_code == 201


@pytest.mark.parametrize("role", RELATIVE_TIER_ROLES)
def test_relative_tier_denied_guardian_actions(client, family_with_child, role):
    """(b) require_guardian_role actions — invite, create-child, manage goals —
    are denied (403), exactly like a relative."""
    parent, family_id, child_id = family_with_child
    member = make_member(client, parent, family_id, role, f"{role}@example.com", role.title())

    assert client.post(
        f"/families/{family_id}/invites",
        json={"email": "someone@example.com", "role": "relative"},
        headers=member,
    ).status_code == 403
    assert client.post(
        f"/families/{family_id}/children",
        json={"first_name": "Liam", "birthdate": "2020-01-01", "parental_consent": True},
        headers=member,
    ).status_code == 403
    assert client.post(
        f"/children/{child_id}/goals",
        json={"title": "Read 10 books", "reward_type": "badge"},
        headers=member,
    ).status_code == 403


@pytest.mark.parametrize("role", RELATIVE_TIER_ROLES)
def test_relative_tier_can_vote_to_release_milestone_capsule(client, family_with_child, role):
    """(c) GUARDIAN_ROLES gate: the new roles can vote a life-moment capsule
    open, and their votes count toward release (two distinct votes)."""
    parent, family_id, child_id = family_with_child
    capsule_id = seal_capsule(
        client,
        parent,
        child_id,
        release_condition="milestone",
        release_age=None,
        release_milestone="Graduation day",
    ).json()["id"]

    voter_a = make_member(client, parent, family_id, role, f"{role}-a@example.com", role.title())
    voter_b = make_member(client, parent, family_id, role, f"{role}-b@example.com", role.title())

    r = client.post(f"/capsules/{capsule_id}/vote-release", headers=voter_a)
    assert r.status_code == 200, r.text
    assert r.json()["i_voted"] is True
    assert r.json()["status"] == "sealed"  # one vote is not enough

    r = client.post(f"/capsules/{capsule_id}/vote-release", headers=voter_b)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "released"  # two distinct guardian votes open it


@pytest.mark.parametrize("role", RELATIVE_TIER_ROLES)
def test_relative_tier_sees_full_feed_and_birthdate(client, family_with_child, role):
    """(d) full, non-supporter feed (milestone + contribution visible) and the
    child's birthdate — the sensitive slice a supporter never gets."""
    parent, family_id, child_id = family_with_child
    client.post(
        f"/children/{child_id}/milestones", json={"title": "First steps"}, headers=parent
    )
    setup_fund(client, parent, child_id)
    c = client.post(
        f"/children/{child_id}/contributions", json={"amount_cents": 2500}, headers=parent
    ).json()
    client.post(f"/contributions/{c['id']}/confirm", headers=parent)

    member = make_member(client, parent, family_id, role, f"{role}@example.com", role.title())

    types = {e["type"] for e in client.get(f"/families/{family_id}/feed", headers=member).json()}
    assert "milestone" in types
    assert "contribution" in types

    detail = client.get(f"/families/{family_id}", headers=member).json()
    assert detail["children"][0]["birthdate"] is not None
    kids = client.get(f"/families/{family_id}/children", headers=member).json()
    assert kids[0]["birthdate"] is not None


@pytest.mark.parametrize("role", RELATIVE_TIER_ROLES)
def test_relative_tier_invite_round_trips(client, family_with_child, role):
    """(e) an invite with the new role previews, accepts, and persists to both
    FamilyMember.role and the Family Graph edge (ChildRelationship)."""
    from app.models import ChildRelationship, FamilyInvite, FamilyMember, FamilyRole

    parent, family_id, child_id = family_with_child
    email = f"{role}@example.com"

    r = client.post(
        f"/families/{family_id}/invites", json={"email": email, "role": role}, headers=parent
    )
    assert r.status_code == 201, r.text
    with TestingSession() as db:
        token = db.query(FamilyInvite).filter(FamilyInvite.email == email).first().token

    preview = client.get(f"/invites/{token}")
    assert preview.status_code == 200
    assert preview.json()["role"] == role

    member = signup(client, email, role.title())
    accept = client.post("/invites/accept", json={"token": token}, headers=member)
    assert accept.status_code == 200, accept.text
    assert accept.json()["role"] == role

    with TestingSession() as db:
        assert (
            db.query(FamilyMember).filter(FamilyMember.role == FamilyRole(role)).count() == 1
        )
        assert (
            db.query(ChildRelationship)
            .filter(ChildRelationship.relationship_type == FamilyRole(role))
            .count()
            == 1
        )


def test_supporter_regression_still_locked_out(client, family_with_child):
    """No regression: a supporter still CANNOT reach family-only surfaces (a)
    or vote to release a capsule (c)."""
    parent, family_id, child_id = family_with_child
    capsule_id = seal_capsule(
        client,
        parent,
        child_id,
        release_condition="milestone",
        release_age=None,
        release_milestone="Graduation day",
    ).json()["id"]

    supporter = make_member(client, parent, family_id, "supporter", "coach@example.com", "Coach")

    # (a) family-only surfaces stay blocked
    assert client.get(f"/children/{child_id}/fund", headers=supporter).status_code == 403
    assert client.get(f"/children/{child_id}/capsules", headers=supporter).status_code == 403
    assert client.get(f"/children/{child_id}/goals", headers=supporter).status_code == 403
    assert client.get(f"/families/{family_id}/legacy", headers=supporter).status_code == 403

    # (c) supporters cannot vote to open a capsule
    assert client.post(
        f"/capsules/{capsule_id}/vote-release", headers=supporter
    ).status_code == 403
