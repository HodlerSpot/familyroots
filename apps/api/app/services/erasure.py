"""Automated GDPR/PIPEDA erasure — the code form of docs/erasure-runbook.md §3-§6.

Three transactional entry points mirror the runbook's scope tree (§2):
`erase_member` (§3.A), `erase_child` (§3.B), `erase_family` (§3.C). Each encodes
the table-by-table walk in dependency order (leaf rows before the row they
reference), so the transaction never trips an FK constraint. The WS1 migration
(e7c4a1b9f0d2, + f4a9c2e7b1d8 for contributions.media_id) adds ON DELETE CASCADE
/ SET NULL as a prod backstop, but this walk is fully EXPLICIT and does not rely
on DB cascade, so it behaves identically under SQLite (tests, FKs unenforced)
and Postgres.

Post-commit side effects: deleting S3 bytes, calling Stripe, and sending emails
NEVER happen inside the open transaction. Each walk COLLECTS them into a
`PendingSideEffects` and returns it alongside the receipt; the caller commits the
DB transaction FIRST, then calls `effects.run()` (the ContributionSettlement /
NotificationBatch.deliver post-commit idiom). This guarantees a mid-erase failure
can only roll back to "nothing happened" — it can never leave deleted S3 bytes
with surviving DB rows, or parents emailed / Stripe cancelled for an erasure that
didn't commit. After commit the DB is source of truth; a byte-delete that then
fails only leaks an S3 object to reconcile, never the reverse.

Money discipline (CLAUDE.md, §3.D): the four financial tables — `contributions`,
`fund_ledger_entries`, `family_subscriptions`, `premium_grants` — are NEVER in a
delete loop and their money fields are NEVER edited. On erasure we sever only
the identity link (a `*_user_id` / `child_id` / `family_id` set to NULL) and
clear free-text that names a subject; the ledger is left completely untouched.
No financial-record PURGE is implemented (retention duration is counsel-gated,
WS0).

Stripe: Customer delete/anonymize + subscription cancel run ONLY when the live
Stripe backend is active (`settles_via_webhook`), so the whole walk no-ops
cleanly in local/test mode. Connect Express deauthorize is counsel-gated
(runbook §5) and deliberately NOT called — the account is retained and the
deferral is recorded in the receipt.

Every call returns an `ErasureReceipt` the caller logs as the §6 erasure-log
entry. Idempotent (a re-run of an already-erased subject is a no-op) and
single-writer (one transaction per call; the caller commits).
"""

import logging
import uuid

from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import (
    AdminAuditLog,
    Badge,
    BugReport,
    CallChildPresence,
    CallParticipant,
    Child,
    ChildRelationship,
    Comment,
    ConsentRecord,
    Contribution,
    Family,
    FamilyCall,
    FamilyInvite,
    FamilyMember,
    FamilyRole,
    FamilySubscription,
    FeedEvent,
    FundAccount,
    FundNudge,
    Goal,
    GoalCompletion,
    LegacyItem,
    MediaObject,
    MemberStatus,
    MemoryPrompt,
    Notification,
    NotificationPreference,
    PasswordReset,
    PlannedCall,
    Prediction,
    PredictionRound,
    PremiumGiftIntent,
    PremiumGrant,
    PushSubscription,
    Reaction,
    ReactionTargetType,
    SubscriptionStatus,
    TimeCapsule,
    User,
    utcnow,
)
from .payments import get_payment_provider
from .premium import handle_owner_departure
from .storage import get_storage

logger = logging.getLogger("futureroots.erasure")


class ErasureBlocked(Exception):
    """Raised when standing/state forbids an erasure (e.g. the sole parent of a
    family that still has children). The endpoint renders this as a 409."""


