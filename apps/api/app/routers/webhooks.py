from fastapi import APIRouter, Header, HTTPException, Request, status

from ..config import settings
from ..deps import DbSession
from ..models import Contribution, ContributionStatus
from ..services.payments import settle_contribution

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: DbSession,
    stripe_signature: str = Header(default=""),
) -> dict:
    """The ONLY settlement path in Stripe mode. Trust comes from the
    signature — never from the client."""
    import stripe

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except (stripe.error.SignatureVerificationError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")

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
                settle_contribution(db, contribution)
                db.commit()
        else:
            # failed or canceled: a payment that never settled becomes failed
            if contribution.status == ContributionStatus.pending:
                contribution.status = ContributionStatus.failed
                db.commit()

    return {"received": True}
