"""FutureRoots Premium settlement — the ONLY writers of family_subscriptions
and premium_grants.

Called from: the signed Stripe webhook handlers, the /sync reconcile (which
reads live Stripe state), the local backend's synchronous settle in
routers/premium.py, and the admin reconcile action. Mirrors the
settle_contribution discipline: status guard + unique-key idempotency + feed
event + emails, all in one place.

Trust model:
- Subscription mirroring converges to LIVE Stripe state (subscriptions
  retrieve) — the triggering event is only a trigger, so ordering and replays
  never matter.
- Gift settlement is insert-or-return on the unique checkout session id.
- Feed events and activation/gift emails ride row CREATION, which the unique
  keys make exactly-once. Everything else dedupes through premium_email_log.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Family,
    FamilyMember,
    FamilyRole,
    FamilySubscription,
    FeedEventType,
    MemberStatus,
    PremiumEmailLog,
    PremiumGiftIntent,
    PremiumGrant,
    SubscriptionPlan,
    SubscriptionStatus,
    User,
    utcnow,
)
from . import premium_emails as copy
from .email import get_email_sender
from .entitlements import family_is_premium, premium_until
from .feed import emit
from .payments import SubscriptionState, get_payment_provider

logger = logging.getLogger(__name__)

# Display/refund fallbacks only — the money truth is always the Stripe Price.
PLAN_PRICE_CENTS = {
    SubscriptionPlan.monthly: 999,
    SubscriptionPlan.annual: 9900,
}

GIFT_ENDING_SOON_WINDOW = timedelta(days=7)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _send(user: User, payload: dict) -> None:
    get_email_sender().send(to=user.email, **payload)


def _active_parents(db: Session, family_id: uuid.UUID) -> list[User]:
    return (
        db.query(User)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role == FamilyRole.parent,
        )
        .all()
    )


def _log_once(db: Session, family_id: uuid.UUID, kind: str, dedupe_key: str) -> bool:
    """Send-once guard: insert into premium_email_log (unique on
    kind+dedupe_key) and send only when the insert wins. The pre-check covers
    replays (the common case); the unique constraint is the race-safe backstop
    for truly concurrent deliveries — the loser's transaction rolls back and
    the next delivery/sync re-converges the mirror."""
    exists = (
        db.query(PremiumEmailLog.id)
        .filter(PremiumEmailLog.kind == kind, PremiumEmailLog.dedupe_key == dedupe_key)
        .first()
    )
    if exists is not None:
        return False
    db.add(PremiumEmailLog(family_id=family_id, kind=kind, dedupe_key=dedupe_key))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return False
    return True


# --- Stripe → ours mapping ---

def stripe_status_to_ours(raw: str) -> SubscriptionStatus | None:
    if raw in ("active", "trialing"):
        return SubscriptionStatus.active
    if raw == "past_due":
        return SubscriptionStatus.past_due
    if raw in ("canceled", "unpaid", "incomplete_expired"):
        return SubscriptionStatus.canceled
    return None  # incomplete (and anything unknown): ignore, never mirror


def plan_for_price(price_id: str) -> SubscriptionPlan:
    if price_id and price_id == settings.stripe_price_annual:
        return SubscriptionPlan.annual
    if price_id and price_id == settings.stripe_price_monthly:
        return SubscriptionPlan.monthly
    # Local synthetic price ids ("price_local_annual") and safety fallback.
    if "annual" in (price_id or ""):
        return SubscriptionPlan.annual
    return SubscriptionPlan.monthly


def _plan_for_state(state: SubscriptionState) -> SubscriptionPlan:
    meta_plan = (state.metadata or {}).get("plan")
    if meta_plan in (p.value for p in SubscriptionPlan):
        return SubscriptionPlan(meta_plan)
    return plan_for_price(state.price_id)


# --- subscription mirror ---

def apply_subscription_state(
    db: Session,
    state: SubscriptionState,
    *,
    family_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> FamilySubscription | None:
    """Upsert the mirror row keyed on stripe_subscription_id, converging to
    `state`. On FIRST creation of a row for a not-previously-premium family:
    emit feed_events.premium_activated + 'Premium activated' email to all
    active parents (exactly once — creation is the idempotency gate).
    On transition to canceled: run the premium-ended path. Enforces the
    double-subscribe guard before insert."""
    status = stripe_status_to_ours(state.status)
    if status is None:
        return None

    row = (
        db.query(FamilySubscription)
        .filter(FamilySubscription.stripe_subscription_id == state.subscription_id)
        .first()
    )
    meta = state.metadata or {}
    fid = family_id or _uuid_or_none(meta.get("family_id"))
    owner_id = owner_user_id or _uuid_or_none(meta.get("owner_user_id"))

    if row is None:
        if status == SubscriptionStatus.canceled:
            return None  # never mirrored, already dead — nothing to record
        if fid is None or owner_id is None:
            return None  # not ours (another product on the same account)

        # Double-subscribe guard, layer 3: a different live subscription
        # already exists for this family → cancel + refund the newcomer.
        existing_live = (
            db.query(FamilySubscription)
            .filter(
                FamilySubscription.family_id == fid,
                FamilySubscription.status != SubscriptionStatus.canceled,
            )
            .first()
        )
        if existing_live is not None:
            _handle_duplicate_subscription(db, state, fid, owner_id)
            return None

        was_premium = family_is_premium(db, fid)
        row = FamilySubscription(
            family_id=fid,
            owner_user_id=owner_id,
            stripe_customer_id=state.customer_id,
            stripe_subscription_id=state.subscription_id,
            plan=_plan_for_state(state),
            status=status,
            current_period_end=state.current_period_end,
            cancel_at_period_end=state.cancel_at_period_end,
        )
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            # Lost a race on the partial unique index — same duplicate case.
            db.rollback()
            _handle_duplicate_subscription(db, state, fid, owner_id)
            return None
        if not was_premium:
            _announce_activation(db, row)
        return row

    # Update path: converge the mirror to live truth.
    was_canceled = row.status == SubscriptionStatus.canceled
    row.status = status
    row.plan = _plan_for_state(state)
    row.current_period_end = state.current_period_end
    row.cancel_at_period_end = state.cancel_at_period_end
    if state.customer_id:
        row.stripe_customer_id = state.customer_id
    row.updated_at = utcnow()
    db.flush()
    if status == SubscriptionStatus.canceled and not was_canceled:
        _maybe_premium_ended(db, row)
    return row


def _announce_activation(db: Session, row: FamilySubscription) -> None:
    family = db.get(Family, row.family_id)
    emit(
        db,
        family_id=row.family_id,
        actor_user_id=row.owner_user_id,
        type=FeedEventType.premium_activated,
        payload={
            "family_name": family.name if family else "",
            "plan": row.plan.value,
        },
    )
    for parent in _active_parents(db, row.family_id):
        _send(
            parent,
            copy.premium_activated(
                parent_name=parent.display_name,
                plan=row.plan.value,
                renewal_date=_aware(row.current_period_end),
                family_id=row.family_id,
            ),
        )


def _maybe_premium_ended(db: Session, row: FamilySubscription) -> None:
    """After a terminal subscription status: downgrade email — unless a live
    grant still covers the family (spec: gift coverage suppresses it)."""
    if family_is_premium(db, row.family_id):
        return
    key = f"{row.family_id}:{_aware(row.current_period_end).isoformat()}"
    if not _log_once(db, row.family_id, "premium_ended", key):
        return
    recipients = {p.id: p for p in _active_parents(db, row.family_id)}
    owner = db.get(User, row.owner_user_id)
    if owner is not None:
        recipients.setdefault(owner.id, owner)
    for user in recipients.values():
        _send(
            user,
            copy.premium_ended(parent_name=user.display_name, family_id=row.family_id),
        )


def _handle_duplicate_subscription(
    db: Session,
    state: SubscriptionState,
    family_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> None:
    """Layer 3 of the double-subscribe guard: immediately cancel + refund the
    accidental second subscription and apologize to that parent. Deduped per
    subscription id so webhook replays don't re-email."""
    get_payment_provider().cancel_subscription_now(
        state.subscription_id, refund_latest_charge=True
    )
    if not _log_once(db, family_id, "duplicate_subscription", state.subscription_id):
        return
    parent = db.get(User, owner_user_id)
    if parent is None:
        return
    plan = _plan_for_state(state)
    _send(
        parent,
        copy.double_subscribe_apology(
            parent_name=parent.display_name,
            amount_cents=PLAN_PRICE_CENTS[plan],
            family_id=family_id,
        ),
    )


