"""Unified notification dispatch: bell + email + web push.

Every notify()-worthy domain action funnels through here. A single call writes
the durable in-app "bell" row for each recipient and, gated by that recipient's
preferences, queues an email and/or a web-push payload. Callers COMMIT their
transaction first, then call ``batch.deliver(db)`` — mirroring the
ContributionSettlement post-commit pattern so a webhook replay that loses the
DB race never double-sends (the bell rows roll back with the losing
transaction, and deliver() is only reached after a successful commit).

Core rule: **the bell is never gated; preferences govern only the interrupting
channels (email + push).** A user who has muted everything still accrues bell
rows — they are the durable record of what happened; the switches only decide
whether we also interrupt them out of band. (Admin broadcasts follow the same
rule: opted-out users still get the bell row, just no push/email.)

Taxonomy — audience / channels / feed event per kind:

| kind             | audience                              | feed event      |
|------------------|---------------------------------------|-----------------|
| call_live        | family members, excl. starter; no sup | none (by design)|
| contribution     | parents/guardians, excl. contributor  | contribution    |
| fund_activated   | parents/guardians                     | fund_activated  |
| capsule_sealed   | family members, excl. sealer; no sup  | capsule_created |
| capsule_released | parents/guardians                     | capsule_released|
| announcement     | ALL non-disabled users (sup included) | none            |
| new_member       | active members, excl. joiner; no sup  | member_joined   |
| milestone        | active members, excl. actor; no sup   | milestone       |
| memory           | active members, excl. actor; no sup   | memory_added    |
| legacy           | active members, excl. actor; no sup   | none (existing) |

"no sup" = supporters excluded (non-family adults who must never receive family
content out of band). The feed events are emitted by the domain code, not here;
this module only fans out notifications.

Scale seam: delivery is inline and synchronous (one HTTP POST per push
subscription, 3s timeout each). Fan-out today is a single family (or, for
broadcasts, the whole user base at low frequency), so this is fine. If push
volume ever grows, deliver() is the seam to make asynchronous — enqueue the
payload and have the API Lambda self-invoke (or an SQS-backed worker) do the
POSTs, leaving the request path untouched.
"""

import enum
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Child,
    FamilyMember,
    FamilyRole,
    FeedEventType,
    MemberStatus,
    Notification,
    NotificationPreference,
    PushSubscription,
    User,
)
from .email import get_email_sender
from .email_templates import render_email
from .feed import emit
from .notifications import DEFAULT_PREFS

logger = logging.getLogger(__name__)

# Push copy hard limits (docs/brand/notifications-copy.md). Applied as a
# last-resort backstop; audiences see well-fitting strings for realistic names.
TITLE_LIMIT = 50
BODY_LIMIT = 120


class NotificationKind(str, enum.Enum):
    call_live = "call_live"
    contribution = "contribution"
    fund_activated = "fund_activated"
    capsule_sealed = "capsule_sealed"
    capsule_released = "capsule_released"
    announcement = "announcement"
    new_member = "new_member"
    milestone = "milestone"
    memory = "memory"
    legacy = "legacy"


# kind -> (email pref attr, push pref attr). Note "announcement" maps to the
# plural "announcements" columns.
PREF_ATTRS: dict[NotificationKind, tuple[str, str]] = {
    NotificationKind.call_live: ("email_call_live", "push_call_live"),
    NotificationKind.contribution: ("email_contribution", "push_contribution"),
    NotificationKind.fund_activated: ("email_fund_activated", "push_fund_activated"),
    NotificationKind.capsule_sealed: ("email_capsule_sealed", "push_capsule_sealed"),
    NotificationKind.capsule_released: ("email_capsule_released", "push_capsule_released"),
    NotificationKind.announcement: ("email_announcements", "push_announcements"),
    NotificationKind.new_member: ("email_new_member", "push_new_member"),
    NotificationKind.milestone: ("email_milestone", "push_milestone"),
    NotificationKind.memory: ("email_memory", "push_memory"),
    NotificationKind.legacy: ("email_legacy", "push_legacy"),
}

