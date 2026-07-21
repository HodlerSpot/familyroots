"""The monthly Memory Request: the deterministic child-of-the-month rotation,
the idempotent maintenance sweep (bell + pref-gated push/email, supporters
excluded, satisfied members skipped), and the on-read card endpoint.

Push is exercised with a FAKE pywebpush module (same pattern as test_notify.py)
so no network happens; settings.vapid_private_key is monkeypatched on so the
push feature is "lit".
"""

import sys
import types
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.config import settings
from app.models import MemoryPrompt, Notification, User
from app.services.memory_prompts import (
    child_of_the_month,
    period_for,
    run_memory_prompts,
)

from .conftest import (
    TestingSession,
    add_child,
    create_family,
    make_member,
    signup,
)


# --- helpers -----------------------------------------------------------------


def add_memory(client, headers, child_id, title="A little memory"):
    r = client.post(
        f"/children/{child_id}/vault",
        json={"type": "message", "title": title},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _uid(email: str) -> uuid.UUID:
    with TestingSession() as db:
        return db.query(User).filter(User.email == email).one().id


def _bells(email: str):
    with TestingSession() as db:
        uid = db.query(User).filter(User.email == email).one().id
        return (
            db.query(Notification)
            .filter(
                Notification.user_id == uid,
                Notification.kind == "memory_request",
            )
            .all()
        )


def _prompts(email: str):
    with TestingSession() as db:
        uid = db.query(User).filter(User.email == email).one().id
        return db.query(MemoryPrompt).filter(MemoryPrompt.user_id == uid).all()


def _sweep():
    with TestingSession() as db:
        return run_memory_prompts(db)


# --- fake web push (mirrors test_notify.py) ----------------------------------


class _FakePush:
    def __init__(self):
        self.calls = []

        class WebPushException(Exception):
            def __init__(self, message="", response=None):
                super().__init__(message)
                self.response = response

        self.WebPushException = WebPushException

    def webpush(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture()
def push(monkeypatch):
    fake = _FakePush()
    module = types.ModuleType("pywebpush")
    module.webpush = fake.webpush
    module.WebPushException = fake.WebPushException
    monkeypatch.setitem(sys.modules, "pywebpush", module)
    monkeypatch.setattr(settings, "vapid_private_key", "test-private-key")
    monkeypatch.setattr(settings, "vapid_public_key", "test-public-key")
    monkeypatch.setattr(settings, "vapid_subject", "mailto:test@futureroots.app")
    return fake


def subscribe_push(client, headers, endpoint):
    r = client.post(
        "/me/push-subscriptions",
        json={"endpoint": endpoint, "p256dh": "p256dh-key", "auth": "auth-key"},
        headers=headers,
    )
    assert r.status_code == 201, r.text


# --- rotation: deterministic, covers every child, handles 0/1/N --------------


def _kids(n):
    return [SimpleNamespace(id=i, first_name=f"c{i}") for i in range(n)]


def test_rotation_is_deterministic_and_covers_all_children():
    children = _kids(3)
    dt = datetime(2026, 7, 1, tzinfo=timezone.utc)
    # Deterministic: the same month always resolves the same child object.
    assert child_of_the_month(children, dt) is child_of_the_month(children, dt)

    # The exact index formula, across a two-year span.
    for year in (2025, 2026):
        for month in range(1, 13):
            when = datetime(year, month, 1, tzinfo=timezone.utc)
            idx = (year * 12 + (month - 1)) % 3
            assert child_of_the_month(children, when) is children[idx]

    # Twelve consecutive months of a 3-child family hit every child.
    seen = {
        child_of_the_month(children, datetime(2026, m, 1, tzinfo=timezone.utc)).id
        for m in range(1, 13)
    }
    assert seen == {0, 1, 2}


def test_rotation_zero_and_one_child():
    assert child_of_the_month([], datetime(2026, 7, 1, tzinfo=timezone.utc)) is None
    one = _kids(1)
    for month in range(1, 13):
        when = datetime(2026, month, 1, tzinfo=timezone.utc)
        assert child_of_the_month(one, when) is one[0]


def test_period_for_is_utc_year_month():
    assert period_for(datetime(2026, 7, 21, tzinfo=timezone.utc)) == "2026-07"
    assert period_for(datetime(2026, 12, 1, tzinfo=timezone.utc)) == "2026-12"


# --- the sweep: idempotency --------------------------------------------------


def test_sweep_is_idempotent_one_prompt_per_member_per_month(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id, "Emma")

    assert _sweep() == 1
    assert len(_prompts("parent@example.com")) == 1
    assert len(_bells("parent@example.com")) == 1

    # A second run the same month prompts no one again (throttle claim held).
    assert _sweep() == 0
    assert len(_prompts("parent@example.com")) == 1
    assert len(_bells("parent@example.com")) == 1


# --- satisfied members are skipped -------------------------------------------


def test_member_who_added_a_memory_this_month_is_skipped(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    child_id = add_child(client, parent, family_id, "Emma")
    gran = make_member(client, parent, family_id, "grandparent", "gran@example.com")

    # Gran already added a memory this month → generously satisfied.
    add_memory(client, gran, child_id)

    assert _sweep() == 1  # only the parent is prompted
    assert _prompts("gran@example.com") == []
    assert _bells("gran@example.com") == []
    assert len(_prompts("parent@example.com")) == 1


# --- a member who joins mid-month still gets prompted ------------------------


def test_new_member_mid_month_is_prompted_on_the_next_sweep(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id, "Emma")

    assert _sweep() == 1  # only the parent so far
    gran = make_member(client, parent, family_id, "grandparent", "gran@example.com")

    assert _sweep() == 1  # the new member is caught; the parent is not re-prompted
    assert len(_prompts("gran@example.com")) == 1
    assert len(_prompts("parent@example.com")) == 1


# --- supporters are never prompted, and their card is null -------------------


def test_supporter_never_prompted_and_card_is_null(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id, "Emma")
    supporter = make_member(client, parent, family_id, "supporter", "coach@example.com")

    assert _sweep() == 1  # the parent only; the supporter is excluded
    assert _prompts("coach@example.com") == []
    assert _bells("coach@example.com") == []

    # The card endpoint returns null for the supporter.
    r = client.get(f"/families/{family_id}/memory-prompt", headers=supporter)
    assert r.status_code == 200
    assert r.json() is None


# --- per-family independence for a multi-family member -----------------------


def test_multi_family_member_prompted_per_family_independently(client):
    pat = signup(client, "pat@example.com", "Pat")
    fam_a = create_family(client, pat, "A")
    child_a = add_child(client, pat, fam_a, "Ana")

    bob = signup(client, "bob@example.com", "Bob")
    fam_b = create_family(client, bob, "B")
    add_child(client, bob, fam_b, "Ben")
    # Pat also belongs to family B as a grandparent.
    r = client.post(
        f"/families/{fam_b}/invites",
        json={"email": "pat@example.com", "role": "grandparent"},
        headers=bob,
    )
    assert r.status_code == 201, r.text
    from app.models import FamilyInvite

    with TestingSession() as db:
        token = (
            db.query(FamilyInvite)
            .filter(FamilyInvite.email == "pat@example.com")
            .first()
            .token
        )
    assert client.post("/invites/accept", json={"token": token}, headers=pat).status_code == 200

    # Pat satisfies family A (adds a memory there) but does nothing in B.
    add_memory(client, pat, child_a)

    _sweep()

    # Pat is prompted for B only; family A was satisfied.
    pat_prompts = _prompts("pat@example.com")
    assert len(pat_prompts) == 1
    assert pat_prompts[0].family_id == uuid.UUID(fam_b)
    # Bob (only in B, unsatisfied) is prompted for B.
    assert len(_prompts("bob@example.com")) == 1


# --- prefs: default on; muting suppresses channels but the bell still writes -


def test_prefs_default_on_and_mute_suppresses_only_the_channels(
    client, tmp_path, monkeypatch, push
):
    from app.services import email as email_module
    from .test_me import prefs

    outbox = tmp_path / "outbox"
    monkeypatch.setattr(email_module, "_sender", email_module.OutboxEmailSender(outbox))

    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id, "Emma")
    gran = make_member(client, parent, family_id, "grandparent", "gran@example.com")

    # Gran mutes BOTH memory-request channels; Pat keeps the defaults (on).
    r = client.put(
        "/me/notifications",
        json=prefs(email_memory_request=False, push_memory_request=False),
        headers=gran,
    )
    assert r.status_code == 200, r.text
    subscribe_push(client, parent, "https://fcm.googleapis.com/pat")
    subscribe_push(client, gran, "https://fcm.googleapis.com/gran")
    for f in outbox.glob("*.txt"):
        f.unlink()

    assert _sweep() == 2  # both members get a bell row

    # Bell is written for BOTH (never gated).
    assert len(_bells("parent@example.com")) == 1
    assert len(_bells("gran@example.com")) == 1

    # Push + email reach Pat (defaults on) but not Gran (muted).
    endpoints = {c["subscription_info"]["endpoint"] for c in push.calls}
    assert endpoints == {"https://fcm.googleapis.com/pat"}
    mail = [f.read_text(encoding="utf-8") for f in outbox.glob("*.txt")]
    assert any("To: parent@example.com" in m for m in mail)
    assert all("To: gran@example.com" not in m for m in mail)


# --- the card endpoint matrix ------------------------------------------------


def test_card_names_the_month_child_and_satisfied_flips_after_a_memory(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    add_child(client, parent, family_id, "Ana")
    child_b = add_child(client, parent, family_id, "Ben")

    r = client.get(f"/families/{family_id}/memory-prompt", headers=parent)
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    # The card names the deterministic child-of-the-month (matches the rule).
    with TestingSession() as db:
        from app.services.memory_prompts import active_children
        from app.models import utcnow

        expected = child_of_the_month(active_children(db, uuid.UUID(family_id)), utcnow())
    assert body["child"]["id"] == str(expected.id)
    assert body["period"] == period_for_now()
    assert body["satisfied"] is False

    # Adding any memory this month flips satisfied → true (the card auto-hides).
    add_memory(client, parent, child_b)
    r = client.get(f"/families/{family_id}/memory-prompt", headers=parent)
    assert r.json()["satisfied"] is True


def test_card_is_null_for_a_childless_family(client):
    parent = signup(client, "parent@example.com", "Pat")
    family_id = create_family(client, parent)
    r = client.get(f"/families/{family_id}/memory-prompt", headers=parent)
    assert r.status_code == 200
    assert r.json() is None


def period_for_now() -> str:
    from app.models import utcnow

    return period_for(utcnow())
