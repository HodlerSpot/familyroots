from .conftest import add_child, create_family, signup


def _get_token(db_session_factory):
    from app.models import FamilyInvite

    with db_session_factory() as db:
        return db.query(FamilyInvite).first().token


def test_full_invite_flow(client):
    """North-star setup: parent creates family + child, invites grandparent,
    grandparent joins and can see the family and child."""
    from .conftest import TestingSession

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Salignas")
    add_child(client, parent, family_id, "Emma")

    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    assert r.status_code == 201
    token = _get_token(TestingSession)

    # Unauthenticated preview greets the grandparent with context
    r = client.get(f"/invites/{token}")
    assert r.status_code == 200
    assert r.json() == {
        "family_name": "The Salignas",
        "role": "grandparent",
        "invited_by": "Pat",
    }

    gran = signup(client, "gran@example.com", "Gran")
    r = client.post("/invites/accept", json={"token": token}, headers=gran)
    assert r.status_code == 200
    assert r.json()["role"] == "grandparent"

    # Grandparent now sees the family and Emma
    r = client.get(f"/families/{family_id}", headers=gran)
    assert r.status_code == 200
    assert r.json()["children"][0]["first_name"] == "Emma"

    # And has a Family Graph edge to Emma
    from app.models import ChildRelationship, FamilyRole

    with TestingSession() as db:
        edges = db.query(ChildRelationship).filter(
            ChildRelationship.relationship_type == FamilyRole.grandparent
        ).all()
        assert len(edges) == 1


def test_invite_email_written_to_outbox(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(tmp_path))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    for f in tmp_path.glob("*.txt"):
        f.unlink()  # drop the welcome email; this test is about the invite
    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    assert r.status_code == 201

    outbox = list(tmp_path.glob("*.txt"))
    assert len(outbox) == 1
    content = outbox[0].read_text(encoding="utf-8")
    assert "To: gran@example.com" in content
    assert "/invites/" in content
    # Brand rule: no crypto vocabulary in user-facing text
    for banned in ("wallet", "blockchain", "crypto", "token", "web3"):
        assert banned not in content.lower().replace("/invites/", "")


def test_family_phrase_never_doubles_articles():
    from app.services.text import family_phrase

    assert family_phrase("Smith") == "the Smith family"
    assert family_phrase("The Saliga Family") == "The Saliga Family"
    assert family_phrase("the saliga family") == "the saliga family"
    assert family_phrase("Saliga Family") == "the Saliga Family"
    assert family_phrase("Theodore") == "the Theodore family"  # "The" prefix ≠ "The "


def test_invite_email_grammar_with_the_prefixed_family(client, tmp_path, monkeypatch):
    from app.services import email as email_module

    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(tmp_path))
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent, "The Saliga Family")
    for f in tmp_path.glob("*.txt"):
        f.unlink()
    client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    content = next(tmp_path.glob("*.txt")).read_text(encoding="utf-8")
    assert "join The Saliga Family on FutureRoots" in content
    assert "the The" not in content
    assert "Family family" not in content


def test_invite_requires_parent_role(client):
    from .conftest import TestingSession

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    token = _get_token(TestingSession)
    gran = signup(client, "gran@example.com")
    client.post("/invites/accept", json={"token": token}, headers=gran)

    # Grandparent cannot invite others
    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": "other@example.com", "role": "relative"},
        headers=gran,
    )
    assert r.status_code == 403


def test_invite_wrong_email_rejected(client):
    from .conftest import TestingSession

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    token = _get_token(TestingSession)

    interloper = signup(client, "someone-else@example.com")
    r = client.post("/invites/accept", json={"token": token}, headers=interloper)
    assert r.status_code == 403


def test_invite_single_use(client):
    from .conftest import TestingSession

    parent = signup(client, "parent@example.com")
    family_id = create_family(client, parent)
    client.post(
        f"/families/{family_id}/invites",
        json={"email": "gran@example.com", "role": "grandparent"},
        headers=parent,
    )
    token = _get_token(TestingSession)
    gran = signup(client, "gran@example.com")
    assert client.post("/invites/accept", json={"token": token}, headers=gran).status_code == 200
    assert client.post("/invites/accept", json={"token": token}, headers=gran).status_code == 410
    assert client.get(f"/invites/{token}").status_code == 410
