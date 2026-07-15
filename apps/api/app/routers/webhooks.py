import logging

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..config import settings
from ..deps import DbSession
from ..models import Contribution, ContributionStatus, FundAccount
from ..services.payments import (
    get_payment_provider,
    settle_contribution,
    sync_fund_account_state,
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
