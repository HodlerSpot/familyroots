"""Payment provider abstraction and the single ledger-write path.

Money discipline (docs/data-model.md):
- integer cents + currency, always
- the fund ledger is append-only
- ledger entries are written ONLY from a verified payment-success event, and
  only by record_payment_succeeded below — no other code writes the ledger
- balances are always derived (SUM over entries), never stored

The local provider simulates the card flow so everything works end to end
with no cloud dependency; the Stripe implementation replaces create/confirm
with PaymentIntents + signed webhooks, then calls the same
record_payment_succeeded.
"""

import uuid
from typing import Protocol

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Contribution,
    ContributionStatus,
    FundAccount,
    FundLedgerEntry,
    LedgerEntryType,
)


def contribution_fee_cents(amount_cents: int) -> int:
    """Platform fee, deducted from the contribution (basis points from config)."""
    return (amount_cents * settings.contribution_fee_bps) // 10_000


class PaymentProvider(Protocol):
    def create_payment(self, contribution: Contribution) -> str:
        """Start a payment; returns the provider's payment id."""
        ...

    def confirm_payment(self, contribution: Contribution) -> bool:
        """Confirm/settle the payment; True when the provider verified success.
        (Stripe: this step is replaced by Stripe.js + signed webhook.)"""
        ...


class LocalPaymentProvider:
    """Dev-only simulated card processor. Always succeeds."""

    def create_payment(self, contribution: Contribution) -> str:
        return f"local_{uuid.uuid4().hex}"

    def confirm_payment(self, contribution: Contribution) -> bool:
        return contribution.provider_payment_id is not None


_provider: PaymentProvider = LocalPaymentProvider()


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


def record_payment_succeeded(db: Session, contribution: Contribution) -> FundLedgerEntry:
    """THE ledger-write path. Call only after the provider verified success.
    Idempotent via the unique constraint on source_contribution_id."""
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
    return entry