@dataclass
class PendingSideEffects:
    """External side effects COLLECTED during the erasure transaction and run
    only AFTER the caller commits — the ContributionSettlement /
    NotificationBatch.deliver post-commit idiom. Deleting S3 bytes or calling
    Stripe / sending email INSIDE the open transaction risks orphaned bytes or
    phantom Stripe calls + emails if the transaction later rolls back (H1/M2)."""

    media_keys: list[str] = field(default_factory=list)   # storage keys -> delete bytes
    actions: list[Callable[[], None]] = field(default_factory=list)  # stripe/email closures

    def schedule_media(self, storage_key: str) -> None:
        self.media_keys.append(storage_key)

    def defer(self, action: Callable[[], None]) -> None:
        self.actions.append(action)

    def run(self) -> None:
        """Post-commit: delete bytes, then run the Stripe/email closures. Each is
        best-effort + logged — the DB erasure already committed, so a failure
        here is a reconcile item (a leaked object / an un-cancelled sub the admin
        catches in the Stripe dashboard), never a data-integrity problem."""
        storage = get_storage()
        for key in self.media_keys:
            try:
                storage.delete(key)
            except Exception:  # noqa: BLE001 — best-effort; DB row already gone
                logger.warning("erasure: media byte delete failed for %s", key)
        for action in self.actions:
            try:
                action()
            except Exception:  # noqa: BLE001 — best-effort; reconcile from the log
                logger.warning("erasure: deferred side effect failed", exc_info=True)


@dataclass
class ErasureReceipt:
    """The auto-generated §6 erasure-log entry, assembled from the transaction."""

    scope: str
    user_ids: list[str] = field(default_factory=list)
    child_ids: list[str] = field(default_factory=list)
    family_ids: list[str] = field(default_factory=list)
    deleted: dict[str, int] = field(default_factory=dict)          # table -> rows hard-deleted
    anonymized: dict[str, int] = field(default_factory=dict)       # table -> rows severed/retained
    retained: list[str] = field(default_factory=list)              # financial tables kept (§3.D)
    media_keys: list[str] = field(default_factory=list)            # storage keys scheduled (§4)
    consent_revoked: int = 0
    stripe_actions: list[str] = field(default_factory=list)
    orphaned_user_ids: list[str] = field(default_factory=list)     # left memberless, NOT erased (§3.C)

    def _bump(self, bucket: dict[str, int], table: str, n: int) -> None:
        if n:
            bucket[table] = bucket.get(table, 0) + n

    def deleted_rows(self, table: str, n: int) -> None:
        self._bump(self.deleted, table, n)

    def anonymized_rows(self, table: str, n: int) -> None:
        self._bump(self.anonymized, table, n)
        if table not in self.retained and table in _FINANCIAL_TABLES:
            self.retained.append(table)

    def as_log(self) -> dict:
        return {
            "event": "erasure",
            "scope": self.scope,
            "subject_users": self.user_ids,
            "subject_children": self.child_ids,
            "subject_families": self.family_ids,
            "tables_hard_deleted": self.deleted,
            "tables_anonymized": self.anonymized,
            "tables_retained_carveout": sorted(set(self.retained)),
            "media_objects_deleted": len(self.media_keys),
            "consent_revoked": self.consent_revoked,
            "stripe_actions": self.stripe_actions,
            "users_left_orphaned": self.orphaned_user_ids,
            "legal_basis_retained": "GDPR Art. 17(3)(b)/(e)",
        }


_FINANCIAL_TABLES = {
    "contributions",
    "fund_ledger_entries",
    "family_subscriptions",
    "premium_grants",
}


# --- primitives --------------------------------------------------------------


def _delete(db: Session, model, *conditions) -> int:
    """Bulk hard-delete matching rows; returns the count. Ordered by the caller
    (leaf tables first), so cascade is never relied upon."""
    n = db.query(model).filter(*conditions).delete(synchronize_session=False)
    db.flush()
    return n


def _sever(db: Session, model, column, *conditions) -> int:
    """Bulk set `column = NULL` (the §3.D / author-sever identity decoupling)."""
    n = (
        db.query(model)
        .filter(*conditions)
        .update({column: None}, synchronize_session=False)
    )
    db.flush()
    return n


