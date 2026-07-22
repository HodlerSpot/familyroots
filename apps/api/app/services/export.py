"""DSAR data export (GDPR Art. 15/20) — the read/portability counterpart to
services/erasure.py. Assembles a machine-readable JSON bundle plus a manifest of
the subject's media (ids + storage keys the caller is entitled to fetch) for the
three scopes in the runbook tree: member-only, child-profile, whole-family.

No cross-family leak: every query is scoped by the subject id (user/child/
family), and media gathering reuses the same per-object rules as
routers.vault.download_media — a SEALED prediction-round keepsake is excluded
for everyone, a SEALED capsule's attachment only for its own creator. Financial
facts included are the ones the subject is entitled to see (amounts, currency,
status, dates), never another family's.

The bundle is plain JSON-serializable data (uuids -> str, datetimes ->
isoformat); the endpoint returns it directly (a downloadable JSON), which keeps
the assembly single-query-per-table and rate-limit-friendly (no per-media Stripe
or provider calls)."""

import mimetypes
import uuid
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import (
    Badge,
    CapsuleReleaseVote,
    Child,
    Comment,
    ConsentRecord,
    Contribution,
    Family,
    FamilyMember,
    FeedEvent,
    FundAccount,
    FundLedgerEntry,
    FundNudge,
    Goal,
    GoalCompletion,
    LegacyItem,
    MediaObject,
    MemberStatus,
    MemoryPrompt,
    Notification,
    NotificationPreference,
    Prediction,
    PredictionRound,
    PredictionRoundStatus,
    PremiumGrant,
    PushSubscription,
    FamilySubscription,
    Reaction,
    TimeCapsule,
    User,
    VaultItem,
    CapsuleStatus,
    utcnow,
)
from .notifications import DEFAULT_PREFS

# How the subject retrieves the actual bytes for any media_id in this bundle.
# We NEVER expose internal storage_keys (Art. 20 / key exposure); the id +
# content_type is enough to fetch via the authenticated media endpoint.
MEDIA_RETRIEVAL_NOTE = (
    "Download each media file by its media_id from GET /media/{media_id} while "
    "authenticated (a media token is minted for you on request). storage_key is "
    "deliberately omitted — it is an internal reference, not needed to retrieve "
    "your files."
)


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value is not None else None


def _dt(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _media_entry(m: MediaObject, scope: str) -> dict:
    """One media manifest row (Art. 20). Exposes the retrievable media_id +
    content_type + a friendly kind/filename label — NEVER the internal
    storage_key. The subject fetches the bytes via GET /media/{media_id}."""
    kind = m.content_type.split("/", 1)[0] if "/" in m.content_type else "file"
    ext = mimetypes.guess_extension(m.content_type) or ""
    return {
        "media_id": _id(m.id),
        "content_type": m.content_type,
        "kind": kind,
        "filename": f"{m.id}{ext}",
        "scope": scope,
    }


def _display_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.display_name if user is not None else None


# --- media manifest (per-object authorization mirrors download_media) --------


def _child_media_manifest(
    db: Session, child_id: uuid.UUID, requester_id: uuid.UUID
) -> list[dict]:
    """Every child-scoped media object the requester is entitled to, EXCLUDING a
    sealed prediction-round keepsake (hidden from everyone until 18) and a sealed
    capsule's attachment authored by someone else."""
    sealed_round_media = {
        row[0]
        for row in db.query(PredictionRound.cloud_media_id)
        .filter(
            PredictionRound.child_id == child_id,
            PredictionRound.status == PredictionRoundStatus.sealed,
            PredictionRound.cloud_media_id.isnot(None),
        )
        .all()
    }
    sealed_capsule_owner: dict[uuid.UUID, uuid.UUID] = {
        media_id: created_by
        for media_id, created_by in db.query(
            TimeCapsule.media_id, TimeCapsule.created_by
        )
        .filter(
            TimeCapsule.child_id == child_id,
            TimeCapsule.status == CapsuleStatus.sealed,
            TimeCapsule.media_id.isnot(None),
        )
        .all()
    }
    manifest: list[dict] = []
    for media in db.query(MediaObject).filter(MediaObject.child_id == child_id).all():
        if media.id in sealed_round_media:
            continue
        owner = sealed_capsule_owner.get(media.id)
        if owner is not None and owner != requester_id:
            continue
        manifest.append(_media_entry(media, "child"))
    return manifest


def _scope_media_manifest(db: Session, *, family_id=None, user_id=None) -> list[dict]:
    query = db.query(MediaObject)
    scope = "family" if family_id is not None else "user"
    if family_id is not None:
        query = query.filter(MediaObject.family_id == family_id)
    else:
        query = query.filter(MediaObject.user_id == user_id)
    return [_media_entry(m, scope) for m in query.all()]


# --- row serializers ---------------------------------------------------------


def _contribution_row(db: Session, c: Contribution, *, include_child: bool) -> dict:
    row = {
        "id": _id(c.id),
        "amount_cents": c.amount_cents,
        "currency": c.currency,
        "fee_cents": c.fee_cents,
        "refunded_cents": c.refunded_cents,
        "status": c.status.value,
        "message": c.message,
        "created_at": _dt(c.created_at),
        "contributor_name": _display_name(db, c.contributor_user_id),
    }
    if include_child:
        child = db.get(Child, c.child_id) if c.child_id else None
        row["child_name"] = child.first_name if child else None
    return row


def _vault_row(item: VaultItem) -> dict:
    return {
        "id": _id(item.id),
        "type": item.type.value,
        "title": item.title,
        "body": item.body,
        "media_id": _id(item.media_id),
        "visible_to_supporters": item.visible_to_supporters,
        "created_at": _dt(item.created_at),
    }


def _prefs_dict(db: Session, user_id: uuid.UUID) -> dict:
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .first()
    )
    if pref is None:
        return dict(DEFAULT_PREFS)
    return {field: getattr(pref, field) for field in DEFAULT_PREFS}


