import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from ..deps import CurrentUser, DbSession, get_child_with_access, require_not_supporter
from ..models import (
    Contribution,
    ContributionStatus,
    FundAccount,
    FundAccountStatus,
    FundLedgerEntry,
    LedgerEntryType,
    User,
)
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
    """Any family member can contribute — this is the north-star flow. The
    child's Future Fund (connected account) must be active: money only ever
    moves toward a real, payout-ready account. The destination is resolved
    server-side — never from the client."""
    child, _ = get_child_with_access(db, child_id, user)
    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    account_status = account.account_status if account else FundAccountStatus.none
    if account_status == FundAccountStatus.restricted:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Gifts to {child.first_name} are paused just now. Please try again soon.",
        )
    if account_status != FundAccountStatus.active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{child.first_name}'s Future Fund isn't ready for gifts yet. "
            f"A parent needs to finish setting it up first.",
        )
    # Currency is the FUND's, never the client's: a crafted non-USD currency
    # would otherwise charge in that currency while the USD ledger records the
    # raw cents figure, diverging the balance from the money actually moved.
    if payload.currency != account.currency:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Gifts to {child.first_name} are in {account.currency}.",
        )
    contribution = Contribution(
        child_id=child_id,
        contributor_user_id=user.id,
        amount_cents=payload.amount_cents,
        currency=account.currency,
        fee_cents=contribution_fee_cents(payload.amount_cents),
        message=payload.message,
        media_id=payload.media_id,
        trigger_feed_event_id=payload.trigger_feed_event_id,
    )
    provider_id, client_secret = get_payment_provider().create_payment(
        contribution, destination_account=account.stripe_account_id
    )
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
        raise HTTPException(status.HTTP_409_CONFLICT, "This gift already went through. Thank you!")

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

    settlement = settle_contribution(db, contribution)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent confirm settled first (ledger unique constraint on
        # source_contribution_id). This one is a replay: no email, same 409
        # the serialized replay gets above.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This gift already went through. Thank you!")
    # Celebration notifications go out only after the ledger write is committed
    # — never inside the transaction (double-send race, see settle_contribution).
    settlement.deliver(db)
    return ContributionOut.model_validate(contribution)


@router.get("/children/{child_id}/fund", response_model=FundOut)
def child_fund(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FundOut:
    child, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)
    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    if account is None:
        return FundOut(
            child_id=child_id,
            currency="USD",
            balance_cents=0,
            account_status=FundAccountStatus.none,
            setup_by_name=None,
            gift_count=0,
            entries=[],
        )

    setup_by = db.get(User, account.setup_by) if account.setup_by else None

    rows = (
        db.query(FundLedgerEntry, Contribution, User)
        .outerjoin(Contribution, FundLedgerEntry.source_contribution_id == Contribution.id)
        .outerjoin(User, Contribution.contributor_user_id == User.id)
        .filter(FundLedgerEntry.account_id == account.id)
        .order_by(FundLedgerEntry.created_at.desc(), FundLedgerEntry.id.desc())
        .all()
    )
    # "Gifts from the family": count contribution entries whose contribution is
    # not fully refunded. Refund entries are `adjustment`, so they never add; a
    # full refund flips the contribution to `refunded` (drop it, -1); a partial
    # refund leaves it `succeeded` (still counted).
    gift_count = sum(
        1
        for entry, contribution, _ in rows
        if entry.entry_type == LedgerEntryType.contribution
        and (contribution is None or contribution.status != ContributionStatus.refunded)
    )
    return FundOut(
        child_id=child_id,
        currency=account.currency,
        balance_cents=fund_balance_cents(db, account.id),
        account_status=account.account_status,
        setup_by_name=setup_by.display_name if setup_by else None,
        gift_count=gift_count,
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