def erase_media_for(
    db: Session,
    effects: PendingSideEffects,
    *,
    child_id: uuid.UUID | None = None,
    family_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> list[str]:
    """Walk `media_objects` for one subject scope, delete the ROWS, and SCHEDULE
    the underlying bytes for post-commit deletion via the proven
    `MediaStorage.delete()` primitive (§4). Returns the storage keys scheduled.
    MUST be called only after every row that references these media (vault_items,
    time_capsules, *.avatar_media_id, cloud_media_id, contributions.media_id) has
    been deleted or nulled, so no FK dangles."""
    query = db.query(MediaObject)
    if child_id is not None:
        query = query.filter(MediaObject.child_id == child_id)
    elif family_id is not None:
        query = query.filter(MediaObject.family_id == family_id)
    elif user_id is not None:
        query = query.filter(MediaObject.user_id == user_id)
    else:
        return []
    keys: list[str] = []
    for media in query.all():
        effects.schedule_media(media.storage_key)  # bytes deleted post-commit (§4 order)
        keys.append(media.storage_key)
        db.delete(media)
    db.flush()
    return keys


def _schedule_media_delete(
    db: Session,
    media_id: uuid.UUID | None,
    receipt: ErasureReceipt,
    effects: PendingSideEffects,
) -> None:
    """Delete one media_object ROW now and SCHEDULE its bytes for post-commit
    deletion. Idempotent: a missing media row (already swept elsewhere in the
    same walk) is a no-op, so overlapping scopes never double-delete."""
    if media_id is None:
        return
    media = db.get(MediaObject, media_id)
    if media is None:
        return
    effects.schedule_media(media.storage_key)
    receipt.media_keys.append(media.storage_key)
    db.delete(media)
    db.flush()


def _delete_feed_events(db: Session, receipt: ErasureReceipt, *conditions) -> None:
    """Delete feed events (and their comment threads + reactions) matching the
    conditions. Comments can't outlive their event; reactions key on an opaque
    target_id (no FK) so they are cleaned up but never block the delete."""
    fe_ids = [row[0] for row in db.query(FeedEvent.id).filter(*conditions).all()]
    if not fe_ids:
        return
    comment_ids = [
        row[0]
        for row in db.query(Comment.id).filter(Comment.feed_event_id.in_(fe_ids)).all()
    ]
    if comment_ids:
        receipt.deleted_rows(
            "reactions",
            _delete(
                db,
                Reaction,
                Reaction.target_type == ReactionTargetType.comment,
                Reaction.target_id.in_(comment_ids),
            ),
        )
        receipt.deleted_rows(
            "comments", _delete(db, Comment, Comment.id.in_(comment_ids))
        )
    receipt.deleted_rows(
        "reactions",
        _delete(
            db,
            Reaction,
            Reaction.target_type == ReactionTargetType.feed_event,
            Reaction.target_id.in_(fe_ids),
        ),
    )
    receipt.deleted_rows("feed_events", _delete(db, FeedEvent, FeedEvent.id.in_(fe_ids)))


def _delete_calls(db: Session, receipt: ErasureReceipt, call_ids: list[uuid.UUID]) -> None:
    if not call_ids:
        return
    receipt.deleted_rows(
        "call_child_presence",
        _delete(db, CallChildPresence, CallChildPresence.call_id.in_(call_ids)),
    )
    receipt.deleted_rows(
        "call_participants",
        _delete(db, CallParticipant, CallParticipant.call_id.in_(call_ids)),
    )
    receipt.deleted_rows("family_calls", _delete(db, FamilyCall, FamilyCall.id.in_(call_ids)))


# --- §3.B child-profile erasure ---------------------------------------------


def erase_child(
    db: Session,
    child_id: uuid.UUID,
    *,
    receipt: ErasureReceipt | None = None,
    effects: PendingSideEffects | None = None,
) -> tuple[ErasureReceipt, PendingSideEffects]:
    """Erase one child's profile (§3.B). Leaf tables first, then `children`.
    Financial rows are RETAINED with the child link severed; the child's media
    (vault, avatar, capsule attachments, the sealed keepsake PNG) is deleted."""
    receipt = receipt or ErasureReceipt(scope="child")
    effects = effects if effects is not None else PendingSideEffects()
    child = db.get(Child, child_id)
    if child is None:
        return receipt, effects  # idempotent: already gone
    receipt.child_ids.append(str(child_id))
    now = utcnow()

    # Retained contributions (§3.D): sever child link, drop child-linked free
    # text + the attached personal video message (§4.5). Money fields untouched.
    # Null contributions.media_id BEFORE the media row is scheduled for deletion
    # (§4.5): the FK ref must be gone before its target row leaves.
    child_contribs = (
        db.query(Contribution).filter(Contribution.child_id == child_id).all()
    )
    contrib_media_ids: list[uuid.UUID] = []
    for contribution in child_contribs:
        if contribution.media_id is not None:
            contrib_media_ids.append(contribution.media_id)
        contribution.media_id = None               # null the FK ref FIRST (§4.5)
        contribution.trigger_feed_event_id = None  # points at a feed event we delete below
        contribution.message = None                # child-linked text, not a money fact
        contribution.child_id = None               # sever; ROW RETAINED
    if child_contribs:
        db.flush()
        receipt.anonymized_rows("contributions", len(child_contribs))
    for media_id in contrib_media_ids:
        _schedule_media_delete(db, media_id, receipt, effects)

    # Fund account (§3.B/§3.D): RETAIN as the anchor for the append-only ledger;
    # sever the child link. Connect deauthorize is counsel-gated (runbook §5).
    for account in db.query(FundAccount).filter(FundAccount.child_id == child_id).all():
        if account.stripe_account_id:
            receipt.stripe_actions.append(
                f"connect_account_retained:{account.stripe_account_id} "
                "(deauthorize deferred — counsel §5)"
            )
        account.child_id = None
        receipt.anonymized_rows("fund_accounts", 1)
        if "fund_ledger_entries" not in receipt.retained:
            receipt.retained.append("fund_ledger_entries")
    db.flush()

    # Consent (§3.B): revoke open records, then delete them all.
    receipt.consent_revoked += (
        db.query(ConsentRecord)
        .filter(ConsentRecord.child_id == child_id, ConsentRecord.revoked_at.is_(None))
        .update({ConsentRecord.revoked_at: now}, synchronize_session=False)
    )
    db.flush()
    receipt.deleted_rows(
        "consent_records", _delete(db, ConsentRecord, ConsentRecord.child_id == child_id)
    )

    # Time capsules (incl. sealed) + their release votes.
    capsule_ids = [
        row[0]
        for row in db.query(TimeCapsule.id).filter(TimeCapsule.child_id == child_id).all()
    ]
    if capsule_ids:
        from ..models import CapsuleReleaseVote

        receipt.deleted_rows(
            "capsule_release_votes",
            _delete(db, CapsuleReleaseVote, CapsuleReleaseVote.capsule_id.in_(capsule_ids)),
        )
    receipt.deleted_rows(
        "time_capsules", _delete(db, TimeCapsule, TimeCapsule.child_id == child_id)
    )

    # Achievement economy: badges + goal completions before goals they reference.
    receipt.deleted_rows("badges", _delete(db, Badge, Badge.child_id == child_id))
    goal_ids = [row[0] for row in db.query(Goal.id).filter(Goal.child_id == child_id).all()]
    if goal_ids:
        receipt.deleted_rows(
            "goal_completions",
            _delete(db, GoalCompletion, GoalCompletion.goal_id.in_(goal_ids)),
        )
    receipt.deleted_rows("goals", _delete(db, Goal, Goal.child_id == child_id))

    # Future Predictions (new data): predictions -> rounds. The keepsake PNGs are
    # child-scoped media, swept below with the rest of the child's media.
    round_ids = [
        row[0]
        for row in db.query(PredictionRound.id)
        .filter(PredictionRound.child_id == child_id)
        .all()
    ]
    if round_ids:
        receipt.deleted_rows(
            "predictions", _delete(db, Prediction, Prediction.round_id.in_(round_ids))
        )
    receipt.deleted_rows(
        "prediction_rounds",
        _delete(db, PredictionRound, PredictionRound.child_id == child_id),
    )

    # Vault items (media swept below).
    from ..models import VaultItem

    receipt.deleted_rows("vault_items", _delete(db, VaultItem, VaultItem.child_id == child_id))

    # Ephemeral / non-financial child rows. memory_prompts deleted EXPLICITLY
    # (not just via the DB CASCADE) so the walk behaves identically under SQLite.
    receipt.deleted_rows("fund_nudges", _delete(db, FundNudge, FundNudge.child_id == child_id))
    receipt.deleted_rows(
        "memory_prompts", _delete(db, MemoryPrompt, MemoryPrompt.child_id == child_id)
    )
    receipt.deleted_rows(
        "call_child_presence",
        _delete(db, CallChildPresence, CallChildPresence.child_id == child_id),
    )

    # Feed events about this child (+ their comment threads).
    _delete_feed_events(db, receipt, FeedEvent.child_id == child_id)

    # Family Graph edges to the child.
    receipt.deleted_rows(
        "child_relationships",
        _delete(db, ChildRelationship, ChildRelationship.child_id == child_id),
    )

    # Now that nothing references the child's media, sweep the bytes + rows.
    child.avatar_media_id = None
    db.flush()
    receipt.media_keys.extend(erase_media_for(db, effects, child_id=child_id))

    receipt.deleted_rows("children", _delete(db, Child, Child.id == child_id))
    return receipt, effects


# --- §3.A member-only erasure ------------------------------------------------


def _is_last_parent_blocking(db: Session, user_id: uuid.UUID) -> str | None:
    """A member erasure is blocked while the user is the sole active parent of a
    family that still has children or other active members (children must never
    be orphaned — mirrors the leave-family guard). Returns a family id string to
    block on, or None."""
    parent_memberships = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.user_id == user_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role == FamilyRole.parent,
        )
        .all()
    )
    for membership in parent_memberships:
        fid = membership.family_id
        other_parents = (
            db.query(FamilyMember)
            .filter(
                FamilyMember.family_id == fid,
                FamilyMember.status == MemberStatus.active,
                FamilyMember.role == FamilyRole.parent,
                FamilyMember.user_id != user_id,
            )
            .count()
        )
        if other_parents > 0:
            continue
        has_children = db.query(Child.id).filter(Child.family_id == fid).first() is not None
        other_members = (
            db.query(FamilyMember)
            .filter(
                FamilyMember.family_id == fid,
                FamilyMember.status == MemberStatus.active,
                FamilyMember.user_id != user_id,
            )
            .first()
            is not None
        )
        if has_children or other_members:
            return str(fid)
    return None