# --- child bundle (shared by child + family export) --------------------------


def _child_bundle(db: Session, child: Child, requester_id: uuid.UUID) -> dict:
    consent = db.query(ConsentRecord).filter(ConsentRecord.child_id == child.id).all()
    vault = (
        db.query(VaultItem)
        .filter(VaultItem.child_id == child.id, VaultItem.deleted_at.is_(None))
        .all()
    )
    badges = db.query(Badge).filter(Badge.child_id == child.id).all()
    goals = db.query(Goal).filter(Goal.child_id == child.id).all()
    goal_ids = [g.id for g in goals]
    completions = (
        db.query(GoalCompletion).filter(GoalCompletion.goal_id.in_(goal_ids)).all()
        if goal_ids
        else []
    )

    # Capsules: released fully; the requester's own (incl. sealed) fully; every
    # other sealed capsule as existence-only (no body/media) — same rule as the
    # read API.
    capsules_out: list[dict] = []
    for cap in db.query(TimeCapsule).filter(TimeCapsule.child_id == child.id).all():
        visible = (
            cap.status == CapsuleStatus.released or cap.created_by == requester_id
        )
        entry = {
            "id": _id(cap.id),
            "type": cap.type.value,
            "status": cap.status.value,
            "release_condition": cap.release_condition.value,
            "created_at": _dt(cap.created_at),
        }
        if visible:
            entry["body"] = cap.body
            entry["media_id"] = _id(cap.media_id)
        capsules_out.append(entry)

    # Predictions: the released Book + a sealed-year index (no content).
    rounds = db.query(PredictionRound).filter(PredictionRound.child_id == child.id).all()
    book: list[dict] = []
    for r in rounds:
        if r.status != PredictionRoundStatus.released:
            continue
        preds = db.query(Prediction).filter(Prediction.round_id == r.id).all()
        book.append(
            {
                "round_id": _id(r.id),
                "year": r.seals_on.year,
                "cloud_media_id": _id(r.cloud_media_id),
                "predictions": [
                    {
                        "body": p.body,
                        "author_name": _display_name(db, p.author_user_id),
                        "created_at": _dt(p.created_at),
                    }
                    for p in preds
                ],
            }
        )

    contributions = (
        db.query(Contribution).filter(Contribution.child_id == child.id).all()
    )
    fund = db.query(FundAccount).filter(FundAccount.child_id == child.id).first()
    fund_out = None
    if fund is not None:
        balance = (
            db.query(func.coalesce(func.sum(FundLedgerEntry.amount_cents), 0))
            .filter(FundLedgerEntry.account_id == fund.id)
            .scalar()
        )
        fund_out = {
            "currency": fund.currency,
            "account_status": fund.account_status.value,
            "balance_cents": int(balance or 0),
        }

    feed = db.query(FeedEvent).filter(FeedEvent.child_id == child.id).all()

    return {
        "profile": {
            "id": _id(child.id),
            "first_name": child.first_name,
            "birthdate": _dt(child.birthdate),
            "family_id": _id(child.family_id),
            "created_at": _dt(child.created_at),
        },
        "consent_records": [
            {
                "consent_type": c.consent_type.value,
                "granted_at": _dt(c.granted_at),
                "revoked_at": _dt(c.revoked_at),
            }
            for c in consent
        ],
        "vault_items": [_vault_row(v) for v in vault],
        "badges": [
            {"label": b.label, "icon": b.icon, "awarded_at": _dt(b.awarded_at)}
            for b in badges
        ],
        "goals": [
            {
                "id": _id(g.id),
                "title": g.title,
                "status": g.status.value,
                "reward_type": g.reward_type.value,
                "created_at": _dt(g.created_at),
            }
            for g in goals
        ],
        "goal_completions": [
            {"goal_id": _id(gc.goal_id), "completed_at": _dt(gc.completed_at)}
            for gc in completions
        ],
        "time_capsules": capsules_out,
        "predictions": {
            "book": book,
            "sealed_years": sorted(
                r.seals_on.year
                for r in rounds
                if r.status == PredictionRoundStatus.sealed
            ),
        },
        "contributions": [
            _contribution_row(db, c, include_child=False) for c in contributions
        ],
        "fund": fund_out,
        "feed_events": [
            {"type": f.type.value, "payload": f.payload, "created_at": _dt(f.created_at)}
            for f in feed
        ],
        "media": _child_media_manifest(db, child.id, requester_id),
    }


