import uuid

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..deps import CurrentUser, DbSession, get_child_with_access
from ..models import (
    Contribution,
    ContributionStatus,
    FamilyMember,
    FamilyRole,
    FeedEventType,
    FundAccount,
    FundLedgerEntry,
    MemberStatus,
    User,
)
from ..schemas import ContributionCreate, ContributionOut, FundOut, LedgerEntryOut
from ..services.email import get_email_sender
from ..services.feed import emit
from ..services.payments import (
    contribution_fee_cents,
    fund_balance_cents,
    get_payment_provider,
    record_payment_succeeded,
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
    contribution.provider_payment_id = get_payment_provider().create_payment(contribution)
    db.add(contribution)
    db.commit()
    return ContributionOut.model_validate(contribution)


@router.post("/contributions/{contribution_id}/confirm", response_model=ContributionOut)
def confirm_contribution(
    contribution_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ContributionOut:
    """Local-dev settlement: the provider verifies, then the shared
    record_payment_succeeded writes the ledger. With Stripe, a signed webhook
    replaces this endpoint and calls the same function."""
    contribution = db.get(Contribution, contribution_id)
    if contribution is None or contribution.contributor_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    if contribution.status == ContributionStatus.succeeded:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already completed")
    if not get_payment_provider().confirm_payment(contribution):
        contribution.status = ContributionStatus.failed
        db.commit()
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "The payment didn't go through")

    child, _ = get_child_with_access(db, contribution.child_id, user)
    record_payment_succeeded(db, contribution)
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=user.id,
        type=FeedEventType.contribution,
        child_id=child.id,
        payload={
            "contribution_id": str(contribution.id),
            "child_name": child.first_name,
            "contributor_name": user.display_name,
            "amount_cents": contribution.amount_cents,
            "currency": contribution.currency,
            "message": contribution.message,
        },
    )
    db.commit()

    # Tell the parents someone just added to their child's future
    parents = (
        db.query(User)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .filter(
            FamilyMember.family_id == child.family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role.in_([FamilyRole.parent, FamilyRole.guardian]),
            User.id != user.id,
        )
        .all()
    )
    sender = get_email_sender()
    amount = f"${contribution.amount_cents / 100:,.2f}"
    for parent in parents:
        sender.send(
            to=parent.email,
            subject=f"{user.display_name} just added to {child.first_name}'s future",
            body=(
                f"Hi {parent.display_name},\n\n"
                f"{user.display_name} contributed {amount} to {child.first_name}'s "
                f"future fund"
                + (f" with a note:\n\n  “{contribution.message}”\n" if contribution.message else ".\n")
                + f"\nSee it here: {settings.web_base_url}/family/{child.family_id}\n\n"
                f"With warmth,\nFutureRoots"
            ),
        )
    return ContributionOut.model_validate(contribution)


@router.get("/children/{child_id}/fund", response_model=FundOut)
def child_fund(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FundOut:
    child, _ = get_child_with_access(db, child_id, user)
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
