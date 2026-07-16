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
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class SubscriptionState:
    """Point-in-time live subscription state (subscriptions.retrieve)."""

    subscription_id: str
    customer_id: str
    status: str                      # raw Stripe status string
    price_id: str                    # maps to plan via settings
    current_period_end: datetime
    cancel_at_period_end: bool
    metadata: dict[str, str]


@dataclass(frozen=True)
class CheckoutResult:
    """Live checkout-session state (checkout.sessions.retrieve) for /sync."""

    session_id: str
    kind: str                        # metadata["kind"]
    paid: bool                       # payment_status == "paid"
    subscription_id: str | None
    payment_intent_id: str | None
    amount_total: int | None         # integer cents
    currency: str | None
    price_id: str | None             # first line item's price (gift verification)
    metadata: dict[str, str]


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

    # --- FutureRoots Premium (family subscription + one-time gift) ---

    def get_or_create_customer(
        self,
        *,
        email: str,
        display_name: str,
        user_id: str,
        existing_customer_id: str | None,
    ) -> str:
        """Return the user's Stripe customer id, creating one if needed
        (idempotency key fr-customer-{user_id}). Local: 'cus_local_{user_id}'."""
        ...

    def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
        idempotency_scope: str,
    ) -> tuple[str, str]:
        """(session_id, redirect_url) for a mode=subscription Checkout."""
        ...

    def create_gift_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]:
        """(session_id, redirect_url) for a mode=payment Checkout."""
        ...

    def subscription_state(self, subscription_id: str) -> SubscriptionState | None:
        """Live retrieve; None if the subscription doesn't exist. Local: None
        (the local backend mirrors state directly in the DB)."""
        ...

    def checkout_result(self, session_id: str) -> CheckoutResult | None:
        """Live session retrieve for the /sync reconcile path."""
        ...

    def set_cancel_at_period_end(
        self, subscription_id: str, cancel: bool
    ) -> SubscriptionState | None:
        """Flip auto-renew; returns the resulting live state. Local: None (no-op)."""
        ...

    def cancel_subscription_now(
        self, subscription_id: str, *, refund_latest_charge: bool
    ) -> None:
        """Immediate cancel + refund — ONLY for the accidental double-subscribe
        guard. Never used by the user-facing cancel flow."""
        ...

    def create_billing_portal(self, customer_id: str, *, return_url: str) -> str:
        """Hosted Billing Portal URL. Local: '{return_url}?portal=simulated'."""
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

    # --- Premium: the routers settle synchronously through the same settlement
    # functions the Stripe webhook calls, so no live state exists to retrieve.

    def get_or_create_customer(
        self,
        *,
        email: str,
        display_name: str,
        user_id: str,
        existing_customer_id: str | None,
    ) -> str:
        return existing_customer_id or f"cus_local_{user_id}"

    def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
        idempotency_scope: str,
    ) -> tuple[str, str]:
        session_id = f"cs_local_{uuid.uuid4().hex}"
        return session_id, success_url.replace("{CHECKOUT_SESSION_ID}", session_id)

    def create_gift_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]:
        session_id = f"cs_local_{uuid.uuid4().hex}"
        return session_id, success_url.replace("{CHECKOUT_SESSION_ID}", session_id)

    def subscription_state(self, subscription_id: str) -> "SubscriptionState | None":
        return None  # local mode mirrors state directly in the DB

    def checkout_result(self, session_id: str) -> "CheckoutResult | None":
        return None  # local checkouts settle synchronously; nothing to reconcile

    def set_cancel_at_period_end(
        self, subscription_id: str, cancel: bool
    ) -> "SubscriptionState | None":
        return None  # the router flips the mirror row directly in local mode

    def cancel_subscription_now(
        self, subscription_id: str, *, refund_latest_charge: bool
    ) -> None:
        return None

    def create_billing_portal(self, customer_id: str, *, return_url: str) -> str:
        return f"{return_url}?portal=simulated"


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

    # --- Premium: customers, Checkout sessions, subscriptions, Billing Portal ---

    @staticmethod
    def _obj_field(obj, key: str, default=None):
        """StripeObject supports [] but not dict.get()."""
        try:
            value = obj[key]
        except (KeyError, TypeError):
            return default
        return default if value is None else value

    @staticmethod
    def _obj_dict(obj) -> dict:
        """StripeObject (v15+) is not a Mapping — dict(obj) breaks; it exposes
        to_dict() instead. Plain dicts pass through."""
        if obj is None:
            return {}
        to_dict = getattr(obj, "to_dict", None)
        if callable(to_dict):
            return dict(to_dict())
        if isinstance(obj, dict):
            return dict(obj)
        return {}

    def _to_subscription_state(self, sub) -> SubscriptionState:
        items = self._obj_field(sub, "items", {})
        data = list(self._obj_field(items, "data", []) or [])
        first = data[0] if data else {}
        price = self._obj_field(first, "price", {})
        price_id = self._obj_field(price, "id", "") or ""
        # current_period_end lives on the subscription in classic API versions
        # and on the item in newer ones; accept either.
        period_end = self._obj_field(sub, "current_period_end") or self._obj_field(
            first, "current_period_end"
        )
        period_end_dt = (
            datetime.fromtimestamp(int(period_end), tz=timezone.utc)
            if period_end
            else datetime.now(timezone.utc)
        )
        metadata = self._obj_dict(self._obj_field(sub, "metadata", {}))
        return SubscriptionState(
            subscription_id=sub["id"],
            customer_id=str(self._obj_field(sub, "customer", "") or ""),
            status=str(self._obj_field(sub, "status", "") or ""),
            price_id=price_id,
            current_period_end=period_end_dt,
            cancel_at_period_end=bool(self._obj_field(sub, "cancel_at_period_end", False)),
            metadata=metadata,
        )

    def get_or_create_customer(
        self,
        *,
        email: str,
        display_name: str,
        user_id: str,
        existing_customer_id: str | None,
    ) -> str:
        if existing_customer_id:
            return existing_customer_id
        customer = self.client.customers.create(
            params={
                "email": email,
                "name": display_name,
                # Opaque UUID only — never child data, never free text.
                "metadata": {"futureroots_user_id": user_id},
            },
            options={"idempotency_key": f"fr-customer-{user_id}"},
        )
        return customer.id

    def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
        idempotency_scope: str,
    ) -> tuple[str, str]:
        session = self.client.checkout.sessions.create(
            params={
                "mode": "subscription",
                "customer": customer_id,
                "line_items": [{"price": price_id, "quantity": 1}],
                "client_reference_id": metadata.get("family_id", ""),
                # Duplicated onto the subscription so every customer.subscription.*
                # event self-identifies without a session lookup.
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
                "success_url": success_url,
                "cancel_url": cancel_url,
                "allow_promotion_codes": False,
            },
            options={"idempotency_key": f"fr-premium-sub-{idempotency_scope}"},
        )
        return session.id, session.url

    def create_gift_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        metadata: dict[str, str],
        success_url: str,
        cancel_url: str,
    ) -> tuple[str, str]:
        session = self.client.checkout.sessions.create(
            params={
                "mode": "payment",
                "customer": customer_id,
                "line_items": [{"price": price_id, "quantity": 1}],
                "metadata": metadata,
                "success_url": success_url,
                "cancel_url": cancel_url,
            }
        )
        return session.id, session.url

    def subscription_state(self, subscription_id: str) -> SubscriptionState | None:
        try:
            sub = self.client.subscriptions.retrieve(subscription_id)
        except Exception:
            return None
        return self._to_subscription_state(sub)

    def checkout_result(self, session_id: str) -> CheckoutResult | None:
        try:
            session = self.client.checkout.sessions.retrieve(
                session_id, params={"expand": ["line_items"]}
            )
        except Exception:
            return None
        metadata = self._obj_dict(self._obj_field(session, "metadata", {}))
        line_items = self._obj_field(session, "line_items", {})
        data = list(self._obj_field(line_items, "data", []) or [])
        first = data[0] if data else {}
        price = self._obj_field(first, "price", {})
        price_id = self._obj_field(price, "id")
        subscription = self._obj_field(session, "subscription")
        payment_intent = self._obj_field(session, "payment_intent")
        amount_total = self._obj_field(session, "amount_total")
        return CheckoutResult(
            session_id=session["id"],
            kind=str(metadata.get("kind", "")),
            paid=self._obj_field(session, "payment_status") == "paid",
            subscription_id=str(subscription) if subscription else None,
            payment_intent_id=str(payment_intent) if payment_intent else None,
            amount_total=int(amount_total) if amount_total is not None else None,
            currency=self._obj_field(session, "currency"),
            price_id=str(price_id) if price_id else None,
            metadata=metadata,
        )

    def set_cancel_at_period_end(
        self, subscription_id: str, cancel: bool
    ) -> SubscriptionState | None:
        try:
            sub = self.client.subscriptions.update(
                subscription_id, params={"cancel_at_period_end": cancel}
            )
        except Exception:
            return None
        return self._to_subscription_state(sub)

    def cancel_subscription_now(
        self, subscription_id: str, *, refund_latest_charge: bool
    ) -> None:
        """Best-effort: used only by the double-subscribe guard. Failures are
        left for the admin reconcile (the Stripe dashboard shows the duplicate)."""
        try:
            sub = self.client.subscriptions.retrieve(
                subscription_id, params={"expand": ["latest_invoice"]}
            )
            self.client.subscriptions.cancel(subscription_id)
            if refund_latest_charge:
                invoice = self._obj_field(sub, "latest_invoice", {})
                payment_intent = self._obj_field(invoice, "payment_intent")
                if payment_intent:
                    self.client.refunds.create(
                        params={"payment_intent": str(payment_intent)}
                    )
        except Exception:  # noqa: BLE001 — deliberately best-effort
            import logging

            logging.getLogger(__name__).warning(
                "cancel_subscription_now failed for %s — reconcile manually",
                subscription_id,
            )

    def create_billing_portal(self, customer_id: str, *, return_url: str) -> str:
        session = self.client.billing_portal.sessions.create(
            params={"customer": customer_id, "return_url": return_url}
        )
        return session.url


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
