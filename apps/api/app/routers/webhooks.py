import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..config import settings
from ..deps import DbSession
from ..models import Contribution, ContributionStatus, FamilySubscription, FundAccount
from ..services.payments import (
    SubscriptionState,
    get_payment_provider,
    settle_contribution,
    sync_fund_account_state,
)
from ..services.premium import (
    apply_gift_paid,
    apply_subscription_state,
    handle_invoice_payment_failed,
    handle_invoice_upcoming,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


def _verified_event(payload: bytes, signature: str, secret: str):
    import stripe

    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except (stripe.error.SignatureVerificationError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")


def _field(obj, key: str, default=None):
    """Subscript-safe field access: Stripe event objects support __getitem__
    but not dict.get()."""
    try:
        value = obj[key]
    except (KeyError, TypeError):
        return default
    return default if value is None else value


def _destination_verified(db, contribution: Contribution, intent: dict) -> bool:
    """A succeeded PI settles the ledger only when the money verifiably went
    where WE route it today: transfer_data.destination matches the child's
    current connected account AND the application fee matches what we priced.
    Carve-out: a PI with no transfer_data at all is a legacy (pre-Connect)
    charge and settles only if the child's fund has no connected account."""
    account = (
        db.query(FundAccount).filter(FundAccount.child_id == contribution.child_id).first()
    )
    expected_destination = account.stripe_account_id if account else None
    transfer_data = _field(intent, "transfer_data", {})
    destination = _field(transfer_data, "destination")

    if destination is None:
        return expected_destination is None
    return (
        destination == expected_destination
        and _field(intent, "application_fee_amount") == contribution.fee_cents
    )


def _uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _livemode_ok(event) -> bool:
    """Guard against a test-mode gift event settling on a live system (or vice
    versa). We don't carry a dedicated stripe_livemode flag, so we derive the
    mode we expect from signals that are already wired: on the local backend
    the webhook is never the money path (tests, dev) so we don't enforce; on
    the real Stripe backend the secret key prefix (sk_live_ vs sk_test_) tells
    us which mode this deployment runs, and Stripe stamps every event with
    livemode. A mismatch means the event doesn't belong to this deployment."""
    if settings.payment_backend != "stripe":
        return True
    expected_live = settings.stripe_secret_key.startswith("sk_live")
    return bool(_field(event, "livemode", False)) == expected_live


def _as_dict(obj) -> dict:
    """StripeObject (v15+) is not a Mapping — dict(obj) breaks. It exposes
    to_dict(); plain dicts (tests, local payloads) pass through."""
    if obj is None:
        return {}
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if isinstance(obj, dict):
        return dict(obj)
    return {}


def _epoch_to_dt(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError):
        return None


def _invoice_subscription_id(invoice) -> str | None:
    """The invoice's subscription id — top-level in classic API versions,
    under parent.subscription_details in newer ones."""
    sub = _field(invoice, "subscription")
    if sub:
        return str(sub)
    parent = _field(invoice, "parent", {})
    details = _field(parent, "subscription_details", {})
    sub = _field(details, "subscription")
    return str(sub) if sub else None


def _mirror_live_subscription(db, subscription_id: str, payload_sub=None) -> None:
    """Converge the family_subscriptions mirror to LIVE Stripe state. The
    triggering event is only a trigger, so replays and reordering are
    harmless. Unknown subscriptions that carry no premium metadata are ignored
    (another product on the same Stripe account)."""
    known = (
        db.query(FamilySubscription)
        .filter(FamilySubscription.stripe_subscription_id == subscription_id)
        .first()
    )
    state = get_payment_provider().subscription_state(subscription_id)
    if state is None:
        # Retrieve 404s once a subscription is deleted: map the signed payload
        # to a canceled state (its metadata still self-identifies the family).
        if payload_sub is None and known is None:
            return
        metadata = _as_dict(_field(payload_sub, "metadata", {})) if payload_sub else {}
        period_end = (
            _epoch_to_dt(_field(payload_sub, "current_period_end")) if payload_sub else None
        )
        state = SubscriptionState(
            subscription_id=subscription_id,
            customer_id=str(_field(payload_sub, "customer", "") or "") if payload_sub else "",
            status="canceled",
            price_id="",
            current_period_end=period_end
            or (known.current_period_end if known else datetime.now(timezone.utc)),
            cancel_at_period_end=True,
            metadata=metadata,
        )
    if known is None and (state.metadata or {}).get("kind") != "premium_subscription":
        return  # not ours
    apply_subscription_state(db, state)


@router.post("/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: DbSession,
    stripe_signature: str = Header(default=""),
) -> dict:
    """The ONLY settlement path in Stripe mode. Trust comes from the
    signature — never from the client."""
    payload = await request.body()
    event = _verified_event(payload, stripe_signature, settings.stripe_webhook_secret)

    handled = {
        "payment_intent.succeeded",
        "payment_intent.payment_failed",
        "payment_intent.canceled",
    }
    if event["type"] in handled:
        intent = event["data"]["object"]
        contribution = (
            db.query(Contribution)
            .filter(Contribution.provider_payment_id == intent["id"])
            .first()
        )
        if contribution is None:
            # Not ours (e.g. another product on the same Stripe account) — ack
            return {"received": True}

        if event["type"] == "payment_intent.succeeded":
            if contribution.status != ContributionStatus.succeeded:  # idempotent
                if not _destination_verified(db, contribution, intent):
                    # Money went somewhere we don't route today (stale account,
                    # tampered fee, replayed old intent). Never ledger it; ack
                    # so Stripe stops retrying and leave the record pending for
                    # an operator to reconcile.
                    logger.warning(
                        "stripe webhook: destination/fee mismatch for contribution %s "
                        "(intent %s) — left pending, not settled",
                        contribution.id,
                        intent["id"],
                    )
                    return {"received": True}
                settle_contribution(db, contribution)
                db.commit()
        else:
            # failed or canceled: a payment that never settled becomes failed
            if contribution.status == ContributionStatus.pending:
                contribution.status = ContributionStatus.failed
                db.commit()

    # --- FutureRoots Premium (family subscription + one-time gift) ---
    # Every handler is idempotent and commits+acks even for "not ours" events
    # (never make Stripe retry what we've chosen to skip).

    elif event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = _as_dict(_field(session, "metadata", {}))
        kind = meta.get("kind")
        if kind == "premium_subscription":
            sub_id = _field(session, "subscription")
            if sub_id:
                # Never mirror from the session payload: re-fetch live state.
                state = get_payment_provider().subscription_state(str(sub_id))
                if state is not None:
                    apply_subscription_state(
                        db,
                        state,
                        family_id=_uuid_or_none(meta.get("family_id")),
                        owner_user_id=_uuid_or_none(meta.get("owner_user_id")),
                    )
                    db.commit()
        elif kind == "premium_gift":
            # A completed one-time payment is an immutable fact — the SIGNED
            # payload is trusted for it. Verify paid + the gift amount
            # (line items aren't in webhook payloads; amount_total is).
            family_id = _uuid_or_none(meta.get("family_id"))
            gifter_id = _uuid_or_none(meta.get("gifter_user_id"))
            amount_total = _field(session, "amount_total")
            currency = str(_field(session, "currency", "") or "").lower()
            if (
                _field(session, "payment_status") == "paid"
                and family_id is not None
                and gifter_id is not None
                and amount_total == settings.premium_gift_amount_cents
                and currency == "usd"
                and _livemode_ok(event)
            ):
                payment_intent = _field(session, "payment_intent")
                apply_gift_paid(
                    db,
                    session_id=str(session["id"]),
                    payment_intent_id=str(payment_intent) if payment_intent else None,
                    amount_cents=int(amount_total),
                    currency=str(_field(session, "currency", "usd")),
                    family_id=family_id,
                    gifter_user_id=gifter_id,
                )
                db.commit()
            elif _field(session, "payment_status") == "paid":
                logger.warning(
                    "stripe webhook: premium gift session %s failed verification "
                    "(amount_total=%s currency=%s livemode_ok=%s) — not settled",
                    _field(session, "id"),
                    amount_total,
                    currency,
                    _livemode_ok(event),
                )
        # other/missing kind: contributions use PaymentIntents, not Checkout — ack

    elif event["type"] in ("customer.subscription.updated", "customer.subscription.deleted"):
        sub = event["data"]["object"]
        _mirror_live_subscription(db, str(sub["id"]), payload_sub=sub)
        db.commit()

    elif event["type"] == "invoice.paid":
        sub_id = _invoice_subscription_id(event["data"]["object"])
        if sub_id:
            # Trigger-only: re-fetch and re-mirror (covers renewals; the new
            # period end usually also arrives via subscription.updated).
            _mirror_live_subscription(db, sub_id)
            db.commit()

    elif event["type"] == "invoice.payment_failed":
        invoice = event["data"]["object"]
        sub_id = _invoice_subscription_id(invoice)
        invoice_id = _field(invoice, "id")
        if sub_id and invoice_id:
            amount_due = _field(invoice, "amount_due")
            handle_invoice_payment_failed(
                db,
                subscription_id=sub_id,
                invoice_id=str(invoice_id),
                amount_cents=int(amount_due) if amount_due else None,
            )
            db.commit()

    elif event["type"] == "invoice.upcoming":
        invoice = event["data"]["object"]
        sub_id = _invoice_subscription_id(invoice)
        period_end = _epoch_to_dt(_field(invoice, "period_end"))
        if sub_id and period_end is not None:
            handle_invoice_upcoming(db, subscription_id=sub_id, period_end=period_end)
            db.commit()

    return {"received": True}


@router.post("/webhooks/stripe-connect", status_code=status.HTTP_200_OK)
async def stripe_connect_webhook(
    request: Request,
    db: DbSession,
    stripe_signature: str = Header(default=""),
) -> dict:
    """Connected-account events (account.updated) arrive on their own endpoint
    with its own signing secret. The payload is only a trigger: account state
    is always re-fetched live from Stripe, never trusted from the event body."""
    if not settings.stripe_connect_webhook_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Connect webhook is not configured"
        )
    payload = await request.body()
    event = _verified_event(
        payload, stripe_signature, settings.stripe_connect_webhook_secret
    )

    if event["type"] == "account.updated":
        account_id = _field(event, "account") or _field(event["data"]["object"], "id")
        fund_account = (
            db.query(FundAccount)
            .filter(FundAccount.stripe_account_id == account_id)
            .first()
        )
        if fund_account is None:
            return {"received": True}  # not one of ours — ack
        state = get_payment_provider().connect_account_state(account_id)
        sync_fund_account_state(fund_account, state)
        db.commit()

    return {"received": True}
