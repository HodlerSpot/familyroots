"""FutureRoots Premium — family-level membership (subscribe, gift, manage).

Contract: docs/specs/premium-architecture.md §4 (frozen — the web app builds
against it). Rules enforced here:

- Checkout (subscribe) is strictly parent-only; billing is founder-fixed to
  parents. Guardians manage children, not the family's plan.
- Gifts come from active NON-parents (grandparent, relative, guardian, and
  supporter). Parents who try to gift get 409 use_subscribe.
- The Billing Portal is for the subscription owner only.
- family_subscriptions / premium_grants are written only through the
  settlement service (services/premium.py). On the local backend, checkout
  settles synchronously through those SAME functions, so dev and tests
  exercise the production code path end to end.
"""

import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..deps import (
    ClientPlatform,
    CurrentUser,
    DbSession,
    get_active_membership,
    is_supporter,
    require_parent_role,
)
from ..models import (
    FamilyMember,
    FamilyRole,
    FamilySubscription,
    PremiumGiftIntent,
    PremiumGrant,
    SubscriptionStatus,
    User,
    utcnow,
)
from ..schemas import (
    CheckoutSessionOut,
    GiftCheckoutIn,
    PremiumCheckoutIn,
    PremiumGrantOut,
    PremiumPortalOut,
    PremiumStatusOut,
    PremiumSubscriptionOut,
    PremiumSyncIn,
)
from ..services.entitlements import family_capabilities, family_is_premium, premium_until
from ..services.payments import SubscriptionState, get_payment_provider
from ..services.premium import (
    _active_parents,
    _aware,
    apply_gift_paid,
    apply_subscription_state,
    run_lazy_lifecycle,
)
from ..services import premium_emails as copy
from ..services.email import get_email_sender
from ..return_urls import bridge_url, is_mobile

router = APIRouter(prefix="/families/{family_id}/premium", tags=["premium"])


def _live_subscription(db, family_id: uuid.UUID) -> FamilySubscription | None:
    return (
        db.query(FamilySubscription)
        .filter(
            FamilySubscription.family_id == family_id,
            FamilySubscription.status != SubscriptionStatus.canceled,
        )
        .first()
    )


def _status_out(db, family_id: uuid.UUID, membership: FamilyMember, user) -> PremiumStatusOut:
    is_parent = membership.role == FamilyRole.parent
    sub_row = _live_subscription(db, family_id)

    subscription = None
    if is_parent and sub_row is not None:
        owner = db.get(User, sub_row.owner_user_id)
        subscription = PremiumSubscriptionOut(
            plan=sub_row.plan.value,
            status=sub_row.status.value,
            current_period_end=sub_row.current_period_end,
            cancel_at_period_end=sub_row.cancel_at_period_end,
            owner_name=owner.display_name if owner else "",
            is_owner=sub_row.owner_user_id == user.id,
        )

    grants: list[PremiumGrantOut] = []
    if not is_supporter(membership.role):
        now = utcnow()
        rows = (
            db.query(PremiumGrant, User)
            .outerjoin(User, PremiumGrant.granted_by_user_id == User.id)
            .filter(
                PremiumGrant.family_id == family_id,
                PremiumGrant.voided_at.is_(None),
            )
            .order_by(PremiumGrant.starts_at)
            .all()
        )
        grants = [
            PremiumGrantOut(
                gifter_name=gifter.display_name if gifter else "",
                starts_at=grant.starts_at,
                ends_at=grant.ends_at,
                message=grant.message,
            )
            for grant, gifter in rows
            if _aware(grant.ends_at) > now  # current + future coverage only
        ]

    return PremiumStatusOut(
        plan="premium" if family_is_premium(db, family_id) else "free",
        premium_until=premium_until(db, family_id),
        capabilities=family_capabilities(db, family_id),
        can_manage=is_parent,
        can_gift=not is_parent,
        subscription=subscription,
        grants=grants,
    )


