import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession, get_child_with_access, require_not_supporter
from ..models import Contribution, ContributionStatus, FundAccount, FundLedgerEntry, User
from ..schemas import ContributionCreate, ContributionOut, FundOut, LedgerEntryOut
from ..services.payments import (
    contribution_fee_cents,
    fund_balance_cents,
    get_payment_provider,
    settle_contribution,
)

router = APIRouter(tags=["contributions"])


@router.post(
    "/children/{child_id}/contributions",
    response_model=ContributionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_contribution(
    child_id: uuid.UUID, payload: ContributionCreate, db: DbSession, user: CurrentUser
) -> ContributionOut:
    """Any family member can contribute — this is the north-star flow."""
    get_child_with_access(db, child_id, user)
    contribution = Contribution(
        child_id=child_id,
        contributor_user_id=user.id,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        fee_cents=contribution_fee_cents(payload.amount_cents),
        message=payload.message,
        media_id=payload.media_id,
        trigger_feed_event_id=payload.trigger_feed_event_id,
    )
    provider_id, client_secret = get_payment_provider().create_payment(contribution)
    contribution.provider_payment_id = provider_id
    db.add(contribution)
    db.commit()
    out = ContributionOut.model_validate(contribution)
    out.client_secret = client_secret  # Stripe Elements needs this; never stored
    return out


@router.post("/contributions/{contribution_id}/confirm", response_model=ContributionOut)
def confirm_contribution(
    contribution_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ContributionOut:
    """Local-backend settlement. With Stripe, the signed webhook settles
    instead and this endpoint refuses."""
    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.contributor_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    if contribution.status == ContributionStatus.succeeded:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already completed")

    provider = get_payment_provider()
    if provider.settles_via_webhook:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This payment completes automatically once your card is confirmed",
        )
    get_child_with_access(db, contribution.child_id, user)
    if not provider.confirm_payment(contribution):
        contribution.status = ContributionStatus.failed
        db.commit()
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "The payment didn't go through")

    settle_contribution(db, contribution)
    db.commit()
    return ContributionOut.model_validate(contribution)


@router.get("/children/{child_id}/fund", response_model=FundOut)
def child_fund(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FundOut:
    child, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)
    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    if account is None:
        return FundOut(child_id=child_id, currency="USD", balance_cents=0, entries=[])

    rows = (
        db.query(FundLedgerEntry, Contribution, User)
        .outerjoin(Contribution, FundLedgerEntry.source_contribution_id == Contribution.id)
        .outerjoin(User, Contribution.contributor_user_id == User.id)
        .filter(FundLedgerEntry.account_id == account.id)
        .order_by(FundLedgerEntry.created_at.desc(), FundLedgerEntry.id.desc())
        .all()
    )
    return FundOut(
        child_id=child_id,
        currency=account.currency,
        balance_cents=fund_balance_cents(db, account.id),
        entries=[
            LedgerEntryOut(
                id=entry.id,
                amount_cents=entry.amount_cents,
                entry_type=entry.entry_type.value,
                contributor_name=contributor.display_name if contributor else None,
                message=contribution.message if contribution else None,
                created_at=entry.created_at,
            )
            for entry, contribution, contributor in rows
        ],
    )
