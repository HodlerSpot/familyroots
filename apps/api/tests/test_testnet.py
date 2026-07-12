"""Testnet gamification harness tests (docs/testnet.md).

Covers the security wall (404s when testnet_mode is off, no awards when off),
real signature verification with eth-account keys, single-use nonces, tester
provisioning, the award flow across real product actions, daily caps, and the
derived leaderboard.
"""

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.config import settings
from app.main import app
from app.testnet.router import router as _testnet_routes  # name must not start with "test"

from .conftest import add_child, create_family, signup

# The default (family-product) app never mounts /testnet. Mount it once here
# so the harness can be exercised; the require_testnet dependency still 404s
# whenever settings.testnet_mode is off, which is exactly the wall we test.
if not any(getattr(r, "path", "").startswith("/testnet") for r in app.router.routes):
    app.include_router(_testnet_routes)


ADMIN_TOKEN = "test-admin-secret"
BOGUS_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture()
def testnet_on(monkeypatch):
    monkeypatch.setattr(settings, "testnet_mode", True)


@pytest.fixture()
def admin_token(monkeypatch):
    monkeypatch.setattr(settings, "testnet_admin_token", ADMIN_TOKEN)
    return {"X-Admin-Token": ADMIN_TOKEN}


def submit_bug(client, headers, title="Feed crashes on open", body="Open the feed and it goes blank"):
    r = client.post("/testnet/bugs", json={"title": title, "body": body}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def wallet_login(client, acct=None):
    """Full SIWE-style login: nonce -> personal_sign -> verify."""
    acct = acct or Account.create()
    r = client.post("/testnet/auth/nonce", json={"address": acct.address})
    assert r.status_code == 200, r.text
    message = r.json()["message"]
    assert acct.address.lower() in message
    signed = Account.sign_message(encode_defunct(text=message), acct.key)
    r = client.post(
        "/testnet/auth/verify",
        json={"address": acct.address, "signature": signed.signature.hex()},
    )
    assert r.status_code == 200, r.text
    return acct, {"Authorization": f"Bearer {r.json()['access_token']}"}


def total_points(client, headers) -> int:
    r = client.get("/testnet/quests", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["total_points"]


def quest(client, headers, action) -> dict:
    r = client.get("/testnet/quests", headers=headers)
    assert r.status_code == 200, r.text
    return next(q for q in r.json()["quests"] if q["action"] == action)


# --- the wall ---


def test_endpoints_do_not_exist_when_flag_off(client):
    assert client.post("/testnet/auth/nonce", json={"address": "0x" + "a" * 40}).status_code == 404
    assert client.get("/testnet/leaderboard").status_code == 404
    assert client.get("/testnet/quests").status_code == 404
    assert client.post("/testnet/profile", json={"display_name": "x"}).status_code == 404


def test_no_awards_when_flag_off(client, monkeypatch):
    """The award hook itself is walled: with the flag off, real product
    actions by an existing tester score nothing."""
    monkeypatch.setattr(settings, "testnet_mode", True)
    _, headers = wallet_login(client)
    assert total_points(client, headers) == 25  # connect_wallet only

    monkeypatch.setattr(settings, "testnet_mode", False)
    create_family(client, headers)  # runs fine, awards nothing

    monkeypatch.setattr(settings, "testnet_mode", True)
    assert total_points(client, headers) == 25


# --- wallet auth ---


def test_wallet_login_creates_tester_and_platform_user(testnet_on, client):
    acct, headers = wallet_login(client)
    addr = acct.address.lower()

    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == f"{addr}@wallet.testnet.futureroots.app"
    assert me["display_name"] == f"Tester {addr[:6]}...{addr[-4:]}"
    assert me["display_name"].isascii()

    q = quest(client, headers, "connect_wallet")
    assert q["times_completed"] == 1
    assert q["points_earned"] == 25


def test_second_login_reuses_tester_and_awards_connect_once(testnet_on, client):
    acct, headers1 = wallet_login(client)
    _, headers2 = wallet_login(client, acct)
    me1 = client.get("/auth/me", headers=headers1).json()
    me2 = client.get("/auth/me", headers=headers2).json()
    assert me1["id"] == me2["id"]
    assert total_points(client, headers2) == 25  # connect_wallet never repeats


def test_wrong_signature_rejected(testnet_on, client):
    acct, imposter = Account.create(), Account.create()
    r = client.post("/testnet/auth/nonce", json={"address": acct.address})
    signed = Account.sign_message(encode_defunct(text=r.json()["message"]), imposter.key)
    r = client.post(
        "/testnet/auth/verify",
        json={"address": acct.address, "signature": signed.signature.hex()},
    )
    assert r.status_code == 401


def test_nonce_is_single_use(testnet_on, client):
    acct = Account.create()
    r = client.post("/testnet/auth/nonce", json={"address": acct.address})
    signed = Account.sign_message(encode_defunct(text=r.json()["message"]), acct.key)
    body = {"address": acct.address, "signature": signed.signature.hex()}
    assert client.post("/testnet/auth/verify", json=body).status_code == 200
    # Replay of the exact same valid signature must fail: the nonce is spent
    assert client.post("/testnet/auth/verify", json=body).status_code == 401


def test_verify_without_nonce_rejected(testnet_on, client):
    acct = Account.create()
    signed = Account.sign_message(encode_defunct(text="anything"), acct.key)
    r = client.post(
        "/testnet/auth/verify",
        json={"address": acct.address, "signature": signed.signature.hex()},
    )
    assert r.status_code == 401


def test_bad_address_shape_rejected(testnet_on, client):
    assert client.post("/testnet/auth/nonce", json={"address": "grandma"}).status_code == 422


# --- awards, caps, leaderboard ---


def test_award_flow_and_derived_leaderboard(testnet_on, client):
    acct, headers = wallet_login(client)
    family_id = create_family(client, headers)  # +75
    child_id = add_child(client, headers, family_id)  # +60
    r = client.post(
        f"/children/{child_id}/milestones",
        json={"title": "First steps!"},
        headers=headers,
    )
    assert r.status_code == 201  # +50

    # 25 (connect) + 75 + 60 + 50, all derived by SUM over point events
    assert total_points(client, headers) == 210
    assert quest(client, headers, "milestone")["completed_today"] == 1

    r = client.get("/testnet/leaderboard", headers=headers)
    assert r.status_code == 200
    board = r.json()
    assert board["my_rank"] == 1
    assert board["my_points"] == 210
    top = board["entries"][0]
    addr = acct.address.lower()
    assert top["rank"] == 1
    assert top["points"] == 210
    assert top["is_me"] is True
    assert top["display_name"] == f"{addr[:6]}...{addr[-4:]}"

    # Unauthenticated view still works, without a personal rank
    r = client.get("/testnet/leaderboard")
    assert r.status_code == 200
    assert r.json()["my_rank"] is None


def test_daily_cap_enforced(testnet_on, client):
    _, headers = wallet_login(client)
    for name in ("The Oaks", "The Elms", "The Pines"):
        create_family(client, headers, name=name)
    q = quest(client, headers, "create_family")
    assert q["daily_cap"] == 2
    assert q["completed_today"] == 2  # third family created fine, scored nothing
    assert q["points_earned"] == 150
    assert total_points(client, headers) == 25 + 150


def test_non_tester_actions_never_score(testnet_on, client):
    headers = signup(client, "parent@example.com")
    create_family(client, headers)
    r = client.get("/testnet/leaderboard")
    assert r.status_code == 200
    assert r.json()["entries"] == []  # no tester rows, no points
    # And a plain email user has no quest board at all
    assert client.get("/testnet/quests", headers=headers).status_code == 404


def test_profile_display_name(testnet_on, client):
    _, headers = wallet_login(client)
    r = client.post("/testnet/profile", json={"display_name": "Grandma Faye"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["display_name"] == "Grandma Faye"
    assert quest(client, headers, "set_display_name")["points_earned"] == 10

    r = client.get("/testnet/leaderboard", headers=headers)
    assert r.json()["entries"][0]["display_name"] == "Grandma Faye"

    assert (
        client.post("/testnet/profile", json={"display_name": "x" * 41}, headers=headers).status_code
        == 422
    )


def test_north_star_journey_scores_heaviest(testnet_on, client):
    """Invite a grandparent -> they accept -> they contribute: the full
    grandparent journey outweighs everything else on the board."""
    _, parent = wallet_login(client)
    grandma_acct, grandma = wallet_login(client)
    grandma_email = client.get("/auth/me", headers=grandma).json()["email"]

    family_id = create_family(client, parent)  # +75
    child_id = add_child(client, parent, family_id)  # +60

    r = client.post(
        f"/families/{family_id}/invites",
        json={"email": grandma_email, "role": "grandparent"},
        headers=parent,
    )
    assert r.status_code == 201  # parent +150 (invite_grandparent)

    # Grab the token straight from the DB, same as test_invites.py does
    from app.models import FamilyInvite

    from .conftest import TestingSession

    db = TestingSession()
    token = db.query(FamilyInvite).first().token
    db.close()

    r = client.post("/invites/accept", json={"token": token}, headers=grandma)
    assert r.status_code == 200  # grandma +125 (invite_accepted)

    r = client.post(
        f"/children/{child_id}/contributions",
        json={"amount_cents": 2500, "message": "So proud of you!"},
        headers=grandma,
    )
    assert r.status_code == 201
    contribution_id = r.json()["id"]
    r = client.post(f"/contributions/{contribution_id}/confirm", headers=grandma)
    assert r.status_code == 200  # grandma +200 (contribution)

    assert total_points(client, parent) == 25 + 75 + 60 + 150  # 310
    assert total_points(client, grandma) == 25 + 125 + 200  # 350

    board = client.get("/testnet/leaderboard", headers=grandma).json()
    assert [e["points"] for e in board["entries"]] == [350, 310]
    assert board["entries"][0]["is_me"] is True


def test_capsule_quests_award_the_creator(testnet_on, client):
    _, headers = wallet_login(client)
    family_id = create_family(client, headers)
    child_id = add_child(client, headers, family_id)
    r = client.post(
        f"/children/{child_id}/capsules",
        json={
            "type": "letter",
            "body": "For your wedding day",
            "release_condition": "milestone",
            "release_milestone": "Wedding day",
        },
        headers=headers,
    )
    assert r.status_code == 201  # +60 capsule_created
    capsule_id = r.json()["id"]
    r = client.post(f"/capsules/{capsule_id}/release", headers=headers)
    assert r.status_code == 200  # +75 capsule_released, to the sealer

    assert quest(client, headers, "capsule_created")["points_earned"] == 60
    assert quest(client, headers, "capsule_released")["points_earned"] == 75


# --- bug-report quest: submission never scores; only human verify awards ---


def test_bug_endpoints_404_when_flag_off(client):
    assert client.post("/testnet/bugs", json={"title": "x", "body": "y"}).status_code == 404
    assert client.get("/testnet/bugs").status_code == 404
    assert (
        client.post(f"/testnet/bugs/{BOGUS_ID}/verify", json={"decision": "verified"}).status_code
        == 404
    )


def test_submitting_a_bug_awards_no_points(testnet_on, client):
    _, headers = wallet_login(client)  # +25 connect_wallet
    bug = submit_bug(client, headers)
    assert bug["status"] == "pending"

    # Submission is not a scoring path.
    assert total_points(client, headers) == 25
    assert quest(client, headers, "bug_verified")["times_completed"] == 0

    reports = client.get("/testnet/bugs", headers=headers).json()
    assert len(reports) == 1
    assert reports[0]["status"] == "pending"
    assert reports[0]["reviewed_at"] is None


def test_admin_verify_awards_and_shows_on_leaderboard(testnet_on, admin_token, client):
    _, headers = wallet_login(client)
    bug = submit_bug(client, headers)

    r = client.post(
        f"/testnet/bugs/{bug['id']}/verify",
        json={"decision": "verified"},
        headers=admin_token,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
    assert r.json()["reviewed_at"] is not None

    assert total_points(client, headers) == 25 + 250
    assert quest(client, headers, "bug_verified")["points_earned"] == 250

    board = client.get("/testnet/leaderboard", headers=headers).json()
    assert board["my_points"] == 275
    assert board["entries"][0]["points"] == 275

    assert client.get("/testnet/bugs", headers=headers).json()[0]["status"] == "verified"


def test_verify_with_wrong_or_missing_admin_token_awards_nothing(testnet_on, admin_token, client):
    _, headers = wallet_login(client)
    bug = submit_bug(client, headers)
    url = f"/testnet/bugs/{bug['id']}/verify"

    assert client.post(url, json={"decision": "verified"}).status_code == 401  # missing
    assert (
        client.post(url, json={"decision": "verified"}, headers={"X-Admin-Token": "nope"}).status_code
        == 401
    )  # wrong

    assert total_points(client, headers) == 25
    assert client.get("/testnet/bugs", headers=headers).json()[0]["status"] == "pending"


def test_verify_impossible_when_no_admin_token_configured(testnet_on, client):
    # No admin_token fixture -> settings.testnet_admin_token is "".
    _, headers = wallet_login(client)
    bug = submit_bug(client, headers)
    r = client.post(
        f"/testnet/bugs/{bug['id']}/verify",
        json={"decision": "verified"},
        headers={"X-Admin-Token": "anything"},
    )
    assert r.status_code == 401
    assert total_points(client, headers) == 25


def test_double_verify_does_not_double_award(testnet_on, admin_token, client):
    _, headers = wallet_login(client)
    bug = submit_bug(client, headers)
    url = f"/testnet/bugs/{bug['id']}/verify"
    assert client.post(url, json={"decision": "verified"}, headers=admin_token).status_code == 200
    assert client.post(url, json={"decision": "verified"}, headers=admin_token).status_code == 200
    assert total_points(client, headers) == 25 + 250  # still one award


def test_rejected_bug_awards_nothing(testnet_on, admin_token, client):
    _, headers = wallet_login(client)
    bug = submit_bug(client, headers)
    r = client.post(
        f"/testnet/bugs/{bug['id']}/verify",
        json={"decision": "rejected"},
        headers=admin_token,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert total_points(client, headers) == 25


def test_invalid_decision_rejected(testnet_on, admin_token, client):
    _, headers = wallet_login(client)
    bug = submit_bug(client, headers)
    r = client.post(
        f"/testnet/bugs/{bug['id']}/verify",
        json={"decision": "maybe"},
        headers=admin_token,
    )
    assert r.status_code == 422


def test_pending_bug_reports_are_capped(testnet_on, client):
    _, headers = wallet_login(client)
    for i in range(20):
        submit_bug(client, headers, title=f"Bug {i}")
    r = client.post(
        "/testnet/bugs", json={"title": "One too many", "body": "spammy"}, headers=headers
    )
    assert r.status_code == 429

