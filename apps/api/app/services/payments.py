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
from .email_templates import render_email
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

    def refund_payment(self, contribution: Contribution, amount_cents: int) -> bool:
        """Refund `amount_cents` (gross) of a settled payment; True on success."""
        ...

    def payment_status(self, contribution: Contribution) -> str | None:
        """Live provider status of the payment (for reconciling stuck records)."""
        ...


class LocalPaymentProvider:
    """Dev-only simulated card processor. Always succeeds."""

    settles_via_webhook = False

    def create_payment(self, contribution: Contribution) -> tuple[str, str | None]:
        return f"local_{uuid.uuid4().hex}", None

    def confirm_payment(self, contribution: Contribution) -> bool:
        return contribution.provider_payment_id is not None

    def refund_payment(self, contribution: Contribution, amount_cents: int) -> bool:
        return True

    def payment_status(self, contribution: Contribution) -> str | None:
        return "succeeded"


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

    def refund_payment(self, contribution: Contribution, amount_cents: int) -> bool:
        if not contribution.provider_payment_id:
            return False
        self.client.refunds.create(
            params={
                "payment_intent": contribution.provider_payment_id,
                "amount": amount_cents,  # partial when < the full charge
            }
        )
        return True

    def payment_status(self, contribution: Contribution) -> str | None:
        if not contribution.provider_payment_id:
            return None
        try:
            return self.client.payment_intents.retrieve(contribution.provider_payment_id).status
        except Exception:
            return None


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


def _net_reversed_for(contribution: Contribution, gross_refunded: int) -> int:
    """Cumulative NET (fee-adjusted) reversed once `gross_refunded` gross has
    been refunded. Rounding is applied to the cumulative figure so successive
    partial refunds always sum to exactly the full net at 100% refunded."""
    net_total = contribution.amount_cents - contribution.fee_cents
    return round(gross_refunded * net_total / contribution.amount_cents)


def refund_contribution(db: Session, contribution: Contribution, amount_cents: int | None = None) -> bool:
    """Refund a settled contribution, in full or in part, at the provider, then
    reverse the proportional net in the ledger with a compensating (negative)
    append-only entry — never by mutating the original. `amount_cents` is the
    gross to return to the contributor; None means the full remaining amount.
    Returns False if the provider refund fails (nothing is changed then)."""
    if contribution.status not in (ContributionStatus.succeeded,):
        return False
    remaining = contribution.amount_cents - contribution.refunded_cents
    if remaining <= 0:
        return False
    refund_gross = remaining if amount_cents is None else amount_cents
    if refund_gross <= 0 or refund_gross > remaining:
        return False
    if not get_payment_provider().refund_payment(contribution, refund_gross):
        return False

    # reverse only the incremental net for this refund, keeping cumulative exact
    net_before = _net_reversed_for(contribution, contribution.refunded_cents)
    contribution.refunded_cents += refund_gross
    net_after = _net_reversed_for(contribution, contribution.refunded_cents)
    reversal = net_after - net_before
    if contribution.refunded_cents >= contribution.amount_cents:
        contribution.status = ContributionStatus.refunded

    account = get_or_create_fund_account(db, contribution.child_id, contribution.currency)
    db.add(
        FundLedgerEntry(
            account_id=account.id,
            amount_cents=-reversal,
            entry_type=LedgerEntryType.adjustment,
            source_contribution_id=None,
            anchor_ref=None,
        )
    )
    return True


def reconcile_contribution(db: Session, contribution: Contribution) -> str:
    """Resolve a stuck pending contribution against the provider's live status
    (for cases where a webhook was missed or the payment was cancelled). Only
    acts on pending records. Returns the resulting status string."""
    if contribution.status != ContributionStatus.pending:
        return contribution.status.value
    live = get_payment_provider().payment_status(contribution)
    if live == "succeeded":
        settle_contribution(db, contribution)  # sets status + ledger + feed + emails
    elif live in ("canceled", "cancelled"):
        contribution.status = ContributionStatus.failed
    # other live states (processing, requires_payment_method, requires_action)
    # are genuinely still open, so we leave the record pending
    return contribution.status.value


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
    family_url = f"{settings.web_base_url}/family/{child.family_id}"
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
                + f"\nSee it here: {family_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=(
                    f"{contributor.display_name} added {amount} to "
                    f"{child.first_name}'s future fund."
                ),
                greeting=f"Hi {parent.display_name},",
                paragraphs=[
                    f"{contributor.display_name} contributed {amount} to "
                    f"{child.first_name}'s future fund"
                    + (" with a note:" if contribution.message else ".")
                ],
                highlight=(f"“{contribution.message}”" if contribution.message else None),
                cta_label="See it on your family feed",
                cta_url=family_url,
            ),
        )
    return entry
