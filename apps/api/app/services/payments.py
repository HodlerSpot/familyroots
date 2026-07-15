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
from dataclasses import dataclass
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
    FundAccountStatus,
    FundLedgerEntry,
    LedgerEntryType,
    MemberStatus,
    User,
    utcnow,
)
from .email import get_email_sender
from .email_templates import render_email
from .feed import emit


def contribution_fee_cents(amount_cents: int) -> int:
    """The application fee kept by the platform on a destination charge:
    Stripe's US-card baseline (2.9% + 30¢), variable part rounded UP so the
    fee always covers the processing cost and the platform nets ~0 (it absorbs
    the small variance on international/Amex cards). The child's account
    receives amount − fee. Minimum contribution is 100¢ → minimum net 67¢."""
    variable = -(-amount_cents * settings.contribution_fee_bps // 10_000)  # ceil
    fee = variable + settings.contribution_fee_fixed_cents
    if fee >= amount_cents:
        raise ValueError("Fee would consume the whole contribution")
    return fee


@dataclass(frozen=True)
class ConnectAccountState:
    """A point-in-time snapshot of a connected account's Stripe state."""

    details_submitted: bool
    charges_enabled: bool
    payouts_enabled: bool
    transfers_active: bool  # the transfers capability is active
    requirements_due: bool  # Stripe is waiting on more information


class PaymentProvider(Protocol):
    settles_via_webhook: bool

    def create_payment(
        self, contribution: Contribution, *, destination_account: str | None = None
    ) -> tuple[str, str | None]:
        """Start a payment; returns (provider_payment_id, client_secret_or_None).
        With destination_account, the funds (net of the application fee) are
        transferred to that connected account."""
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

    def payment_routing(self, contribution: Contribution) -> tuple[str | None, int | None] | None:
        """Live (destination, application_fee) of the payment, for verifying a
        settle outside the webhook. None means the provider has no routing to
        verify (local backend), so the caller may trust its own settle path."""
        ...

    def create_connect_account(
        self, *, email: str, metadata: dict[str, str], idempotency_scope: str
    ) -> str:
        """Create the child's Express account (owned by the parent); returns
        the account id. Idempotent per scope so a double-click can't create two."""
        ...

    def create_account_link(
        self, account_id: str, *, return_url: str, refresh_url: str
    ) -> str:
        """Mint a single-use hosted-onboarding URL. Links expire and are
        single-use, so callers mint a fresh one every time and never store it."""
        ...

    def connect_account_state(self, account_id: str) -> ConnectAccountState:
        """Live account state, straight from the provider (never from a payload)."""
        ...


class LocalPaymentProvider:
    """Dev-only simulated card processor. Always succeeds."""

    settles_via_webhook = False

    def create_payment(
        self, contribution: Contribution, *, destination_account: str | None = None
    ) -> tuple[str, str | None]:
        return f"local_{uuid.uuid4().hex}", None

    def confirm_payment(self, contribution: Contribution) -> bool:
        return contribution.provider_payment_id is not None

    def refund_payment(self, contribution: Contribution, amount_cents: int) -> bool:
        return True

    def payment_status(self, contribution: Contribution) -> str | None:
        return "succeeded"

    def payment_routing(self, contribution: Contribution) -> tuple[str | None, int | None] | None:
        return None  # no live routing to verify locally; the local settle path is trusted

    def create_connect_account(
        self, *, email: str, metadata: dict[str, str], idempotency_scope: str
    ) -> str:
        return f"acct_local_{uuid.uuid4().hex}"

    def create_account_link(
        self, account_id: str, *, return_url: str, refresh_url: str
    ) -> str:
        # No hosted onboarding locally: send the browser straight back.
        return f"{return_url}?simulated=1"

    def connect_account_state(self, account_id: str) -> ConnectAccountState:
        # Local accounts onboard instantly.
        return ConnectAccountState(
            details_submitted=True,
            charges_enabled=True,
            payouts_enabled=True,
            transfers_active=True,
            requirements_due=False,
        )


class StripePaymentProvider:
    settles_via_webhook = True

    def __init__(self, secret_key: str) -> None:
        import stripe

        self.client = stripe.StripeClient(secret_key)

    def create_payment(
        self, contribution: Contribution, *, destination_account: str | None = None
    ) -> tuple[str, str | None]:
        params: dict = {
            "amount": contribution.amount_cents,
            "currency": contribution.currency.lower(),
            "automatic_payment_methods": {"enabled": True},
            "metadata": {
                "contribution_id": str(contribution.id),
                "child_id": str(contribution.child_id),
            },
            "description": "FutureRoots family contribution",
        }
        if destination_account:
            # Destination charge: the platform is the merchant of record (no
            # on_behalf_of, so charges succeed while the parent's card_payments
            # capability is still pending, as long as transfers is active).
            # Stripe transfers amount − application_fee to the child's account.
            params["transfer_data"] = {"destination": destination_account}
            params["application_fee_amount"] = contribution.fee_cents
            params["transfer_group"] = f"contribution_{contribution.id}"
        intent = self.client.payment_intents.create(params=params)
        return intent.id, intent.client_secret

    def confirm_payment(self, contribution: Contribution) -> bool:
        raise NotImplementedError("Stripe settles via the signed webhook only")

    def refund_payment(self, contribution: Contribution, amount_cents: int) -> bool:
        if not contribution.provider_payment_id:
            return False
        params: dict = {
            "payment_intent": contribution.provider_payment_id,
            "amount": amount_cents,  # partial when < the full charge
        }
        # Destination charge: claw the proportional transfer back from the
        # connected account and return the proportional app fee, so contributor
        # / child / platform all unwind together. Legacy (pre-Connect) charges
        # have no transfer — Stripe rejects reverse_transfer on them, so only
        # send the flags when the intent actually carried a destination.
        routing = self.payment_routing(contribution)
        if routing is not None and routing[0] is not None:
            params["refund_application_fee"] = True
            params["reverse_transfer"] = True
        self.client.refunds.create(params=params)
        return True

    def payment_status(self, contribution: Contribution) -> str | None:
        if not contribution.provider_payment_id:
            return None
        try:
            return self.client.payment_intents.retrieve(contribution.provider_payment_id).status
        except Exception:
            return None

    def payment_routing(self, contribution: Contribution) -> tuple[str | None, int | None] | None:
        """(transfer destination, application fee) straight from the live PI.
        StripeObject supports [] but not .get()."""
        if not contribution.provider_payment_id:
            return (None, None)
        try:
            intent = self.client.payment_intents.retrieve(contribution.provider_payment_id)
        except Exception:
            return (None, None)
        try:
            transfer_data = intent["transfer_data"]
        except KeyError:
            transfer_data = None
        destination = None
        if transfer_data is not None:
            try:
                destination = transfer_data["destination"]
            except KeyError:
                destination = None
        try:
            app_fee = intent["application_fee_amount"]
        except KeyError:
            app_fee = None
        return (destination, app_fee)

    def create_connect_account(
        self, *, email: str, metadata: dict[str, str], idempotency_scope: str
    ) -> str:
        account = self.client.accounts.create(
            params={
                "type": "express",
                "country": "US",
                "email": email,
                "business_type": "individual",
                "capabilities": {
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
                "metadata": metadata,
            },
            options={"idempotency_key": f"fr-connect-acct-{idempotency_scope}"},
        )
        return account.id

    def create_account_link(
        self, account_id: str, *, return_url: str, refresh_url: str
    ) -> str:
        link = self.client.account_links.create(
            params={
                "account": account_id,
                "type": "account_onboarding",
                "return_url": return_url,
                "refresh_url": refresh_url,
            }
        )
        return link.url

    def connect_account_state(self, account_id: str) -> ConnectAccountState:
        account = self.client.accounts.retrieve(account_id)
        capabilities = getattr(account, "capabilities", None)
        transfers = getattr(capabilities, "transfers", None) if capabilities else None
        requirements = getattr(account, "requirements", None)
        currently_due = list(getattr(requirements, "currently_due", None) or [])
        past_due = list(getattr(requirements, "past_due", None) or [])
        return ConnectAccountState(
            details_submitted=bool(account.details_submitted),
            charges_enabled=bool(account.charges_enabled),
            payouts_enabled=bool(account.payouts_enabled),
            transfers_active=transfers == "active",
            requirements_due=bool(currently_due or past_due),
        )


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


def sync_fund_account_state(fund_account: FundAccount, state: ConnectAccountState) -> None:
    """Fold a live ConnectAccountState into our cached columns. The cache is
    informational only — money always moves against Stripe's live state.
    Active means gifts can actually reach the child: the transfers capability
    is live AND payouts are enabled."""
    fund_account.charges_enabled = state.charges_enabled
    fund_account.payouts_enabled = state.payouts_enabled
    fund_account.requirements_due = state.requirements_due
    if state.transfers_active and state.payouts_enabled:
        if fund_account.account_status != FundAccountStatus.active:
            fund_account.activated_at = utcnow()
        fund_account.account_status = FundAccountStatus.active
    elif not state.details_submitted:
        fund_account.account_status = FundAccountStatus.onboarding
    else:
        fund_account.account_status = FundAccountStatus.restricted


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
    provider = get_payment_provider()
    live = provider.payment_status(contribution)
    if live == "succeeded":
        # The webhook refuses to ledger a PI whose destination/fee doesn't
        # match what we route today; reconcile must not become the bypass for
        # that same guard. Verify against the LIVE intent (routing is None on
        # the local backend, whose settle path is separately trusted).
        routing = provider.payment_routing(contribution)
        if routing is not None:
            destination, app_fee = routing
            account = (
                db.query(FundAccount)
                .filter(FundAccount.child_id == contribution.child_id)
                .first()
            )
            expected = account.stripe_account_id if account else None
            ok = (
                expected is None
                if destination is None
                else (destination == expected and app_fee == contribution.fee_cents)
            )
            if not ok:
                # Money went somewhere we don't route today: never ledger it.
                # Stays pending for a human with the Stripe dashboard open.
                return contribution.status.value
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
