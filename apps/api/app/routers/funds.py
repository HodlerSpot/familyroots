"""Future Fund account lifecycle (Stripe Connect Express).

The child's Future Fund becomes a real money account: a parent/guardian sets
up an Express connected account (legally the parent's, earmarked for the
child) through Stripe's hosted onboarding. Contributions then land in that
account as destination charges.

Discipline:
- the Stripe account id never reaches a client (admin console excepted);
- status columns on FundAccount are a cache of Stripe's live state, refreshed
  only from accounts.retrieve (setup/status polling and the signed
  account.updated webhook) — never from client say-so;
- no money endpoints here: the ledger is written only by verified payment
  events (services/payments.py).
"""

import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..deps import CurrentUser, DbSession, get_child_with_access, require_guardian_role
from ..models import (
    ConsentRecord,
    ConsentType,
    FamilyMember,
    FamilyRole,
    FundAccount,
    FundAccountStatus,
    FundNudge,
    MemberStatus,
    User,
    utcnow,
)
from ..services.email import get_email_sender
from ..services.email_templates import render_email
from ..services.notify import notify_fund_activated
from ..services.payments import (
    get_or_create_fund_account,
    get_payment_provider,
    sync_fund_account_state,
)

router = APIRouter(tags=["funds"])


class FundSetupOut(BaseModel):
    url: str


class FundSetupStatusOut(BaseModel):
    account_status: FundAccountStatus
    payouts_enabled: bool
    requirements_due: bool


class FundStatusOut(BaseModel):
    account_status: FundAccountStatus


class FundNudgeOut(BaseModel):
    sent: bool


def _nudge_claim(db, child_id: uuid.UUID, user_id: uuid.UUID) -> FundNudge | None:
    """The member's single throttle row for this child, row-locked so
    concurrent re-nudges serialize (with_for_update is a no-op on SQLite)."""
    return (
        db.query(FundNudge)
        .filter(FundNudge.child_id == child_id, FundNudge.user_id == user_id)
        .with_for_update()
        .first()
    )


@router.post("/children/{child_id}/fund/setup", response_model=FundSetupOut)
def setup_fund(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FundSetupOut:
    """Start (or resume) hosted onboarding for the child's Future Fund.
    Parent/guardian only. Always returns a FRESH single-use onboarding link —
    links expire quickly and are never stored."""
    child, membership = get_child_with_access(db, child_id, user)
    require_guardian_role(membership)

    # Create-if-missing, then row-lock so two concurrent setup clicks can't
    # create two Stripe accounts (SQLite tests: with_for_update is a no-op).
    get_or_create_fund_account(db, child_id, "USD")
    account = (
        db.query(FundAccount)
        .filter(FundAccount.child_id == child_id)
        .with_for_update()
        .one()
    )
    if account.account_status == FundAccountStatus.active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{child.first_name}'s Future Fund is already set up and ready for gifts.",
        )

    provider = get_payment_provider()
    if account.stripe_account_id is None:
        # Data minimization: nothing child-linked goes to Stripe. Our own
        # fund_accounts row (via fund_account_id) carries full traceability.
        account.stripe_account_id = provider.create_connect_account(
            email=user.email,
            metadata={
                "fund_account_id": str(account.id),
                "setup_by": str(user.id),
            },
            idempotency_scope=str(account.id),
        )
        account.setup_by = user.id
        account.account_status = FundAccountStatus.onboarding
        account.onboarding_started_at = utcnow()
        # Consent is recorded data, not an assumption (COPPA): opening a real
        # money account for the child enables the contributions feature.
        db.add(
            ConsentRecord(
                child_id=child.id,
                granted_by=user.id,
                consent_type=ConsentType.contributions,
            )
        )

    base = f"{settings.web_base_url}/family/{child.family_id}/child/{child.id}/fund/setup"
    url = provider.create_account_link(
        account.stripe_account_id,
        return_url=f"{base}/return",
        refresh_url=f"{base}/refresh",
    )
    db.commit()
    return FundSetupOut(url=url)