# --- entry points ------------------------------------------------------------


def export_member(db: Session, user: User) -> dict:
    """Member-only export: the adult's own profile, prefs, memberships, their
    contributions + owned/gifted Premium (money facts), and every piece of
    content THEY authored across their families (memories, milestones, capsules,
    legacy items, goals, comments, predictions, reactions) + their avatar."""
    memberships = (
        db.query(FamilyMember, Family)
        .join(Family, FamilyMember.family_id == Family.id)
        .filter(
            FamilyMember.user_id == user.id,
            FamilyMember.status == MemberStatus.active,
        )
        .all()
    )
    contributions = (
        db.query(Contribution).filter(Contribution.contributor_user_id == user.id).all()
    )
    grants = db.query(PremiumGrant).filter(PremiumGrant.granted_by_user_id == user.id).all()
    subs = db.query(FamilySubscription).filter(FamilySubscription.owner_user_id == user.id).all()
    predictions = db.query(Prediction).filter(Prediction.author_user_id == user.id).all()

    # Art. 15 breadth: the member's own operational/consent records. All
    # own-scoped (user_id == user.id / granted_by == user.id) — no other person's
    # data, and push subscriptions expose the endpoint only, never the crypto
    # keys (p256dh/auth).
    notifications = (
        db.query(Notification).filter(Notification.user_id == user.id).all()
    )
    push_subs = (
        db.query(PushSubscription).filter(PushSubscription.user_id == user.id).all()
    )
    nudges = db.query(FundNudge).filter(FundNudge.user_id == user.id).all()
    prompts = db.query(MemoryPrompt).filter(MemoryPrompt.user_id == user.id).all()
    votes = (
        db.query(CapsuleReleaseVote)
        .filter(CapsuleReleaseVote.user_id == user.id)
        .all()
    )
    consent_granted = (
        db.query(ConsentRecord).filter(ConsentRecord.granted_by == user.id).all()
    )

    return {
        "generated_at": _dt(utcnow()),
        "scope": "member",
        "subject": {"type": "member", "user_id": _id(user.id)},
        "profile": {
            "id": _id(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
            "created_at": _dt(user.created_at),
            "last_login_at": _dt(user.last_login_at),
        },
        "notification_preferences": _prefs_dict(db, user.id),
        "families": [
            {
                "family_id": _id(f.id),
                "name": f.name,
                "role": m.role.value,
                "joined_at": _dt(m.joined_at),
            }
            for m, f in memberships
        ],
        "contributions": [_contribution_row(db, c, include_child=True) for c in contributions],
        "premium": {
            "grants_gifted": [
                {
                    "id": _id(g.id),
                    "amount_cents": g.amount_cents,
                    "currency": g.currency,
                    "starts_at": _dt(g.starts_at),
                    "ends_at": _dt(g.ends_at),
                }
                for g in grants
            ],
            "subscriptions_owned": [
                {
                    "id": _id(s.id),
                    "plan": s.plan.value,
                    "status": s.status.value,
                    "current_period_end": _dt(s.current_period_end),
                }
                for s in subs
            ],
        },
        "authored": {
            "vault_items": [
                _vault_row(v)
                for v in db.query(VaultItem)
                .filter(VaultItem.created_by == user.id, VaultItem.deleted_at.is_(None))
                .all()
            ],
            "time_capsules": [
                {
                    "id": _id(cap.id),
                    "type": cap.type.value,
                    "status": cap.status.value,
                    "body": cap.body,
                    "created_at": _dt(cap.created_at),
                }
                for cap in db.query(TimeCapsule)
                .filter(TimeCapsule.created_by == user.id)
                .all()
            ],
            "legacy_items": [
                {"id": _id(l.id), "type": l.type.value, "title": l.title, "body": l.body}
                for l in db.query(LegacyItem)
                .filter(LegacyItem.created_by == user.id)
                .all()
            ],
            "comments": [
                {"body": c.body, "created_at": _dt(c.created_at)}
                for c in db.query(Comment)
                .filter(Comment.user_id == user.id, Comment.deleted_at.is_(None))
                .all()
            ],
            "predictions": [
                {"body": p.body, "created_at": _dt(p.created_at)} for p in predictions
            ],
            "reactions": [
                {"emoji": r.emoji, "target_type": r.target_type.value}
                for r in db.query(Reaction).filter(Reaction.user_id == user.id).all()
            ],
        },
        "notifications": [
            {
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "url": n.url,
                "read_at": _dt(n.read_at),
                "created_at": _dt(n.created_at),
            }
            for n in notifications
        ],
        "push_subscriptions": [
            # endpoint only — NEVER the encryption keys (p256dh/auth).
            {"endpoint": p.endpoint, "device": p.ua_label, "created_at": _dt(p.created_at)}
            for p in push_subs
        ],
        "fund_nudges": [
            {"child_id": _id(n.child_id), "created_at": _dt(n.created_at)} for n in nudges
        ],
        "memory_prompts": [
            {
                "family_id": _id(p.family_id),
                "child_id": _id(p.child_id),
                "period": p.period,
                "created_at": _dt(p.created_at),
            }
            for p in prompts
        ],
        "capsule_release_votes": [
            {"capsule_id": _id(v.capsule_id), "created_at": _dt(v.created_at)}
            for v in votes
        ],
        "consent_granted": [
            {
                "child_id": _id(c.child_id),
                "consent_type": c.consent_type.value,
                "granted_at": _dt(c.granted_at),
                "revoked_at": _dt(c.revoked_at),
            }
            for c in consent_granted
        ],
        "media": _scope_media_manifest(db, user_id=user.id),
        "media_retrieval": MEDIA_RETRIEVAL_NOTE,
    }


def export_child(db: Session, child: Child, requester_id: uuid.UUID) -> dict:
    return {
        "generated_at": _dt(utcnow()),
        "scope": "child",
        "subject": {"type": "child", "child_id": _id(child.id)},
        "media_retrieval": MEDIA_RETRIEVAL_NOTE,
        **{"child": _child_bundle(db, child, requester_id)},
    }


def export_family(db: Session, family: Family, requester_id: uuid.UUID) -> dict:
    members = (
        db.query(FamilyMember, User)
        .join(User, FamilyMember.user_id == User.id)
        .filter(FamilyMember.family_id == family.id)
        .all()
    )
    children = db.query(Child).filter(Child.family_id == family.id).all()
    legacy = db.query(LegacyItem).filter(LegacyItem.family_id == family.id).all()
    feed = db.query(FeedEvent).filter(FeedEvent.family_id == family.id).all()
    subs = db.query(FamilySubscription).filter(FamilySubscription.family_id == family.id).all()
    grants = db.query(PremiumGrant).filter(PremiumGrant.family_id == family.id).all()

    return {
        "generated_at": _dt(utcnow()),
        "scope": "family",
        "subject": {"type": "family", "family_id": _id(family.id)},
        "profile": {"id": _id(family.id), "name": family.name, "created_at": _dt(family.created_at)},
        # Art. 15(4): a family export must not disclose OTHER members' contact
        # details. Members are listed by display_name + role only — no email.
        "members": [
            {"display_name": u.display_name, "role": m.role.value}
            for m, u in members
        ],
        "children": [_child_bundle(db, c, requester_id) for c in children],
        "legacy_items": [
            {
                "id": _id(l.id),
                "type": l.type.value,
                "title": l.title,
                "body": l.body,
                "media_id": _id(l.media_id),
            }
            for l in legacy
        ],
        "feed_events": [
            {"type": f.type.value, "payload": f.payload, "created_at": _dt(f.created_at)}
            for f in feed
        ],
        "premium": {
            "subscriptions": [
                {"id": _id(s.id), "plan": s.plan.value, "status": s.status.value}
                for s in subs
            ],
            "grants": [
                {"id": _id(g.id), "amount_cents": g.amount_cents, "currency": g.currency}
                for g in grants
            ],
        },
        "media": _scope_media_manifest(db, family_id=family.id),
        "media_retrieval": MEDIA_RETRIEVAL_NOTE,
    }