def erase_member(
    db: Session,
    user_id: uuid.UUID,
    *,
    receipt: ErasureReceipt | None = None,
    effects: PendingSideEffects | None = None,
) -> tuple[ErasureReceipt, PendingSideEffects]:
    """Erase one adult account globally (§3.A). Family history + financial rows
    SURVIVE with the author/identity link severed (SET NULL); everything that is
    the user's own personal data is hard-deleted; then the `users` row itself."""
    receipt = receipt or ErasureReceipt(scope="member")
    effects = effects if effects is not None else PendingSideEffects()
    user = db.get(User, user_id)
    if user is None:
        return receipt, effects  # idempotent
    blocked_family = _is_last_parent_blocking(db, user_id)
    if blocked_family is not None:
        raise ErasureBlocked(
            "You're the only parent of a family that still has children. "
            "Erase that family (or add another parent) before deleting your account."
        )
    receipt.user_ids.append(str(user_id))

    # A departing subscription owner shouldn't keep paying (matches leave_family).
    # The DB mutation runs in-transaction; the Stripe cancel + parent emails are
    # DEFERRED to post-commit (H1) via the effects sink.
    for membership in (
        db.query(FamilyMember)
        .filter(FamilyMember.user_id == user_id, FamilyMember.status == MemberStatus.active)
        .all()
    ):
        handle_owner_departure(db, membership.family_id, user_id, defer=effects.defer)

    # --- §3.D / Art. 17: delete the erased person's OWN contribution-video
    #     media. It's child-scoped (media.child_id), so the avatar sweep below
    #     misses it. Null contributions.media_id BEFORE scheduling the media row
    #     for deletion; the money row itself is RETAINED and severed below.
    own_contribs = (
        db.query(Contribution).filter(Contribution.contributor_user_id == user_id).all()
    )
    own_contrib_media_ids: list[uuid.UUID] = []
    for contribution in own_contribs:
        if contribution.media_id is not None:
            own_contrib_media_ids.append(contribution.media_id)
            contribution.media_id = None
    if own_contrib_media_ids:
        db.flush()
        for media_id in own_contrib_media_ids:
            # Idempotent: under whole-family erasure erase_child already swept
            # these, so a missing row is a no-op (guarded double-delete).
            _schedule_media_delete(db, media_id, receipt, effects)

    # --- §3.D financial anonymize: sever identity, RETAIN the money rows ---
    receipt.anonymized_rows(
        "contributions",
        _sever(db, Contribution, Contribution.contributor_user_id,
               Contribution.contributor_user_id == user_id),
    )
    receipt.anonymized_rows(
        "family_subscriptions",
        _sever(db, FamilySubscription, FamilySubscription.owner_user_id,
               FamilySubscription.owner_user_id == user_id),
    )
    granted = (
        db.query(PremiumGrant)
        .filter(PremiumGrant.granted_by_user_id == user_id)
        .update(
            {PremiumGrant.granted_by_user_id: None, PremiumGrant.message: None},
            synchronize_session=False,
        )
    )
    _sever(db, PremiumGrant, PremiumGrant.voided_by_user_id,
           PremiumGrant.voided_by_user_id == user_id)
    receipt.anonymized_rows("premium_grants", granted)
    # premium_gift_intents: gifter link + message nulled — an ANONYMIZE (UPDATE
    # to NULL), not a delete. The row (a non-financial staging record) survives.
    receipt.anonymized_rows(
        "premium_gift_intents",
        db.query(PremiumGiftIntent)
        .filter(PremiumGiftIntent.gifter_user_id == user_id)
        .update(
            {PremiumGiftIntent.gifter_user_id: None, PremiumGiftIntent.message: None},
            synchronize_session=False,
        ),
    )
    db.flush()

    # Stripe Customer (adult billing): delete/anonymize — Stripe mode only, and
    # DEFERRED to post-commit (H1: never call Stripe inside the transaction).
    provider = get_payment_provider()
    if user.stripe_customer_id and provider.settles_via_webhook:
        customer_id = user.stripe_customer_id
        effects.defer(lambda cid=customer_id: provider.delete_or_anonymize_customer(cid))
        receipt.stripe_actions.append(f"customer_deleted:{customer_id}")
    user.stripe_customer_id = None
    db.flush()

    # --- author-sever (SET NULL): the row is family history / an anchor and
    #     survives with a severed reference ---
    from ..models import VaultItem

    for model, column in (
        (VaultItem, VaultItem.created_by),
        (TimeCapsule, TimeCapsule.created_by),
        (LegacyItem, LegacyItem.created_by),
        (Goal, Goal.created_by),
        (GoalCompletion, GoalCompletion.verified_by),
        (FeedEvent, FeedEvent.actor_user_id),
        (Family, Family.created_by),
        (FundAccount, FundAccount.setup_by),
        (FamilyMember, FamilyMember.invited_by),
        (AdminAuditLog, AdminAuditLog.admin_user_id),
        (BugReport, BugReport.reporter_user_id),
    ):
        receipt.anonymized_rows(model.__tablename__, _sever(db, model, column, column == user_id))
    # Media the user uploaded for a child/family survives with a severed uploader.
    _sever(db, MediaObject, MediaObject.uploaded_by,
           MediaObject.uploaded_by == user_id, MediaObject.user_id != user_id)

    # --- hard-delete the user's own personal data ---
    from ..models import CapsuleReleaseVote

    receipt.deleted_rows(
        "reactions", _delete(db, Reaction, Reaction.user_id == user_id)
    )
    receipt.deleted_rows("comments", _delete(db, Comment, Comment.user_id == user_id))
    receipt.deleted_rows(
        "capsule_release_votes",
        _delete(db, CapsuleReleaseVote, CapsuleReleaseVote.user_id == user_id),
    )
    receipt.deleted_rows("fund_nudges", _delete(db, FundNudge, FundNudge.user_id == user_id))
    receipt.deleted_rows(
        "memory_prompts", _delete(db, MemoryPrompt, MemoryPrompt.user_id == user_id)
    )
    receipt.deleted_rows(
        "child_relationships",
        _delete(db, ChildRelationship, ChildRelationship.user_id == user_id),
    )
    # The user's own words in the Book of Predictions are hard-deleted (§3.A
    # comment handling: the requester's own free text goes when they do).
    receipt.deleted_rows(
        "predictions", _delete(db, Prediction, Prediction.author_user_id == user_id)
    )
    receipt.deleted_rows(
        "notification_preferences",
        _delete(db, NotificationPreference, NotificationPreference.user_id == user_id),
    )
    receipt.deleted_rows(
        "push_subscriptions",
        _delete(db, PushSubscription, PushSubscription.user_id == user_id),
    )
    receipt.deleted_rows(
        "notifications", _delete(db, Notification, Notification.user_id == user_id)
    )
    receipt.deleted_rows(
        "password_resets", _delete(db, PasswordReset, PasswordReset.user_id == user_id)
    )
    receipt.deleted_rows(
        "family_invites", _delete(db, FamilyInvite, FamilyInvite.invited_by == user_id)
    )

    # Video-call rows: ended calls store no A/V and emit no feed events, so the
    # user's participation + any call they started are simply removed.
    receipt.deleted_rows(
        "call_child_presence",
        _delete(db, CallChildPresence, CallChildPresence.marked_by == user_id),
    )
    receipt.deleted_rows(
        "call_participants",
        _delete(db, CallParticipant, CallParticipant.user_id == user_id),
    )
    receipt.deleted_rows("planned_calls", _delete(db, PlannedCall, PlannedCall.set_by == user_id))
    started_call_ids = [
        row[0] for row in db.query(FamilyCall.id).filter(FamilyCall.started_by == user_id).all()
    ]
    _delete_calls(db, receipt, started_call_ids)

    # The user's own media (their headshot). Null the reference first.
    user.avatar_media_id = None
    db.flush()
    receipt.media_keys.extend(erase_media_for(db, effects, user_id=user_id))

    # Membership rows, then the account itself.
    receipt.deleted_rows(
        "family_members", _delete(db, FamilyMember, FamilyMember.user_id == user_id)
    )
    receipt.deleted_rows("users", _delete(db, User, User.id == user_id))
    return receipt, effects