@router.get("", response_model=PremiumStatusOut)
def premium_status(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PremiumStatusOut:
    membership = get_active_membership(db, family_id, user)
    run_lazy_lifecycle(db, family_id)
    return _status_out(db, family_id, membership, user)


@router.post("/checkout", response_model=CheckoutSessionOut)
def create_checkout(
    family_id: uuid.UUID,
    payload: PremiumCheckoutIn,
    db: DbSession,
    user: CurrentUser,
    platform: ClientPlatform,
) -> CheckoutSessionOut:
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)

    # Layer 1 of the double-subscribe guard. Gift coverage does NOT block
    # subscribing (a family may want auto-renew alongside a gift).
    if _live_subscription(db, family_id) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "already_premium",
                "message": "Your family is already on Premium. There's nothing to buy twice.",
            },
        )

    provider = get_payment_provider()
    price_id = (
        settings.stripe_price_monthly
        if payload.plan == "monthly"
        else settings.stripe_price_annual
    )
    if provider.settles_via_webhook and not price_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Premium isn't set up yet"
        )

    customer_id = provider.get_or_create_customer(
        email=user.email,
        display_name=user.display_name,
        user_id=str(user.id),
        existing_customer_id=user.stripe_customer_id,
    )
    user.stripe_customer_id = customer_id

    # Only opaque UUIDs and enum strings — never names, never child anything.
    metadata = {
        "kind": "premium_subscription",
        "family_id": str(family_id),
        "owner_user_id": str(user.id),
        "plan": payload.plan,
    }
    if is_mobile(platform):
        success_url = (
            bridge_url("premium-success", family_id=str(family_id))
            + "&session_id={CHECKOUT_SESSION_ID}"
        )
        cancel_url = bridge_url("premium-cancel", family_id=str(family_id))
    else:
        success_url = (
            f"{settings.web_base_url}/family/{family_id}/premium/success"
            "?session_id={CHECKOUT_SESSION_ID}"
        )
        cancel_url = f"{settings.web_base_url}/family/{family_id}/premium?canceled=1"
    session_id, redirect_url = provider.create_subscription_checkout(
        customer_id=customer_id,
        price_id=price_id or f"price_local_{payload.plan}",
        metadata=metadata,
        success_url=success_url,
        cancel_url=cancel_url,
        # Double-clicks within the hour reuse one Stripe session.
        idempotency_scope=f"{family_id}-{payload.plan}-{utcnow():%Y%m%d%H}",
    )

    if not provider.settles_via_webhook:
        # Local backend: settle synchronously through the SAME settlement
        # functions the webhook calls, so the success page finds Premium live.
        period_days = 365 if payload.plan == "annual" else 30
        apply_subscription_state(
            db,
            SubscriptionState(
                subscription_id=f"sub_local_{uuid.uuid4().hex}",
                customer_id=customer_id,
                status="active",
                price_id=price_id or f"price_local_{payload.plan}",
                current_period_end=utcnow() + timedelta(days=period_days),
                cancel_at_period_end=False,
                metadata=metadata,
            ),
            family_id=family_id,
            owner_user_id=user.id,
        )
    db.commit()
    return CheckoutSessionOut(checkout_url=redirect_url)


@router.post("/gift-checkout", response_model=CheckoutSessionOut)
def create_gift_checkout(
    family_id: uuid.UUID,
    payload: GiftCheckoutIn,
    db: DbSession,
    user: CurrentUser,
    platform: ClientPlatform,
) -> CheckoutSessionOut:
    membership = get_active_membership(db, family_id, user)
    if membership.role == FamilyRole.parent:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "use_subscribe",
                "message": "Parents subscribe directly. Gifting is for the rest of the family.",
            },
        )

    provider = get_payment_provider()
    if provider.settles_via_webhook and not settings.stripe_price_gift_year:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Premium isn't set up yet"
        )

    customer_id = provider.get_or_create_customer(
        email=user.email,
        display_name=user.display_name,
        user_id=str(user.id),
        existing_customer_id=user.stripe_customer_id,
    )
    user.stripe_customer_id = customer_id

    session_id, redirect_url = provider.create_gift_checkout(
        customer_id=customer_id,
        price_id=settings.stripe_price_gift_year or "price_local_gift_year",
        # The gift message is NEVER sent to Stripe — it stays in the local
        # premium_gift_intents staging row (COPPA by construction).
        metadata={
            "kind": "premium_gift",
            "family_id": str(family_id),
            "gifter_user_id": str(user.id),
        },
        success_url=(
            (
                bridge_url("gift-success", family_id=str(family_id))
                + "&session_id={CHECKOUT_SESSION_ID}"
            )
            if is_mobile(platform)
            else (
                f"{settings.web_base_url}/family/{family_id}/premium/gift/success"
                "?session_id={CHECKOUT_SESSION_ID}"
            )
        ),
        cancel_url=(
            bridge_url("gift-cancel", family_id=str(family_id))
            if is_mobile(platform)
            else f"{settings.web_base_url}/family/{family_id}/premium/gift?canceled=1"
        ),
    )
    # Same transaction as session creation: the webhook joins on this row.
    db.add(
        PremiumGiftIntent(
            family_id=family_id,
            gifter_user_id=user.id,
            stripe_checkout_session_id=session_id,
            message=payload.message,
        )
    )
    if not provider.settles_via_webhook:
        db.flush()
        apply_gift_paid(
            db,
            session_id=session_id,
            payment_intent_id=f"pi_local_{uuid.uuid4().hex}",
            amount_cents=settings.premium_gift_amount_cents,
            currency="USD",
            family_id=family_id,
            gifter_user_id=user.id,
        )
    db.commit()
    return CheckoutSessionOut(checkout_url=redirect_url)