@router.get("/children/{child_id}/fund/setup/status", response_model=FundSetupStatusOut)
def fund_setup_status(
    child_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> FundSetupStatusOut:
    """Live setup progress, for the guardian finishing onboarding. Pulls the
    account's state straight from the provider and refreshes our cache."""
    _, membership = get_child_with_access(db, child_id, user)
    require_guardian_role(membership)

    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    if account is None or account.stripe_account_id is None:
        return FundSetupStatusOut(
            account_status=FundAccountStatus.none,
            payouts_enabled=False,
            requirements_due=False,
        )
    state = get_payment_provider().connect_account_state(account.stripe_account_id)
    became_active = sync_fund_account_state(account, state)
    # First time the fund goes live: celebrate on the feed + tell the parents.
    batch = notify_fund_activated(db, account) if became_active else None
    db.commit()
    if batch is not None:
        batch.deliver(db)
    return FundSetupStatusOut(
        account_status=account.account_status,
        payouts_enabled=account.payouts_enabled,
        requirements_due=account.requirements_due,
    )


@router.get("/children/{child_id}/fund/status", response_model=FundStatusOut)
def fund_status(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> FundStatusOut:
    """Whether the Future Fund can receive gifts — for ANY active family
    member, supporters included (they can give, so they may see readiness).
    Deliberately status-only: no balance, no money data, no account id."""
    get_child_with_access(db, child_id, user)

    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    return FundStatusOut(
        account_status=account.account_status if account else FundAccountStatus.none
    )


@router.post("/children/{child_id}/fund/nudge", response_model=FundNudgeOut)
def nudge_fund_setup(
    child_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> FundNudgeOut:
    """A non-guardian member asks the parents to finish Future Fund setup.
    Emails go to parents/guardians only (never supporters). Throttled to one
    nudge per member per child per 7 days — a throttled nudge quietly returns
    sent=false rather than erroring."""
    child, membership = get_child_with_access(db, child_id, user)
    if membership.role in (FamilyRole.parent, FamilyRole.guardian):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "You can set up the Future Fund yourself. No need to ask.",
        )

    # Claim the throttle BEFORE anything is sent. fund_nudges keeps ONE row
    # per (member, child); the unique constraint makes a concurrent double-tap
    # race-safe — exactly one request owns the claim, the loser quietly
    # returns sent=false. (Rows older than 30 days are swept by the daily
    # maintenance command.)
    now = utcnow()
    week_ago = now - timedelta(days=7)
    existing = _nudge_claim(db, child_id, user.id)
    if existing is not None:
        created = existing.created_at
        if created.tzinfo is None:  # SQLite drops tz in tests
            created = created.replace(tzinfo=timezone.utc)
        if created >= week_ago:
            return FundNudgeOut(sent=False)
        existing.created_at = now  # re-nudge after the window: refresh in place
        db.flush()
    else:
        db.add(FundNudge(child_id=child_id, user_id=user.id, created_at=now))
        try:
            db.flush()
        except IntegrityError:
            # First-nudge race: a concurrent request inserted the claim first.
            db.rollback()
            return FundNudgeOut(sent=False)

    guardians = (
        db.query(User)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .filter(
            FamilyMember.family_id == child.family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role.in_([FamilyRole.parent, FamilyRole.guardian]),
        )
        .all()
    )
    # The claim is durable before any email leaves (send-after-commit, same
    # discipline as contribution settlement).
    db.commit()
    sender = get_email_sender()
    child_url = f"{settings.web_base_url}/family/{child.family_id}/child/{child.id}"
    for guardian in guardians:
        sender.send(
            to=guardian.email,
            subject=f"{user.display_name} is ready to give to {child.first_name}'s Future Fund",
            body=(
                f"Hi {guardian.display_name},\n\n"
                f"{user.display_name} is ready to give to {child.first_name}'s Future Fund, "
                f"but it isn't set up yet. It only takes a few minutes to finish. "
                f"Then the whole family can start giving.\n\n"
                f"Finish setting it up here: {child_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=(
                    f"{user.display_name} is ready to give to "
                    f"{child.first_name}'s Future Fund."
                ),
                greeting=f"Hi {guardian.display_name},",
                paragraphs=[
                    f"{user.display_name} is ready to give to {child.first_name}'s "
                    f"Future Fund, but it isn't set up yet.",
                    "It only takes a few minutes to finish. Then the whole family "
                    "can start giving.",
                ],
                cta_label="Finish setting up the Future Fund",
                cta_url=child_url,
            ),
        )
    return FundNudgeOut(sent=True)