# --- §3.C whole-family erasure ----------------------------------------------


def erase_family(
    db: Session,
    family_id: uuid.UUID,
    *,
    receipt: ErasureReceipt | None = None,
    effects: PendingSideEffects | None = None,
) -> tuple[ErasureReceipt, PendingSideEffects]:
    """Erase an entire family (§3.C): every child (§3.B), then all family-level
    content, then the `families` row. Financial rows are retained with the
    family link severed.

    Other adults are NOT auto-erased: this is a per-family action, not
    per-user-everywhere (runbook §2/§3.C). An adult left with no remaining
    membership becomes a memberless account they can self-erase later (DELETE
    /me) — destroying a non-consenting third party's account + their Stripe
    customer with no step-up/consent from them would be a consent violation.
    Such orphaned adults are recorded on the receipt (`users_left_orphaned`)."""
    receipt = receipt or ErasureReceipt(scope="family")
    effects = effects if effects is not None else PendingSideEffects()
    family = db.get(Family, family_id)
    if family is None:
        return receipt, effects  # idempotent
    receipt.family_ids.append(str(family_id))

    member_user_ids = [
        row[0]
        for row in db.query(FamilyMember.user_id)
        .filter(FamilyMember.family_id == family_id, FamilyMember.status == MemberStatus.active)
        .all()
    ]

    # Stop a live subscription: a deleted family shouldn't keep billing to period
    # end, so cancel NOW (not cancel-at-period-end). Stripe only, and DEFERRED to
    # post-commit (H1: never call Stripe inside the transaction).
    provider = get_payment_provider()
    if provider.settles_via_webhook:
        for sub in (
            db.query(FamilySubscription)
            .filter(
                FamilySubscription.family_id == family_id,
                FamilySubscription.status != SubscriptionStatus.canceled,
            )
            .all()
        ):
            sub_id = sub.stripe_subscription_id
            effects.defer(
                lambda sid=sub_id: provider.cancel_subscription_now(
                    sid, refund_latest_charge=False
                )
            )
            receipt.stripe_actions.append(f"subscription_canceled_now:{sub_id}")

    # Every child (leaf-first cascade per §3.B).
    for row in db.query(Child.id).filter(Child.family_id == family_id).all():
        erase_child(db, row[0], receipt=receipt, effects=effects)

    # Remaining family-level content.
    _delete_feed_events(db, receipt, FeedEvent.family_id == family_id)
    receipt.deleted_rows("legacy_items", _delete(db, LegacyItem, LegacyItem.family_id == family_id))
    receipt.deleted_rows("family_invites", _delete(db, FamilyInvite, FamilyInvite.family_id == family_id))
    family_call_ids = [
        row[0] for row in db.query(FamilyCall.id).filter(FamilyCall.family_id == family_id).all()
    ]
    _delete_calls(db, receipt, family_call_ids)
    receipt.deleted_rows("planned_calls", _delete(db, PlannedCall, PlannedCall.family_id == family_id))
    receipt.deleted_rows("memory_prompts", _delete(db, MemoryPrompt, MemoryPrompt.family_id == family_id))
    receipt.deleted_rows("notifications", _delete(db, Notification, Notification.family_id == family_id))
    receipt.deleted_rows(
        "premium_gift_intents",
        _delete(db, PremiumGiftIntent, PremiumGiftIntent.family_id == family_id),
    )
    from ..models import PremiumEmailLog

    receipt.deleted_rows(
        "premium_email_log", _delete(db, PremiumEmailLog, PremiumEmailLog.family_id == family_id)
    )

    # Retained financial rows (§3.D): sever the family link; clear grant text.
    receipt.anonymized_rows(
        "family_subscriptions",
        _sever(db, FamilySubscription, FamilySubscription.family_id,
               FamilySubscription.family_id == family_id),
    )
    grants = (
        db.query(PremiumGrant)
        .filter(PremiumGrant.family_id == family_id)
        .update(
            {PremiumGrant.family_id: None, PremiumGrant.message: None},
            synchronize_session=False,
        )
    )
    receipt.anonymized_rows("premium_grants", grants)
    db.flush()

    # Family-scoped media (legacy attachments) — rows above already deleted.
    receipt.media_keys.extend(erase_media_for(db, effects, family_id=family_id))

    receipt.deleted_rows("family_members", _delete(db, FamilyMember, FamilyMember.family_id == family_id))
    receipt.deleted_rows("families", _delete(db, Family, Family.id == family_id))

    # Adults whose only family this was are now memberless. We do NOT erase their
    # accounts (no consent/step-up from them) — record them so the operator can
    # follow up; they can self-erase via DELETE /me.
    for uid in member_user_ids:
        remaining = (
            db.query(FamilyMember.id).filter(FamilyMember.user_id == uid).first() is not None
        )
        if not remaining:
            receipt.orphaned_user_ids.append(str(uid))

    return receipt, effects