# --- gifts ---

def apply_gift_paid(
    db: Session,
    *,
    session_id: str,
    payment_intent_id: str | None,
    amount_cents: int,
    currency: str,
    family_id: uuid.UUID,
    gifter_user_id: uuid.UUID,
) -> PremiumGrant | None:
    """Idempotent on the unique stripe_checkout_session_id (returns the
    existing grant on replay). Grant stacking math runs under a row lock on
    the family: starts_at = max(now, latest unvoided ends_at); grants never
    overlap each other but may overlap subscription coverage by design."""
    existing = (
        db.query(PremiumGrant)
        .filter(PremiumGrant.stripe_checkout_session_id == session_id)
        .first()
    )
    if existing is not None:
        return existing

    # Serialize concurrent gifts to one family (no-op lock on SQLite).
    db.query(Family.id).filter(Family.id == family_id).with_for_update().first()

    now = utcnow()
    grant_ends = [
        _aware(g.ends_at)
        for g in db.query(PremiumGrant)
        .filter(PremiumGrant.family_id == family_id, PremiumGrant.voided_at.is_(None))
        .all()
    ]
    starts_at = max([now, *grant_ends])
    ends_at = starts_at + timedelta(days=settings.premium_grant_days)

    # The gift message never went to Stripe — join the local staging row.
    intent = (
        db.query(PremiumGiftIntent)
        .filter(PremiumGiftIntent.stripe_checkout_session_id == session_id)
        .first()
    )

    # Was a subscription active before the gift landed? (Drives the
    # ride-the-gift note in the parents' email.)
    has_active_subscription = (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id == family_id,
            FamilySubscription.status != SubscriptionStatus.canceled,
        )
        .first()
        is not None
    )

    grant = PremiumGrant(
        family_id=family_id,
        source="gift",
        granted_by_user_id=gifter_user_id,
        stripe_checkout_session_id=session_id,
        stripe_payment_intent_id=payment_intent_id,
        amount_cents=amount_cents,
        currency=currency.upper()[:3],
        message=intent.message if intent else None,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    db.add(grant)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent replay of the same session id — return the winner's grant.
        db.rollback()
        return (
            db.query(PremiumGrant)
            .filter(PremiumGrant.stripe_checkout_session_id == session_id)
            .first()
        )

    gifter = db.get(User, gifter_user_id)
    family = db.get(Family, family_id)
    combined_end = premium_until(db, family_id) or ends_at
    gifter_name = gifter.display_name if gifter else "Someone"

    emit(
        db,
        family_id=family_id,
        actor_user_id=gifter_user_id,
        type=FeedEventType.premium_gifted,
        payload={
            "gifter_name": gifter_name,
            "message": grant.message,
            "months": 12,
            "premium_until": combined_end.isoformat(),
        },
    )

    if gifter is not None:
        _send(
            gifter,
            copy.gift_confirmation(
                gifter_name=gifter.display_name,
                family_name=family.name if family else "",
                amount_cents=amount_cents,
                payment_date=now,
                starts_at=starts_at,
                ends_at=ends_at,
                family_id=family_id,
            ),
        )
    for parent in _active_parents(db, family_id):
        _send(
            parent,
            copy.gift_received(
                parent_name=parent.display_name,
                gifter_name=gifter_name,
                ends_at=ends_at,
                message=grant.message,
                has_active_subscription=has_active_subscription,
                combined_end=combined_end,
                family_id=family_id,
            ),
        )
    return grant


# --- invoice-driven lifecycle ---

def handle_invoice_payment_failed(
    db: Session,
    *,
    subscription_id: str,
    invoice_id: str,
    amount_cents: int | None = None,
) -> None:
    """Mirror past_due from live state, then the owner-only 'we'll retry
    automatically' email — once per invoice, not per retry."""
    state = get_payment_provider().subscription_state(subscription_id)
    row = None
    if state is not None:
        row = apply_subscription_state(db, state)
    if row is None:
        row = (
            db.query(FamilySubscription)
            .filter(FamilySubscription.stripe_subscription_id == subscription_id)
            .first()
        )
    if row is None:
        return
    if not _log_once(db, row.family_id, "payment_failed", invoice_id):
        return
    owner = db.get(User, row.owner_user_id)
    if owner is None:
        return
    _send(
        owner,
        copy.payment_failed(
            owner_name=owner.display_name,
            amount_cents=amount_cents or PLAN_PRICE_CENTS[row.plan],
            family_id=row.family_id,
        ),
    )


def handle_invoice_upcoming(
    db: Session, *, subscription_id: str, period_end: datetime
) -> None:
    """Annual plans only: renewal reminder to the owner. The lead time is
    Stripe Billing's `invoice.upcoming` window (configured in the dashboard —
    30 days for CA ARL; see docs/deploy.md), never hardcoded here. Upcoming
    invoices have no id, so the dedupe key is sub+period_end."""
    row = (
        db.query(FamilySubscription)
        .filter(FamilySubscription.stripe_subscription_id == subscription_id)
        .first()
    )
    if row is None or row.plan != SubscriptionPlan.annual:
        return
    key = f"{subscription_id}:{_aware(period_end).isoformat()}"
    if not _log_once(db, row.family_id, "renewal_upcoming", key):
        return
    owner = db.get(User, row.owner_user_id)
    if owner is None:
        return
    _send(
        owner,
        copy.renewal_upcoming(
            owner_name=owner.display_name,
            renewal_date=_aware(period_end),
            family_id=row.family_id,
        ),
    )


# --- membership lifecycle hooks ---

def handle_owner_departure(db: Session, family_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Call from member-removal / leave / account-deletion paths when the
    departing user owns the family's live subscription: a person shouldn't
    silently keep paying for a family they're no longer in. Stripe call is
    best-effort; on failure the row stays visibly wrong for the admin
    reconcile."""
    row = (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id == family_id,
            FamilySubscription.status != SubscriptionStatus.canceled,
        )
        .first()
    )
    if row is None or row.owner_user_id != user_id:
        return
    owner = db.get(User, user_id)
    try:
        state = get_payment_provider().set_cancel_at_period_end(
            row.stripe_subscription_id, True
        )
    except Exception:  # noqa: BLE001 — best-effort, reconcile fixes drift
        logger.warning(
            "owner-departure cancel_at_period_end failed for %s — reconcile",
            row.stripe_subscription_id,
        )
        state = None
    if state is not None:
        apply_subscription_state(db, state)
    else:
        row.cancel_at_period_end = True
        row.updated_at = utcnow()
    for parent in _active_parents(db, family_id):
        if parent.id == user_id:
            continue
        _send(
            parent,
            copy.owner_departure(
                parent_name=parent.display_name,
                owner_name=owner.display_name if owner else "A parent",
                end_date=_aware(row.current_period_end),
                family_id=family_id,
            ),
        )


# --- request-driven lazy lifecycle (the deliberate no-cron substitute) ---

def run_lazy_lifecycle(db: Session, family_id: uuid.UUID) -> None:
    """Runs inside GET /families/{id}/premium and family_detail. Covers the
    one lifecycle moment Stripe gives us no webhook for: gift-only coverage
    ending (soon, or already lapsed). premium_email_log's unique insert is the
    race-safe send-once guard. Commits only when something was sent."""
    live_sub = (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id == family_id,
            FamilySubscription.status != SubscriptionStatus.canceled,
        )
        .first()
    )
    if live_sub is not None:
        return  # an auto-renewing subscription continues coverage
    grants = (
        db.query(PremiumGrant)
        .filter(PremiumGrant.family_id == family_id, PremiumGrant.voided_at.is_(None))
        .all()
    )
    if not grants:
        return
    latest = max(grants, key=lambda g: _aware(g.ends_at))
    coverage_end = _aware(latest.ends_at)
    now = utcnow()
    sent = False

    if now < coverage_end <= now + GIFT_ENDING_SOON_WINDOW:
        if _log_once(db, family_id, "gift_ending_soon", str(latest.id)):
            gifter = db.get(User, latest.granted_by_user_id)
            for parent in _active_parents(db, family_id):
                _send(
                    parent,
                    copy.gift_ending_soon(
                        parent_name=parent.display_name,
                        gifter_name=gifter.display_name if gifter else "a loved one",
                        end_date=coverage_end,
                        family_id=family_id,
                    ),
                )
            sent = True
    elif coverage_end <= now:
        key = f"{family_id}:{coverage_end.isoformat()}"
        if _log_once(db, family_id, "premium_ended", key):
            for parent in _active_parents(db, family_id):
                _send(
                    parent,
                    copy.premium_ended(
                        parent_name=parent.display_name, family_id=family_id
                    ),
                )
            sent = True
    if sent:
        db.commit()


# --- admin reconcile ---

def reconcile_family_premium(db: Session, family_id: uuid.UUID) -> str:
    """Re-fetch live subscription state and re-mirror (precedent:
    reconcile_contribution). Returns the resulting status string."""
    row = (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id == family_id,
            FamilySubscription.status != SubscriptionStatus.canceled,
        )
        .first()
    ) or (
        db.query(FamilySubscription)
        .filter(FamilySubscription.family_id == family_id)
        .order_by(FamilySubscription.created_at.desc())
        .first()
    )
    if row is None:
        return "no_subscription"
    state = get_payment_provider().subscription_state(row.stripe_subscription_id)
    if state is None:
        # Local backend, or the subscription no longer exists at Stripe.
        if get_payment_provider().settles_via_webhook and row.status != SubscriptionStatus.canceled:
            row.status = SubscriptionStatus.canceled
            row.updated_at = utcnow()
            db.flush()
            _maybe_premium_ended(db, row)
        return row.status.value
    apply_subscription_state(db, state, family_id=row.family_id, owner_user_id=row.owner_user_id)
    return row.status.value