# kind -> (push TTL seconds, Urgency header). A live call is worthless after a
# couple of minutes, so it gets a short TTL and high urgency; everything else
# is a normal-urgency, one-day message.
_DELIVERY: dict[NotificationKind, tuple[int, str]] = {
    NotificationKind.call_live: (90, "high"),
}
_DEFAULT_TTL = 86_400
_DEFAULT_URGENCY = "normal"

Recipient = tuple[User, NotificationPreference | None]


@dataclass(frozen=True)
class EmailPayload:
    subject: str
    body: str
    html: str | None = None


def _clip(text: str, limit: int) -> str:
    """Backstop clip to a hard character limit, at a word boundary, with an
    ellipsis. Real names/titles fit the templates; this only ever fires on
    pathological input."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rstrip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")].rstrip()
    return cut + "…"


def _pref_enabled(pref: NotificationPreference | None, attr: str) -> bool:
    return getattr(pref, attr) if pref is not None else DEFAULT_PREFS[attr]


# --- audience resolvers (reuse the retired notify_members query shape) --------


def family_recipients(
    db: Session,
    family_id: uuid.UUID,
    *,
    exclude_user_id: uuid.UUID | None = None,
    roles: list[FamilyRole] | None = None,
    include_supporters: bool = False,
) -> list[Recipient]:
    """Active members of a family, each paired with their prefs row (or None).
    Supporters are excluded by default — they must never receive family content
    out of band. (family_id, user_id) is unique, so each user appears once."""
    query = (
        db.query(User, NotificationPreference)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.status == MemberStatus.active,
        )
    )
    if not include_supporters:
        query = query.filter(FamilyMember.role != FamilyRole.supporter)
    if roles is not None:
        query = query.filter(FamilyMember.role.in_(roles))
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)
    return query.all()


def all_active_user_recipients(db: Session) -> list[Recipient]:
    """Every non-disabled user (supporters included) — the announcement
    audience. Platform content carries no family data, so it is safe to reach
    everyone."""
    return (
        db.query(User, NotificationPreference)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
        .filter(User.disabled.is_(False))
        .all()
    )


# --- batch + dispatch ---------------------------------------------------------


@dataclass
class NotificationBatch:
    """Bell rows are already staged in the caller's transaction; this carries
    the NOT-yet-sent email payloads and the set of users to push to. Call
    deliver() only AFTER the transaction commits."""

    kind: NotificationKind
    title: str
    body: str
    url: str | None
    emails: list[dict] = field(default_factory=list)  # EmailSender.send(**kwargs)
    push_user_ids: list[uuid.UUID] = field(default_factory=list)

    def deliver(self, db: Session) -> None:
        sender = get_email_sender()
        for email in self.emails:
            sender.send(**email)
        if self.push_user_ids:
            _deliver_push(db, self)


def notify(
    db: Session,
    *,
    kind: NotificationKind,
    recipients: list[Recipient],
    title: str,
    body: str,
    url: str | None,
    family_id: uuid.UUID | None,
    email_builder: Callable[[User], EmailPayload | None] | None = None,
) -> NotificationBatch:
    """Stage one bell row per recipient (always) plus pref-gated email/push.

    Writes the Notification rows into the caller's open transaction so they are
    atomic with the domain change. Returns a batch; the caller commits, then
    calls batch.deliver(db). email_builder is invoked per recipient (so emails
    can carry a personal greeting) only when that recipient has the kind's email
    switch on; returning None from it skips the email for that recipient."""
    email_attr, push_attr = PREF_ATTRS[kind]
    title = _clip(title, TITLE_LIMIT)
    body = _clip(body, BODY_LIMIT)
    batch = NotificationBatch(kind=kind, title=title, body=body, url=url)
    for user, pref in recipients:
        db.add(
            Notification(
                user_id=user.id,
                kind=kind.value,
                title=title,
                body=body,
                url=url,
                family_id=family_id,
            )
        )
        if email_builder is not None and _pref_enabled(pref, email_attr):
            payload = email_builder(user)
            if payload is not None:
                batch.emails.append(
                    {
                        "to": user.email,
                        "subject": payload.subject,
                        "body": payload.body,
                        "html": payload.html,
                    }
                )
        if _pref_enabled(pref, push_attr):
            batch.push_user_ids.append(user.id)
    return batch


def _deliver_push(db: Session, batch: NotificationBatch) -> None:
    """POST the payload to every live subscription of every push-enabled
    recipient. Best-effort: dead subscriptions (404/410/403) are pruned;
    every other failure is logged and swallowed so one bad endpoint never
    breaks the fan-out or the user's original action."""
    if not settings.vapid_private_key:
        return  # feature dark: no keys configured
    # Lazy import so the dependency isn't needed for local dev / tests unless
    # push is exercised (tests inject a fake pywebpush module).
    try:
        from pywebpush import WebPushException, webpush
    except Exception as exc:  # noqa: BLE001
        logger.warning("push disabled: pywebpush unavailable (%r)", exc)
        return

    subs = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id.in_(batch.push_user_ids))
        .all()
    )
    if not subs:
        return
    ttl, urgency = _DELIVERY.get(batch.kind, (_DEFAULT_TTL, _DEFAULT_URGENCY))
    data = json.dumps(
        {
            "title": batch.title,
            "body": batch.body,
            "url": batch.url or "/",
            "tag": batch.kind.value,
        }
    )
    dead: list[uuid.UUID] = []
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=ttl,
                headers={"Urgency": urgency},
                timeout=3,
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            code = getattr(response, "status_code", None)
            if code in (404, 410, 403):
                dead.append(sub.id)  # subscription is gone / no longer authorized
            else:
                logger.warning("push send failed (status=%s): %r", code, exc)
        except Exception as exc:  # noqa: BLE001 — deliberately best-effort
            logger.warning("push send error: %r", exc)
    if dead:
        db.query(PushSubscription).filter(PushSubscription.id.in_(dead)).delete(
            synchronize_session=False
        )
        db.commit()


