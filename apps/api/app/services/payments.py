"""Payment provider abstraction and the single ledger-write path.

Money discipline (docs/data-model.md):
- integer cents + currency, always
- the fund ledger is append-only
- ledger entries are written ONLY from a verified payment-success event —
  the local simulator's verified confirm, or a signature-verified Stripe
  webhook — and only via settle_contribution below
- balances are always derived (SUM over entries), never stored

Backends:
- LocalPaymentProvider (dev): simulated card flow, settled by the
  POST /contributions/{id}/confirm endpoint.
- StripePaymentProvider (prod): PaymentIntent created here, card collected
  by Stripe Elements in the browser, settled ONLY by the signed
  payment_intent.succeeded webhook (never by client say-so).
"""

import uuid
from typing import Protocol

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Contribution,
    ContributionStatus,
    FamilyMember,
    FamilyRole,
    FeedEventType,
    FundAccount,
    FundLedgerEntry,
    LedgerEntryType,
    MemberStatus,
    User,
)
from .email import get_email_sender
from .feed import emit


def contribution_fee_cents(amount_cents: int) -> int:
    """Platform fee, deducted from the contribution (basis points from config)."""
    return (amount_cents * settings.contribution_fee_bps) // 10_000


class PaymentProvider(Protocol):
    settles_via_webhook: bool

    def create_payment(self, contribution: Contribution) -> tuple[str, str | None]:
        """Start a payment; returns (provider_payment_id, client_secret_or_None)."""
        ...

    def confirm_payment(self, contribution: Contribution) -> bool:
        """Local backend only: verify the simulated payment succeeded."""
        ...


class LocalPaymentProvider:
    """Dev-only simulated card processor. Always succeeds."""

    settles_via_webhook = False

    def create_payment(self, contribution: Contribution) -> tuple[str, str | None]:
        return f"local_{uuid.uuid4().hex}", None

    def confirm_payment(self, contribution: Contribution) -> bool:
        return contribution.provider_payment_id is not None


class StripePaymentProvider:
    settles_via_webhook = True

    def __init__(self, secret_key: str) -> None:
        import stripe

        self.client = stripe.StripeClient(secret_key)

    def create_payment(self, contribution: Contribution) -> tuple[str, str | None]:
        intent = self.client.payment_intents.create(
            params={
                "amount": contribution.amount_cents,
                "currency": contribution.currency.lower(),
                "automatic_payment_methods": {"enabled": True},
                "metadata": {
                    "contribution_id": str(contribution.id),
                    "child_id": str(contribution.child_id),
                },
                "description": "FutureRoots family contribution",
            }
        )
        return intent.id, intent.client_secret

    def confirm_payment(self, contribution: Contribution) -> bool:
        raise NotImplementedError("Stripe settles via the signed webhook only")


def _build_provider() -> PaymentProvider:
    if settings.payment_backend == "stripe":
        return StripePaymentProvider(settings.stripe_secret_key)
    return LocalPaymentProvider()


_provider: PaymentProvider = _build_provider()


def get_payment_provider() -> PaymentProvider:
    return _provider


def get_or_create_fund_account(db: Session, child_id: uuid.UUID, currency: str) -> FundAccount:
    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    if account is None:
        account = FundAccount(child_id=child_id, currency=currency)
        db.add(account)
        db.flush()
    return account


def fund_balance_cents(db: Session, account_id: uuid.UUID) -> int:
    return (
        db.query(func.coalesce(func.sum(FundLedgerEntry.amount_cents), 0))
        .filter(FundLedgerEntry.account_id == account_id)
        .scalar()
    )


def settle_contribution(db: Session, contribution: Contribution) -> FundLedgerEntry:
    """THE settlement path: ledger entry + feed celebration + parent emails.
    Call only after payment success is verified (local confirm or signed
    Stripe webhook). Idempotent at the DB level via the unique constraint on
    fund_ledger_entries.source_contribution_id; callers must also check
    status to avoid duplicate feed events."""
    contribution.status = ContributionStatus.succeeded
    account = get_or_create_fund_account(db, contribution.child_id, contribution.currency)
    entry = FundLedgerEntry(
        account_id=account.id,
        amount_cents=contribution.amount_cents - contribution.fee_cents,
        entry_type=LedgerEntryType.contribution,
        source_contribution_id=contribution.id,
        # Phase 6: AnchorService records a contribution proof on Base here
        anchor_ref=None,
    )
    db.add(entry)

    child = contribution.child
    contributor = contribution.contributor
    emit(
        db,
        family_id=child.family_id,
        actor_user_id=contributor.id,
        type=FeedEventType.contribution,
        child_id=child.id,
        payload={
            "contribution_id": str(contribution.id),
            "child_name": child.first_name,
            "contributor_name": contributor.display_name,
            "amount_cents": contribution.amount_cents,
            "currency": contribution.currency,
            "message": contribution.message,
        },
    )

    parents = (
        db.query(User)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .filter(
            FamilyMember.family_id == child.family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role.in_([FamilyRole.parent, FamilyRole.guardian]),
            User.id != contributor.id,
        )
        .all()
    )
    sender = get_email_sender()
    amount = f"${contribution.amount_cents / 100:,.2f}"
    for parent in parents:
        sender.send(
            to=parent.email,
            subject=f"{contributor.display_name} just added to {child.first_name}'s future",
            body=(
                f"Hi {parent.display_name},\n\n"
                f"{contributor.display_name} contributed {amount} to {child.first_name}'s "
                f"future fund"
                + (
                    f" with a note:\n\n  “{contribution.message}”\n"
                    if contribution.message
                    else ".\n"
                )
                + f"\nSee it here: {settings.web_base_url}/family/{child.family_id}\n\n"
                f"With warmth,\nFutureRoots"
            ),
        )
    return entry