@router.post("/cancel", response_model=PremiumStatusOut)
def cancel_premium(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PremiumStatusOut:
    """Any active parent (not only the owner) can cancel. Never ends Premium
    early: sets cancel_at_period_end at Stripe and mirrors the returned state."""
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)
    sub = _live_subscription(db, family_id)
    if sub is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your family doesn't have a Premium plan to cancel"
        )
    if not sub.cancel_at_period_end:  # idempotent: repeat clicks change nothing
        state = get_payment_provider().set_cancel_at_period_end(
            sub.stripe_subscription_id, True
        )
        if state is not None:
            apply_subscription_state(db, state)
        else:  # local backend: flip the mirror row directly
            sub.cancel_at_period_end = True
            sub.updated_at = utcnow()
        # Action-triggered (not webhook-triggered): owner + other parents, same copy.
        sender = get_email_sender()
        for parent in _active_parents(db, family_id):
            sender.send(
                to=parent.email,
                **copy.cancellation_confirmed(
                    parent_name=parent.display_name,
                    end_date=_aware(sub.current_period_end),
                    family_id=family_id,
                ),
            )
    db.commit()
    return _status_out(db, family_id, membership, user)


@router.post("/resume", response_model=PremiumStatusOut)
def resume_premium(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PremiumStatusOut:
    """Undo a pending cancellation before the period ends — no new checkout."""
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)
    sub = _live_subscription(db, family_id)
    if sub is None or not sub.cancel_at_period_end:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "There's no pending cancellation to resume from"
        )
    state = get_payment_provider().set_cancel_at_period_end(
        sub.stripe_subscription_id, False
    )
    if state is not None:
        apply_subscription_state(db, state)
    else:  # local backend
        sub.cancel_at_period_end = False
        sub.updated_at = utcnow()
    db.commit()
    return _status_out(db, family_id, membership, user)


@router.post("/portal", response_model=PremiumPortalOut)
def billing_portal(
    family_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    platform: ClientPlatform,
) -> PremiumPortalOut:
    """Hosted Billing Portal (payment method, invoices) — subscription owner only."""
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)
    sub = _live_subscription(db, family_id)
    if sub is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your family doesn't have a Premium plan yet"
        )
    if sub.owner_user_id != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the parent who started the plan can open billing",
        )
    return_url = (
        bridge_url("portal", family_id=str(family_id))
        if is_mobile(platform)
        else f"{settings.web_base_url}/family/{family_id}"
    )
    url = get_payment_provider().create_billing_portal(
        sub.stripe_customer_id,
        return_url=return_url,
    )
    return PremiumPortalOut(portal_url=url)


@router.post("/sync", response_model=PremiumStatusOut)
def sync_premium(
    family_id: uuid.UUID, payload: PremiumSyncIn, db: DbSession, user: CurrentUser
) -> PremiumStatusOut:
    """Reconcile-on-read: every fact is re-read live from Stripe, so any
    active member (including a supporter gifter) may call it. Used by the
    success page's polling fallback and by support."""
    membership = get_active_membership(db, family_id, user)
    provider = get_payment_provider()

    if payload.session_id:
        result = provider.checkout_result(payload.session_id)
        # None on the local backend (checkout settled synchronously) or when
        # the session doesn't exist — nothing to settle either way.
        if result is not None:
            if result.metadata.get("family_id") != str(family_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Checkout not found")
            if result.kind == "premium_subscription" and result.subscription_id:
                state = provider.subscription_state(result.subscription_id)
                if state is not None:
                    # Pin the mirror to the ALREADY-AUTHORIZED path family (and
                    # the owner from the verified session metadata) — never let
                    # a second metadata blob on the live subscription rebind the
                    # row to a different family than the caller is authorized for.
                    owner_id = None
                    try:
                        owner_id = uuid.UUID(result.metadata.get("owner_user_id", ""))
                    except (ValueError, TypeError):
                        pass
                    apply_subscription_state(
                        db, state, family_id=family_id, owner_user_id=owner_id
                    )
            elif result.kind == "premium_gift" and result.paid:
                price_ok = (
                    not settings.stripe_price_gift_year
                    or result.price_id is None
                    or result.price_id == settings.stripe_price_gift_year
                )
                gifter_id = None
                try:
                    gifter_id = uuid.UUID(result.metadata.get("gifter_user_id", ""))
                except ValueError:
                    pass
                if price_ok and gifter_id is not None:
                    apply_gift_paid(
                        db,
                        session_id=result.session_id,
                        payment_intent_id=result.payment_intent_id,
                        amount_cents=result.amount_total
                        or settings.premium_gift_amount_cents,
                        currency=result.currency or "USD",
                        family_id=family_id,
                        gifter_user_id=gifter_id,
                    )
    else:
        sub = _live_subscription(db, family_id)
        if sub is not None:
            state = provider.subscription_state(sub.stripe_subscription_id)
            if state is not None:
                apply_subscription_state(db, state)
    db.commit()
    return _status_out(db, family_id, membership, user)