# --- shared emitter: fund activation (used by two call sites) -----------------


def notify_fund_activated(db: Session, fund_account) -> NotificationBatch | None:
    """A child's Future Fund just became active: emit the feed event and stage
    the fund_activated notification to the family's parents/guardians. Returns
    the batch (caller commits, then delivers) or None if the child is gone."""
    child = db.get(Child, fund_account.child_id)
    if child is None:
        return None
    actor_id = fund_account.setup_by or child.created_by
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=actor_id,
        type=FeedEventType.fund_activated,
        child_id=child.id,
        payload={"child_name": child.first_name, "child_id": str(child.id)},
    )
    recipients = family_recipients(
        db, child.family_id, roles=[FamilyRole.parent, FamilyRole.guardian]
    )
    contribute_url = f"/family/{child.family_id}/child/{child.id}/contribute"

    def email_builder(user: User) -> EmailPayload:
        return EmailPayload(
            subject=f"{child.first_name}'s Future Fund is ready for gifts",
            body=(
                f"Hi {user.display_name},\n\n"
                f"Wonderful news: {child.first_name}'s Future Fund is set up and "
                f"ready. Gifts can reach {child.first_name}'s future starting today.\n\n"
                f"Birthdays, holidays, or just because, any gift helps build "
                f"something lasting for {child.first_name}.\n\n"
                f"Give to {child.first_name}'s Future Fund: "
                f"{settings.web_base_url}{contribute_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=f"Gifts can reach {child.first_name} starting today.",
                greeting=f"Hi {user.display_name},",
                paragraphs=[
                    f"Wonderful news: {child.first_name}'s Future Fund is set up "
                    f"and ready. Gifts can reach {child.first_name}'s future "
                    f"starting today.",
                    f"Birthdays, holidays, or just because, any gift helps build "
                    f"something lasting for {child.first_name}.",
                ],
                cta_label=f"Give to {child.first_name}'s Future Fund",
                cta_url=f"{settings.web_base_url}{contribute_url}",
            ),
        )

    return notify(
        db,
        kind=NotificationKind.fund_activated,
        recipients=recipients,
        title=f"{child.first_name}'s Future Fund is ready for gifts",
        body=f"The whole family can start giving to {child.first_name}'s future today.",
        url=contribute_url,
        family_id=child.family_id,
        email_builder=email_builder,
    )
