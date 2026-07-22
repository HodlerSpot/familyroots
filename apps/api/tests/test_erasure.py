"""Automated erasure (compliance WS2/WS5/WS6): the §3.A/B/C walks, the §3.D
financial carve-out (rows SURVIVE with a severed identity, money untouched),
media removal, the consent-revocation write, step-up auth, idempotency, and the
local-mode Stripe no-op."""

import uuid
from datetime import date

from app.models import (
    Child,
    ChildRelationship,
    ConsentRecord,
    Contribution,
    Family,
    FamilyMember,
    FundAccount,
    FundLedgerEntry,
    MediaObject,
    MediaStatus,
    Prediction,
    PredictionRound,
    PredictionRoundStatus,
    User,
    VaultItem,
    utcnow,
)
from app.services import erasure as erasure_service
from app.services.storage import get_storage
from .conftest import (
    TestingSession,
    add_child,
    create_family,
    make_member,
    make_premium,
    setup_fund,
    signup,
)

PW = "Password123!"


def _add_media_vault(client, headers, child_id, *, title="A photo"):
    r = client.post(
        f"/children/{child_id}/media", json={"content_type": "image/jpeg"}, headers=headers
    )
    assert r.status_code == 201, r.text
    media_id = r.json()["media_id"]
    assert client.put(f"/media/{media_id}/content", content=b"\xff\xd8\xffhello", headers=headers).status_code == 204
    assert client.post(f"/media/{media_id}/complete", headers=headers).status_code == 204
    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "photo", "title": title, "media_id": media_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return media_id, r.json()["id"]


