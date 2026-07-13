"""Time-capsule governance: content protection, age→date, life-moment votes,
and goal-linked release (spec #5–#8)."""

from .conftest import TestingSession, add_child, create_family, signup
from .test_capsules import seal_capsule
from .test_goals import make_grandparent
from .test_vault import upload_photo


def _make_child(client, headers, family_id, first_name, birthdate):
    r = client.post(
        f"/families/{family_id}/children",
        json={"first_name": first_name, "birthdate": birthdate, "parental_consent": True},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _relative(client, parent, family_id, email="uncle@example.com", name="Uncle"):
    from app.models import FamilyInvite

    client.post(
        f"/families/{family_id}/invites",
        json={"email": email, "role": "relative"},
        headers=parent,
    )
    with TestingSession() as db:
        token = db.query(FamilyInvite).filter(FamilyInvite.email == email).first().token
    headers = signup(client, email, name)
    client.post("/invites/accept", json={"token": token}, headers=headers)
    return headers


# --- #5 sealed capsule media is unfetchable by anyone but the creator ---

def test_sealed_capsule_media_download_blocked(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")
    media_id = upload_photo(client, gran, child_id)

    seal_capsule(client, gran, child_id, type="video", body=None, media_id=media_id)

    gran_token = gran["Authorization"].removeprefix("Bearer ")
    parent_token = parent["Authorization"].removeprefix("Bearer ")
    # The creator can still fetch their own sealed capsule's attachment
    assert client.get(f"/media/{media_id}?token={gran_token}").status_code == 200
    # A parent (or anyone else) cannot, even with the direct media URL
    assert client.get(f"/media/{media_id}?token={parent_token}").status_code == 404


# --- #6 "at an age" stores a concrete release date ---

def test_age_capsule_stores_computed_date(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = _make_child(client, parent, family_id, "Emma", "2018-05-01")

    r = seal_capsule(client, parent, child_id, release_age=10)
    assert r.status_code == 201
    assert r.json()["release_date"] == "2028-05-01"
    assert r.json()["release_age"] == 10


def test_leap_day_birth_falls_back_to_march_first(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = _make_child(client, parent, family_id, "Leap", "2016-02-29")

    r = seal_capsule(client, parent, child_id, release_age=1)  # 2017 is not a leap year
    assert r.json()["release_date"] == "2017-03-01"


# --- #7 life-moment (milestone) release by two guardian votes ---

def test_milestone_two_votes_release(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")
    uncle = _relative(client, parent, family_id)

    capsule_id = seal_capsule(
        client,
        gran,
        child_id,
        release_condition="milestone",
        release_age=None,
        release_milestone="Graduation",
    ).json()["id"]

    # The creator can't vote (they'd release directly), a supporter can't reach here
    assert client.post(f"/capsules/{capsule_id}/vote-release", headers=gran).status_code == 403

    # First guardian vote records, capsule stays sealed
    r = client.post(f"/capsules/{capsule_id}/vote-release", headers=parent)
    assert r.status_code == 200, r.text
    assert r.json()["release_votes"] == 1
    assert r.json()["i_voted"] is True
    assert r.json()["status"] == "sealed"

    # Same guardian voting again is a conflict, not a second vote
    assert client.post(f"/capsules/{capsule_id}/vote-release", headers=parent).status_code == 409

    # A second, distinct guardian tips it open
    r = client.post(f"/capsules/{capsule_id}/vote-release", headers=uncle)
    assert r.status_code == 200
    assert r.json()["release_votes"] == 2
    assert r.json()["status"] == "released"


def test_vote_only_valid_for_milestone(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")

    # gran seals an age capsule; parent (guardian, non-creator) tries to vote
    capsule_id = seal_capsule(client, gran, child_id, release_age=18).json()["id"]
    assert client.post(f"/capsules/{capsule_id}/vote-release", headers=parent).status_code == 422


def test_can_vote_flag(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)
    gran = make_grandparent(client, parent, family_id, name="Gran")

    seal_capsule(
        client,
        gran,
        child_id,
        release_condition="milestone",
        release_age=None,
        release_milestone="Graduation",
    )
    # The creator sees can_vote False; a guardian who isn't the creator sees True
    assert client.get(f"/children/{child_id}/capsules", headers=gran).json()[0]["can_vote"] is False
    assert client.get(f"/children/{child_id}/capsules", headers=parent).json()[0]["can_vote"] is True


# --- #8 goal-linked capsule releases when the goal is completed ---

def test_goal_linked_capsule_auto_releases(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id)

    goal_id = client.post(
        f"/children/{child_id}/goals",
        json={"title": "Learn to swim", "reward_type": "badge"},
        headers=parent,
    ).json()["id"]

    capsule_id = seal_capsule(
        client,
        parent,
        child_id,
        release_condition="goal",
        release_age=None,
        release_goal_id=goal_id,
    ).json()["id"]
    assert client.get(f"/children/{child_id}/capsules", headers=parent).json()[0][
        "release_goal_title"
    ] == "Learn to swim"

    # Completing the goal opens the linked capsule
    client.post(f"/goals/{goal_id}/complete", json={}, headers=parent)
    capsule = [
        c
        for c in client.get(f"/children/{child_id}/capsules", headers=parent).json()
        if c["id"] == capsule_id
    ][0]
    assert capsule["status"] == "released"
    assert capsule["body"] is not None


def test_goal_link_validation(client):
    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    emma = add_child(client, parent, family_id, "Emma")
    liam = add_child(client, parent, family_id, "Liam")

    emma_goal = client.post(
        f"/children/{emma}/goals",
        json={"title": "Read", "reward_type": "badge"},
        headers=parent,
    ).json()["id"]

    # Goal belongs to a different child → 422
    assert seal_capsule(
        client,
        parent,
        liam,
        release_condition="goal",
        release_age=None,
        release_goal_id=emma_goal,
    ).status_code == 422

    # Missing goal id → 422
    assert seal_capsule(
        client, parent, emma, release_condition="goal", release_age=None
    ).status_code == 422

    # A completed goal can't be linked → 422
    client.post(f"/goals/{emma_goal}/complete", json={}, headers=parent)
    assert seal_capsule(
        client,
        parent,
        emma,
        release_condition="goal",
        release_age=None,
        release_goal_id=emma_goal,
    ).status_code == 422
