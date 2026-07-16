"""FutureRoots Premium entitlements — the read side.

Premium is a family-level membership. State is ALWAYS derived at read time
from family_subscriptions (Stripe mirror) + premium_grants (prepaid gifts);
there is no stored is_premium flag anywhere, by design.

Derivation:

    family is Premium ⇔
         EXISTS family_subscriptions s WHERE s.family_id = :f
             AND ( s.status = 'past_due'      -- Stripe's retry window IS the grace period
                 OR (s.status = 'active' AND now() < s.current_period_end + 72h) )
      OR EXISTS premium_grants g WHERE g.family_id = :f
             AND g.voided_at IS NULL AND g.starts_at <= now() AND now() < g.ends_at

The 72-hour slack on `active` exists only so a late/lost renewal webhook can't
glitch a paying family to Free at the renewal instant. Displayed dates
(premium_until) never include the slack.

Write-side (settlement) lives in services/premium.py.
"""

import enum
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import FamilySubscription, PremiumGrant, SubscriptionStatus, utcnow

ACTIVE_SLACK = timedelta(hours=72)


class Capability(str, enum.Enum):
    video_upload = "video_upload"
    family_video_call = "family_video_call"
    # Future premium features are one line here.


# Every capability in the registry requires Premium today; a future free-tier
# capability would simply not appear here.
PREMIUM_CAPABILITIES: frozenset[Capability] = frozenset(Capability)


def _aware(dt: datetime) -> datetime:
    """SQLite drops tz info in tests; normalize to aware UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _live_subscriptions(
    db: Session, family_ids: list[uuid.UUID]
) -> list[FamilySubscription]:
    if not family_ids:
        return []
    return (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id.in_(family_ids),
            FamilySubscription.status != SubscriptionStatus.canceled,
        )
        .all()
    )


def _unvoided_grants(db: Session, family_ids: list[uuid.UUID]) -> list[PremiumGrant]:
    if not family_ids:
        return []
    return (
        db.query(PremiumGrant)
        .filter(
            PremiumGrant.family_id.in_(family_ids),
            PremiumGrant.voided_at.is_(None),
        )
        .all()
    )


def _subscription_entitles(sub: FamilySubscription, now: datetime) -> bool:
    if sub.status == SubscriptionStatus.past_due:
        # past_due holds entitlement unconditionally: Stripe's Smart Retries
        # window is the grace period and Stripe always terminates the state.
        return True
    return (
        sub.status == SubscriptionStatus.active
        and now < _aware(sub.current_period_end) + ACTIVE_SLACK
    )


def _grant_entitles(grant: PremiumGrant, now: datetime) -> bool:
    return _aware(grant.starts_at) <= now < _aware(grant.ends_at)


def plans_for_families(
    db: Session, family_ids: list[uuid.UUID]
) -> dict[uuid.UUID, bool]:
    """Batch: one grouped query over each table, for GET /families (no N+1)."""
    now = utcnow()
    result: dict[uuid.UUID, bool] = {fid: False for fid in family_ids}
    for sub in _live_subscriptions(db, family_ids):
        if _subscription_entitles(sub, now):
            result[sub.family_id] = True
    for grant in _unvoided_grants(db, family_ids):
        if _grant_entitles(grant, now):
            result[grant.family_id] = True
    return result


def family_is_premium(db: Session, family_id: uuid.UUID) -> bool:
    return plans_for_families(db, [family_id])[family_id]


def premium_until(db: Session, family_id: uuid.UUID) -> datetime | None:
    """The real end of current coverage, for display — no slack. Max over
    non-canceled subscriptions' current_period_end and unvoided, unexpired
    grants' ends_at (a stacked future grant extends the combined end date)."""
    now = utcnow()
    candidates: list[datetime] = [
        _aware(s.current_period_end) for s in _live_subscriptions(db, [family_id])
    ]
    candidates.extend(
        _aware(g.ends_at)
        for g in _unvoided_grants(db, [family_id])
        if _aware(g.ends_at) > now
    )
    return max(candidates) if candidates else None


def family_capabilities(db: Session, family_id: uuid.UUID) -> list[str]:
    """[] for free families, sorted capability values for premium ones."""
    if not family_is_premium(db, family_id):
        return []
    return sorted(c.value for c in PREMIUM_CAPABILITIES)


def require_capability(
    db: Session, family_id: uuid.UUID, capability: Capability
) -> None:
    """Raises HTTPException(402) with structured detail when the family lacks
    the capability. THE enforcement point — call sites never write `if premium`."""
    if capability in PREMIUM_CAPABILITIES and not family_is_premium(db, family_id):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "premium_required",
                "capability": capability.value,
                # Warm, brand-safe fallback copy; the web app normally renders
                # its own upsell from the code and never shows this raw.
                "message": "This is part of FutureRoots Premium.",
            },
        )