def _contribute(client, headers, child_id, amount=1500, media_id=None):
    body = {"amount_cents": amount, "currency": "USD", "message": "For your future"}
    if media_id is not None:
        body["media_id"] = media_id
    r = client.post(f"/children/{child_id}/contributions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert client.post(f"/contributions/{cid}/confirm", headers=headers).status_code == 200
    return cid


def _create_child_media(client, headers, child_id):
    """A completed child-scoped media object (a contribution video message)."""
    r = client.post(
        f"/children/{child_id}/media", json={"content_type": "image/jpeg"}, headers=headers
    )
    assert r.status_code == 201, r.text
    media_id = r.json()["media_id"]
    assert client.put(
        f"/media/{media_id}/content", content=b"\xff\xd8\xffvideomsg", headers=headers
    ).status_code == 204
    assert client.post(f"/media/{media_id}/complete", headers=headers).status_code == 204
    return media_id


def _seed_sealed_round_with_keepsake(child_id: uuid.UUID, uploader_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """Directly seed a SEALED prediction round + its child-scoped keepsake PNG
    (the 18-year image), which the normal flow only produces on a birthday seal."""
    key = f"keepsake-{uuid.uuid4().hex}"
    get_storage().put_object(key, b"\x89PNGkeepsake", "image/png")
    with TestingSession() as db:
        media = MediaObject(
            child_id=child_id,
            storage_key=key,
            content_type="image/png",
            byte_size=11,
            uploaded_by=uploader_id,
            status=MediaStatus.uploaded,
        )
        db.add(media)
        db.flush()
        db.add(
            PredictionRound(
                child_id=child_id,
                seals_on=date(2011, 1, 1),
                status=PredictionRoundStatus.sealed,
                cloud_media_id=media.id,
                sealed_at=utcnow(),
            )
        )
        db.commit()
        return media.id, key


def test_erase_child_removes_data_retains_financials_and_revokes_consent(client):
    parent = signup(client, "p@ex.com", "Parent")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    child_id = uuid.UUID(cid)
    setup_fund(client, parent, cid)

    _add_media_vault(client, parent, cid)
    _contribute(client, parent, cid)
    client.post(f"/children/{cid}/predictions", json={"body": "astronaut and artist"}, headers=parent)
    keepsake_media_id, keepsake_key = _seed_sealed_round_with_keepsake(child_id, uuid.UUID(signup_user_id(parent, client)))

    # snapshot the retained financial rows' ids + ledger balance
    with TestingSession() as db:
        contrib = db.query(Contribution).filter(Contribution.child_id == child_id).one()
        contrib_id = contrib.id
        account = db.query(FundAccount).filter(FundAccount.child_id == child_id).one()
        account_id = account.id
        ledger_before = db.query(FundLedgerEntry).filter(FundLedgerEntry.account_id == account_id).count()
    assert ledger_before == 1

    r = client.request(
        "DELETE", f"/families/{fid}/children/{cid}", json={"password": PW}, headers=parent
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "child"
    assert body["consent_revoked"] >= 1
    assert body["media_objects_deleted"] >= 2  # the vault photo + the keepsake PNG

    with TestingSession() as db:
        # child + child-scoped content gone
        assert db.get(Child, child_id) is None
        assert db.query(VaultItem).filter(VaultItem.child_id == child_id).count() == 0
        assert db.query(PredictionRound).filter(PredictionRound.child_id == child_id).count() == 0
        assert db.query(Prediction).count() == 0
        assert db.query(ConsentRecord).filter(ConsentRecord.child_id == child_id).count() == 0
        # no orphaned media (child-scoped media, incl. the keepsake, is gone)
        assert db.query(MediaObject).filter(MediaObject.child_id == child_id).count() == 0
        assert db.get(MediaObject, keepsake_media_id) is None
        # financial rows SURVIVE with the child link severed, money untouched
        contrib = db.get(Contribution, contrib_id)
        assert contrib is not None
        assert contrib.child_id is None
        assert contrib.amount_cents == 1500          # money field untouched
        assert contrib.message is None                # child-linked free text cleared
        account = db.get(FundAccount, account_id)
        assert account is not None and account.child_id is None
        assert db.query(FundLedgerEntry).filter(FundLedgerEntry.account_id == account_id).count() == 1
    # bytes were removed from storage too
    assert get_storage()._path(keepsake_key).exists() is False


def signup_user_id(headers: dict, client) -> str:
    return client.get("/auth/me", headers=headers).json()["id"]


def test_erase_child_is_idempotent(client):
    parent = signup(client, "p2@ex.com", "Parent")
    fid = create_family(client, parent)
    cid = add_child(client, parent, fid)
    child_id = uuid.UUID(cid)
    with TestingSession() as db:
        first, _ = erasure_service.erase_child(db, child_id)
        db.commit()
        assert first.child_ids == [str(child_id)]
        second, _ = erasure_service.erase_child(db, child_id)
        db.commit()
        assert second.child_ids == []  # nothing left to erase


def test_erase_member_severs_authorship_and_deletes_personal(client):
    parent_a = signup(client, "a@ex.com", "Parent A")
    fid = create_family(client, parent_a)
    cid = add_child(client, parent_a, fid)
    child_id = uuid.UUID(cid)
    parent_b = make_member(client, parent_a, fid, "parent", "b@ex.com", "Parent B")
    b_id = uuid.UUID(signup_user_id(parent_b, client))

    # B authors a memory and gives a contribution
    setup_fund(client, parent_a, cid)
    _, vault_id = _add_media_vault(client, parent_b, cid, title="B's memory")
    _contribute(client, parent_b, cid)
    client.put("/me/notifications", json=_all_prefs_off(), headers=parent_b)

    r = client.request("DELETE", "/me", json={"password": PW}, headers=parent_b)
    assert r.status_code == 200, r.text

    with TestingSession() as db:
        assert db.get(User, b_id) is None
        assert db.query(FamilyMember).filter(FamilyMember.user_id == b_id).count() == 0
        assert db.query(ChildRelationship).filter(ChildRelationship.user_id == b_id).count() == 0
        # the memory B authored SURVIVES with a severed author
        item = db.get(VaultItem, uuid.UUID(vault_id))
        assert item is not None and item.created_by is None
        # the contribution SURVIVES with a severed contributor, money intact
        contrib = db.query(Contribution).filter(Contribution.child_id == child_id).one()
        assert contrib.contributor_user_id is None
        assert contrib.amount_cents == 1500
        assert db.query(FundLedgerEntry).count() == 1
    # the family and child continue
    assert client.get(f"/families/{fid}", headers=parent_a).status_code == 200


def test_erase_member_deletes_own_contribution_video(client):
    """Art. 17 fix #3: self-erase deletes the erased person's OWN
    contribution-video media (child-scoped, so the avatar sweep misses it),
    nulls contributions.media_id, and removes the bytes — while the contribution
    money row is RETAINED (contributor severed). The byte deletion is the fix #1
    post-commit assertion: the local storage no longer holds the object once the
    DELETE call returns. (SQLite doesn't enforce the media_id FK, but the walk
    nulls media_id before deleting the row so it is correct on Postgres too.)"""
    parent_a = signup(client, "va@ex.com", "Parent A")
    fid = create_family(client, parent_a)
    cid = add_child(client, parent_a, fid)
    child_id = uuid.UUID(cid)
    parent_b = make_member(client, parent_a, fid, "parent", "vb@ex.com", "Parent B")
    b_id = uuid.UUID(signup_user_id(parent_b, client))

    setup_fund(client, parent_a, cid)
    media_id = _create_child_media(client, parent_b, cid)
    _contribute(client, parent_b, cid, media_id=media_id)

    with TestingSession() as db:
        media = db.get(MediaObject, uuid.UUID(media_id))
        storage_key = media.storage_key
        assert media.child_id == child_id  # child-scoped, NOT user-scoped
    assert get_storage()._path(storage_key).exists() is True

    r = client.request("DELETE", "/me", json={"password": PW}, headers=parent_b)
    assert r.status_code == 200, r.text

    with TestingSession() as db:
        assert db.get(User, b_id) is None
        # contribution RETAINED, contributor + media link severed, money intact
        contrib = db.query(Contribution).filter(Contribution.child_id == child_id).one()
        assert contrib.contributor_user_id is None
        assert contrib.media_id is None
        assert contrib.amount_cents == 1500
        # the video media row is gone
        assert db.get(MediaObject, uuid.UUID(media_id)) is None
    # fix #1: the bytes were removed post-commit
    assert get_storage()._path(storage_key).exists() is False


def _all_prefs_off() -> dict:
    from app.services.notifications import DEFAULT_PREFS

    return {k: False for k in DEFAULT_PREFS}


def test_erase_member_blocked_when_sole_parent_of_family_with_children(client):
    parent = signup(client, "solo@ex.com", "Solo Parent")
    fid = create_family(client, parent)
    add_child(client, parent, fid)
    r = client.request("DELETE", "/me", json={"password": PW}, headers=parent)
    assert r.status_code == 409, r.text
    assert "only parent" in r.json()["detail"].lower()


def test_step_up_auth_required_for_erasure(client):
    parent = signup(client, "step@ex.com", "Parent")
    create_family(client, parent)
    # wrong password → 403 (session valid, step-up failed)
    r = client.request("DELETE", "/me", json={"password": "WrongPass9!"}, headers=parent)
    assert r.status_code == 403, r.text
    # missing body → 422 (StepUpRequest required)
    r = client.request("DELETE", "/me", headers=parent)
    assert r.status_code == 422, r.text
    # account still exists
    assert client.get("/auth/me", headers=parent).status_code == 200


def test_erase_family_retains_financials_and_local_stripe_noops(client):
    parent = signup(client, "fam@ex.com", "Parent")
    fid = create_family(client, parent)
    family_id = uuid.UUID(fid)
    cid = add_child(client, parent, fid)
    setup_fund(client, parent, cid)
    _contribute(client, parent, cid)
    make_premium(client, parent, fid)  # local settlement -> a family_subscriptions row

    # give the (soon-erased) owner a Stripe customer id; local mode must not call Stripe
    with TestingSession() as db:
        u = db.query(User).filter(User.email == "fam@ex.com").one()
        u.stripe_customer_id = "cus_test_local"
        db.commit()

    owner_id = uuid.UUID(signup_user_id(parent, client))
    r = client.request("DELETE", f"/families/{fid}", json={"password": PW}, headers=parent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "family"
    # local backend never calls Stripe Customer.delete
    assert not any("customer_deleted" in a for a in body["stripe_actions"])

    with TestingSession() as db:
        from app.models import FamilySubscription

        assert db.get(Family, family_id) is None
        assert db.query(Child).filter(Child.family_id == family_id).count() == 0
        assert db.query(FamilyMember).filter(FamilyMember.family_id == family_id).count() == 0
        # financial rows SURVIVE with the family link severed; ledger intact
        assert db.query(FundLedgerEntry).count() == 1
        contribs = db.query(Contribution).all()
        assert len(contribs) == 1 and contribs[0].child_id is None
        subs = db.query(FamilySubscription).all()
        assert len(subs) == 1 and subs[0].family_id is None
        # §3.C fix: the now-memberless adult is LEFT INTACT (not auto-erased) —
        # a family erasure is per-family, not per-user-everywhere. They can
        # self-erase via DELETE /me. Recorded on the receipt as orphaned.
        assert db.query(User).filter(User.email == "fam@ex.com").count() == 1
        assert db.query(FamilyMember).filter(FamilyMember.user_id == owner_id).count() == 0
    assert str(owner_id) in body["users_left_orphaned"]


def test_family_erasure_leaves_other_adults_accounts_intact(client):
    """§3.C consent fix: a whole-family erasure must NOT hard-delete other
    independent adults' accounts. A grandparent whose only family this was
    survives as a memberless account (+ recorded orphaned), never erased."""
    parent = signup(client, "solep@ex.com", "Sole Parent")
    fid = create_family(client, parent)
    add_child(client, parent, fid)
    grandparent = make_member(client, parent, fid, "grandparent", "gma@ex.com", "Grandma")
    gp_id = uuid.UUID(signup_user_id(grandparent, client))
    # give the grandparent a Stripe customer id: it must NOT be touched/erased
    with TestingSession() as db:
        gp = db.get(User, gp_id)
        gp.stripe_customer_id = "cus_gp_keepme"
        db.commit()

    r = client.request("DELETE", f"/families/{fid}", json={"password": PW}, headers=parent)
    assert r.status_code == 200, r.text
    body = r.json()

    with TestingSession() as db:
        gp = db.get(User, gp_id)
        assert gp is not None                       # account intact, NOT erased
        assert gp.stripe_customer_id == "cus_gp_keepme"  # their Stripe link untouched
        assert db.query(FamilyMember).filter(FamilyMember.user_id == gp_id).count() == 0
    assert str(gp_id) in body["users_left_orphaned"]
    # the grandparent can still authenticate (account really does survive)
    assert client.get("/auth/me", headers=grandparent).status_code == 200


def test_family_erasure_blocked_with_multiple_parents(client):
    parent_a = signup(client, "pa@ex.com", "Parent A")
    fid = create_family(client, parent_a)
    make_member(client, parent_a, fid, "parent", "pb@ex.com", "Parent B")
    r = client.request("DELETE", f"/families/{fid}", json={"password": PW}, headers=parent_a)
    assert r.status_code == 409, r.text
