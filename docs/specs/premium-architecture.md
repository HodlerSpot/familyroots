# FutureRoots Premium — Technical Architecture

Status: **approved design — drives implementation** · Owner: Technical Architect
Product truth: `docs/specs/premium.md` (do not redesign flows here). Companion docs updated: `docs/architecture.md`, `docs/data-model.md`.

Premium is a **family-level** paid membership: $9.99/mo or $99/yr recurring (Stripe Billing via Checkout), plus a one-time $99 **gift** of 12 months (Stripe Checkout `mode=payment`). Gated capabilities at launch: `video_upload`, `family_video_call`.

---

## 0. Key architecture decisions (summary)

| Decision | Choice |
|---|---|
| Payment UI | **Stripe Checkout (hosted redirect)** for both subscribe and gift — not PaymentElement. Rationale in §5. |
| Stripe customer | **One Stripe Customer per FutureRoots user** (`users.stripe_customer_id`, lazy-created). Subscribers *and* gifters get one; a user in two families reuses the same customer. |
| Premium state | **Always derived** at read time from `family_subscriptions` + `premium_grants`. No `is_premium` column anywhere. |
| Webhook trust model | Gift settlement trusts the **signed payload** (immutable one-time facts + unique-key idempotency). Subscription mirroring **always re-fetches live subscription state** from Stripe (`subscriptions.retrieve`) — the event is only a trigger, so event ordering never matters. Same pattern as the Connect webhook. |
| Gift message | **Never sent to Stripe.** Stored in a local `premium_gift_intents` staging row keyed by checkout session id; the webhook joins on it. Keeps free-text (which may name children) out of Stripe — COPPA by construction. |
| Gating enforcement | Server-side `require_capability()` in `app/services/entitlements.py`; structured **402** `{"code": "premium_required", "capability": ...}`. Client affordances read `plan`/`capabilities` from family payloads but are never the enforcement. |
| Local dev | `LocalPaymentProvider` checkout **settles synchronously through the same settlement functions** the webhook calls, then redirects to the success URL. Stripe-path logic is tested with the existing signed-webhook harness. |
| Grant-lapse emails | Webhook-driven where Stripe gives us an event; the one non-Stripe case (gift-only coverage lapsing) is **request-driven lazy dispatch** with a send-once log — no cron, no workers (§10.4). |
| Serverless fit | Every side effect happens inside a request or webhook invocation. No new infra beyond three env vars. Cost impact ≈ $0. |

---

## 1. Schema

One Alembic migration off HEAD `b7d3e91c4f20`. All enums follow the existing `native_enum=False, length=20` pattern (VARCHAR — adding future values needs no DDL). All timestamps `DateTime(timezone=True)`, UTC via the existing `utcnow`.

### 1.1 New column on `users` (`apps/api/app/models.py`, User ~L165)

```python
# One Stripe Customer per adult user, created lazily on their first checkout
# (subscribe OR gift). Server-only; never exposed in any API payload.
stripe_customer_id: Mapped[str | None] = mapped_column(
    String(64), nullable=True, unique=True
)
```

### 1.2 New enums

```python
class SubscriptionPlan(str, enum.Enum):
    monthly = "monthly"
    annual = "annual"


class SubscriptionStatus(str, enum.Enum):
    active = "active"        # Stripe: active | trialing (we sell no trials)
    past_due = "past_due"    # Stripe: past_due — Smart Retries window = grace period
    canceled = "canceled"    # Stripe: canceled | unpaid | incomplete_expired


class FeedEventType(str, enum.Enum):
    ...existing values...
    premium_activated = "premium_activated"
    premium_gifted = "premium_gifted"
```

### 1.3 `family_subscriptions` — Stripe mirror, one live row per family

```python
class FamilySubscription(Base):
    """Mirror of the family's recurring Stripe subscription. Written ONLY by
    verified webhook handlers, the parent-initiated /sync reconcile (which
    reads live Stripe state), and the local backend's simulated settle —
    never from client say-so."""

    __tablename__ = "family_subscriptions"
    __table_args__ = (
        # At most one non-canceled subscription per family (double-subscribe backstop)
        Index(
            "uq_family_subscriptions_live",
            "family_id",
            unique=True,
            postgresql_where=text("status != 'canceled'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stripe_customer_id: Mapped[str] = mapped_column(String(64))
    stripe_subscription_id: Mapped[str] = mapped_column(String(64), unique=True)
    plan: Mapped[SubscriptionPlan] = mapped_column(Enum(SubscriptionPlan, native_enum=False, length=20))
    status: Mapped[SubscriptionStatus] = mapped_column(Enum(SubscriptionStatus, native_enum=False, length=20))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
```

### 1.4 `premium_grants` — prepaid gift periods, append-only

```python
class PremiumGrant(Base):
    """A prepaid Premium period (gift). Append-only: written ONLY when a
    verified webhook (or the live-Stripe /sync path) confirms payment.
    The single permitted mutation is the admin-only void (support refunds) —
    same deliberate exception as contributions.refunded_cents."""

    __tablename__ = "premium_grants"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_premium_grants_period"),
        CheckConstraint("amount_cents > 0", name="ck_premium_grants_amount"),
        Index("ix_premium_grants_family_ends", "family_id", "ends_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="gift")  # future: "promo", "support"
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), unique=True)  # idempotency key
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount_cents: Mapped[int] = mapped_column()          # integer cents, always
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Admin-only void (manual refund/chargeback support path); voided grants
    # are ignored by the entitlement derivation but never deleted.
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

### 1.5 `premium_gift_intents` — pre-checkout staging (keeps the message out of Stripe)

```python
class PremiumGiftIntent(Base):
    """Created when a gifter starts checkout; holds the gift message locally so
    free text (which may name a child) is NEVER sent to Stripe. Not a money
    row — abandoned checkouts leave a harmless orphan here (no grant, no feed
    event, no email). Prunable after 30 days by the admin sweep."""

    __tablename__ = "premium_gift_intents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    gifter_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), unique=True)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

### 1.6 `premium_email_log` — send-once idempotency for lifecycle emails

```python
class PremiumEmailLog(Base):
    """One row per (kind, dedupe_key) ever sent. INSERT with the unique
    constraint is the race-safe guard: insert first, send only on success."""

    __tablename__ = "premium_email_log"
    __table_args__ = (UniqueConstraint("kind", "dedupe_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("families.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))   # payment_failed | renewal_upcoming | premium_ended | gift_ending_soon
    dedupe_key: Mapped[str] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

Dedupe keys: `payment_failed` → Stripe invoice id · `renewal_upcoming` → `{subscription_id}:{period_end.isoformat()}` (upcoming invoices have no id) · `premium_ended` → `{family_id}:{premium_until.isoformat()}` · `gift_ending_soon` → grant id.

Activation/gift emails and feed events need no log rows: they fire exactly when the mirror/grant row is **newly created**, and row creation is idempotent by unique key.

---

## 2. Derived entitlement (never a stored flag)

```
family is Premium ⇔
     EXISTS family_subscriptions s WHERE s.family_id = :f
         AND ( s.status = 'past_due'                                   -- Stripe retry window IS the grace period
             OR (s.status = 'active' AND now() < s.current_period_end + interval '72 hours') )
  OR EXISTS premium_grants g WHERE g.family_id = :f
         AND g.voided_at IS NULL AND g.starts_at <= now() AND now() < g.ends_at

premium_until(family) = greatest(
     max(s.current_period_end) over non-canceled subscriptions,
     max(g.ends_at) over unvoided grants where starts_at <= now  -- display uses real dates, no slack
)
```

Notes:

- **`past_due` holds entitlement unconditionally** (its `current_period_end` is typically in the past during retries). Stripe deterministically terminates the state — final retry failure emits `customer.subscription.deleted`/`updated → canceled|unpaid`, which flips our mirror to `canceled`.
- The **72-hour slack** on `active` exists only so a late/lost renewal webhook can't glitch a paying family to Free at the renewal instant; the `/sync` reconcile and admin reconcile fix genuinely stale rows. Displayed dates (`premium_until`) never include the slack.
- Two indexed lookups per check; the families list uses one grouped query for all of a user's families (§4.1).

---

## 3. Entitlements service — `apps/api/app/services/entitlements.py` (new)

Read-side only; pure queries + the 402. Write-side (settlement) lives in `services/premium.py` (§6).

```python
class Capability(str, enum.Enum):
    video_upload = "video_upload"
    family_video_call = "family_video_call"
    # Future premium features are one line here.

# Every capability in the registry requires Premium today; a future free-tier
# capability would simply not appear here.
PREMIUM_CAPABILITIES: frozenset[Capability] = frozenset(Capability)


def premium_until(db: Session, family_id: uuid.UUID) -> datetime | None: ...
def family_is_premium(db: Session, family_id: uuid.UUID) -> bool: ...

def family_capabilities(db: Session, family_id: uuid.UUID) -> list[str]:
    """[] for free families, sorted capability values for premium ones."""

def plans_for_families(db: Session, family_ids: list[uuid.UUID]) -> dict[uuid.UUID, bool]:
    """Batch: one grouped query over both tables, for GET /families."""

def require_capability(db: Session, family_id: uuid.UUID, capability: Capability) -> None:
    """Raises HTTPException(402) with structured detail when the family lacks
    the capability. THE enforcement point — call sites never write `if premium`."""
    if capability in PREMIUM_CAPABILITIES and not family_is_premium(db, family_id):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "premium_required",
                "capability": capability.value,
                # Warm, brand-safe fallback copy; the web app normally renders
                # its own upsell from the code and never shows this raw.
                "message": "This is part of FutureRoots Premium.",
            },
        )
```

### 3.1 Gating call sites (defense in depth — client affordance is never the enforcement)

| File | Where | Check |
|---|---|---|
| `apps/api/app/routers/vault.py` | `create_media` (~L90, after `get_child_with_access`) | `if payload.content_type.startswith("video/"): require_capability(db, child.family_id, Capability.video_upload)` |
| `apps/api/app/routers/legacy.py` | `create_family_media` (~L44, after `require_not_supporter`) | same, with `family_id` |
| `apps/api/app/routers/calls.py` | `join_call` (L284), `refresh_token` (L400), `heartbeat` (L320), `set_children_present` (L364), `set_planned` (L433) | `require_capability(db, family_id, Capability.family_video_call)` after the existing `_gate` |

Deliberately **not** gated: `call_state`, `get_planned`, `clear_planned`, `leave_call` (reads + graceful exit must always work — a family downgraded mid-call can see state and leave cleanly; the gated `refresh_token` ends their media within the 300s token TTL, and `heartbeat` gating expires their presence). `me.py` avatar media is user-scoped (no family), image-only in practice — out of scope. Uploads in flight at downgrade complete: the ticket was issued while entitled and `upload_media_content`/`complete` are not gated (matches spec §9).

`MediaCreate`'s regex already limits types; no schema change needed.

---

## 4. API contract

New router `apps/api/app/routers/premium.py`, mounted at `/families/{family_id}/premium` (registered in `app/main.py` like the others). New dep in `apps/api/app/deps.py`:

```python
def require_parent_role(membership: FamilyMember) -> None:
    """Billing is founder-fixed to parents — stricter than require_guardian_role
    (guardians manage children, not the family's plan)."""
    if membership.role != FamilyRole.parent:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a parent can manage the family plan")
```

### 4.1 Family payload additions (`apps/api/app/schemas.py`, `routers/families.py`)

- `FamilySummary` (schemas.py L91) gains `plan: Literal["free", "premium"]`. `my_families` (families.py L33) fills it via `plans_for_families` — one extra query total, no billing detail on the list (spec Flow D).
- `FamilyDetail` (schemas.py L108) gains `plan`, `premium_until: datetime | None`, `capabilities: list[str]`.

### 4.2 Endpoints

All request/response models live in `schemas.py`. `Plan = Literal["monthly", "annual"]`.

| Method + path | Guard (existing deps) | Request | Response |
|---|---|---|---|
| `GET /families/{id}/premium` | `get_active_membership` | — | `PremiumStatusOut` |
| `POST /families/{id}/premium/checkout` | `get_active_membership` + `require_parent_role` | `PremiumCheckoutIn` | `CheckoutSessionOut` |
| `POST /families/{id}/premium/gift-checkout` | `get_active_membership`; **role must NOT be parent** (parents get 409 `{"code": "use_subscribe"}`) — grandparent, relative, guardian, **and supporter** may gift (spec §4) | `GiftCheckoutIn` | `CheckoutSessionOut` |
| `POST /families/{id}/premium/cancel` | membership + `require_parent_role` (any parent, not only owner) | — | `PremiumStatusOut` |
| `POST /families/{id}/premium/resume` | membership + `require_parent_role`; 409 unless `cancel_at_period_end` | — | `PremiumStatusOut` |
| `POST /families/{id}/premium/portal` | membership + `require_parent_role` + `user.id == subscription.owner_user_id` (else 403) | — | `{"portal_url": str}` |
| `POST /families/{id}/premium/sync` | `get_active_membership` (any member — every fact is re-read live from Stripe, so this is safe; the gifter may be a supporter) | `{"session_id": str \| None}` | `PremiumStatusOut` |

```python
class PremiumCheckoutIn(BaseModel):
    plan: Literal["monthly", "annual"]

class GiftCheckoutIn(BaseModel):
    message: str | None = Field(default=None, max_length=500)

class CheckoutSessionOut(BaseModel):
    checkout_url: str          # browser navigates here (Stripe-hosted, or the
                               # success URL directly on the local backend)

class PremiumSubscriptionOut(BaseModel):
    plan: Literal["monthly", "annual"]
    status: Literal["active", "past_due", "canceled"]
    current_period_end: datetime
    cancel_at_period_end: bool
    owner_name: str
    is_owner: bool             # viewer == owner (enables the Portal button)

class PremiumGrantOut(BaseModel):
    gifter_name: str
    starts_at: datetime
    ends_at: datetime
    message: str | None

class PremiumStatusOut(BaseModel):
    plan: Literal["free", "premium"]
    premium_until: datetime | None
    capabilities: list[str]
    can_manage: bool                              # viewer is an active parent
    can_gift: bool                                # viewer is an active non-parent
    subscription: PremiumSubscriptionOut | None   # PARENTS ONLY (billing trouble is private); null for everyone else
    grants: list[PremiumGrantOut]                 # non-supporter members; [] for supporters
```

Endpoint behavior details:

- **checkout**: 409 `{"code": "already_premium"}` if a non-canceled `family_subscriptions` row exists ("Your family is already on Premium"). Gift coverage does **not** block subscribing (a family may want auto-renew alongside a gift). Creates/reuses the parent's Stripe customer, then a Checkout Session (§5.2). Stripe idempotency key `fr-premium-sub-{family_id}-{plan}-{yyyymmddHH}` so double-clicks reuse one session.
- **gift-checkout**: writes the `premium_gift_intents` row in the same transaction as session creation. If the family is already premium, still allowed (the UI shows the "extends" notice using `plan`/`premium_until` from GET).
- **cancel / resume**: calls `provider.set_cancel_at_period_end(sub_id, True|False)`, then mirrors the returned live state immediately (optimistic) — the `customer.subscription.updated` webhook re-confirms. `cancel` also sends the "Cancellation confirmed" email (this email is action-triggered, not webhook-triggered). Local backend: provider call is a no-op; the router flips the mirror row directly.
- **sync**: reconcile-on-read. With `session_id`: `provider.checkout_result(session_id)`, verify `metadata.family_id == {id}`, then settle through the same functions as the webhook (§6). Without: re-fetch the family's live subscription state and re-mirror. Idempotent; used by success-page polling fallback and by support.

---

## 5. Stripe integration

### 5.1 Why Checkout redirect (not PaymentElement)

The contribution flow uses PaymentElement because it is embedded in the 60-second north-star screen. Premium is different:

1. `mode=subscription` via PaymentElement requires hand-building subscription + incomplete-intent + confirmation plumbing; Checkout does subscription creation, SCA, tax, receipts and Link/Apple Pay/Google Pay for free.
2. Checkout keeps the card form entirely off our origin — no new PCI/regulatory surface for the recurring product, and the Billing Portal (already required for payment-method management) is the same hosted pattern.
3. It is the lowest-code path that still lands the ~4–6-tap budget (Link autofill), and dev cost stays inside the $50/month + small-team ceiling.

Trade-off accepted: a redirect off-app and back. The success page owns re-entry warmth.

### 5.2 Checkout session parameters

**Subscribe** (`mode=subscription`):

```
customer = users.stripe_customer_id (get-or-create)
line_items = [{price: settings.stripe_price_monthly | stripe_price_annual, quantity: 1}]
client_reference_id = family_id
metadata + subscription_data.metadata = {kind: "premium_subscription",
    family_id: <uuid>, owner_user_id: <uuid>, plan: "monthly"|"annual"}
success_url = {web_base_url}/family/{id}/premium/success?session_id={CHECKOUT_SESSION_ID}
cancel_url  = {web_base_url}/family/{id}/premium?canceled=1
allow_promotion_codes = false
```

**Gift** (`mode=payment`):

```
customer = gifter's stripe_customer_id (get-or-create — gives receipts + Link)
line_items = [{price: settings.stripe_price_gift_year, quantity: 1}]
metadata = {kind: "premium_gift", family_id: <uuid>, gifter_user_id: <uuid>}
success_url = {web_base_url}/family/{id}/premium/gift/success?session_id={CHECKOUT_SESSION_ID}
cancel_url  = {web_base_url}/family/{id}/premium/gift?canceled=1
```

Metadata carries **only opaque UUIDs and enum strings** — no names, no emails, no child anything, no gift message. `subscription_data.metadata` is duplicated so every `customer.subscription.*` event self-identifies without a session lookup.

### 5.3 `PaymentProvider` Protocol extensions (`apps/api/app/services/payments.py` — both impls)

```python
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
    ...existing members...

    def get_or_create_customer(
        self, *, email: str, display_name: str, user_id: str,
        existing_customer_id: str | None,
    ) -> str:
        """Return the user's Stripe customer id, creating one if needed
        (idempotency key fr-customer-{user_id}). Local: 'cus_local_{user_id}'."""

    def create_subscription_checkout(
        self, *, customer_id: str, price_id: str, metadata: dict[str, str],
        success_url: str, cancel_url: str, idempotency_scope: str,
    ) -> tuple[str, str]:
        """(session_id, redirect_url) for a mode=subscription Checkout."""

    def create_gift_checkout(
        self, *, customer_id: str, price_id: str, metadata: dict[str, str],
        success_url: str, cancel_url: str,
    ) -> tuple[str, str]:
        """(session_id, redirect_url) for a mode=payment Checkout."""

    def subscription_state(self, subscription_id: str) -> SubscriptionState | None:
        """Live retrieve; None if the subscription doesn't exist. Local: None
        (the local backend mirrors state directly in the DB)."""

    def checkout_result(self, session_id: str) -> CheckoutResult | None:
        """Live session retrieve for the /sync reconcile path."""

    def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> SubscriptionState | None:
        """Flip auto-renew; returns the resulting live state. Local: None (no-op)."""

    def cancel_subscription_now(self, subscription_id: str, *, refund_latest_charge: bool) -> None:
        """Immediate cancel + refund — ONLY for the accidental double-subscribe
        guard (§7.3). Never used by the user-facing cancel flow."""

    def create_billing_portal(self, customer_id: str, *, return_url: str) -> str:
        """Hosted Billing Portal URL. Local: '{return_url}?portal=simulated'."""
```

`LocalPaymentProvider` returns synthetic ids (`cs_local_…`, `sub_local_…`); `create_subscription_checkout`/`create_gift_checkout` return `(session_id, success_url)` — and the **router**, when `provider.settles_via_webhook` is `False`, immediately invokes the same settlement functions (§6) before returning, so dev/tests exercise the exact production code path and the success page finds Premium already live. Simulated `SubscriptionState` isn't needed: in local mode the routers mutate the mirror row through the settlement helpers directly.

### 5.4 Webhook events (existing `POST /webhooks/stripe`, same signing secret, `apps/api/app/routers/webhooks.py`)

Add to the dispatch (keep the existing `payment_intent.*` block untouched):

| Event | Handling (all idempotent) |
|---|---|
| `checkout.session.completed` | Dispatch on `metadata.kind`. `premium_subscription` → re-fetch `subscription_state(session.subscription)` and call `apply_subscription_state` with `family_id`/`owner_user_id` from metadata. `premium_gift` → verify `payment_status == "paid"` and line-item price == `stripe_price_gift_year` (signed payload is trusted for this immutable one-time fact), call `apply_gift_paid`. Any other/missing kind (contribution flow uses PaymentIntents, not Checkout) → ack. |
| `customer.subscription.updated` | Re-fetch live state → `apply_subscription_state`. Creates the mirror row if `checkout.session.completed` was lost (metadata self-identifies the family). |
| `customer.subscription.deleted` | Re-fetch (or map payload → `canceled` when retrieve 404s) → `apply_subscription_state`; triggers the downgrade email path if entitlement actually lapsed (a live grant suppresses it). |
| `invoice.paid` | Trigger-only: re-fetch the subscription and re-mirror (covers renewals; new period_end usually also arrives via `subscription.updated`). |
| `invoice.payment_failed` | Re-fetch → mirror `past_due`; **owner-only** "we'll retry automatically" email, deduped per invoice id via `premium_email_log`. |
| `invoice.upcoming` | Annual plans only → renewal-reminder email to the owner, deduped on `{subscription_id}:{period_end}`. No DB mirror change. |

Unknown subscription ids that carry no `kind=premium_subscription` metadata are acked and ignored (another product on the same Stripe account). Handlers never write from payload state where a live re-fetch is specified — **ordering becomes irrelevant because every handler converges the mirror to live truth**.

---

## 6. Settlement service — `apps/api/app/services/premium.py` (new)

The ONLY writers of `family_subscriptions`/`premium_grants`. Called from: webhook handlers, `/sync`, the local-backend routers, and the admin reconcile command. Mirrors the `settle_contribution` discipline (status guard + unique-key idempotency + feed + email in one place).

```python
def stripe_status_to_ours(raw: str) -> SubscriptionStatus | None:
    # active|trialing → active · past_due → past_due
    # canceled|unpaid|incomplete_expired → canceled · incomplete → None (ignore)

def plan_for_price(price_id: str) -> SubscriptionPlan:  # via settings price ids

def apply_subscription_state(
    db, state: SubscriptionState, *,
    family_id: uuid.UUID | None = None,        # from metadata when the row may not exist yet
    owner_user_id: uuid.UUID | None = None,
) -> FamilySubscription | None:
    """Upsert the mirror row keyed on stripe_subscription_id, converging to
    `state`. On FIRST creation of a row for a not-previously-premium family:
    emit feed_events.premium_activated + 'Premium activated' email to all
    active parents (exactly once — creation is the idempotency gate).
    On transition to canceled: run _maybe_premium_ended(db, family).
    Enforces the double-subscribe guard (§7.3) before insert."""

def apply_gift_paid(
    db, *, session_id: str, payment_intent_id: str | None,
    amount_cents: int, currency: str,
    family_id: uuid.UUID, gifter_user_id: uuid.UUID,
) -> PremiumGrant | None:
    """Idempotent on the unique stripe_checkout_session_id (return existing on
    replay). Locks the family's grant chain (SELECT existing grants FOR UPDATE
    of the family row) then:
        starts_at = max(utcnow(), max(unvoided grants' ends_at))
        ends_at   = starts_at + timedelta(days=settings.premium_grant_days)
    Joins premium_gift_intents on session_id for the message. Emits
    feed_events.premium_gifted; emails the gifter (receipt: amount, family,
    coverage dates) and all active parents (message + combined end date;
    mentions the ride-the-gift option when a subscription is active)."""

def handle_invoice_payment_failed(db, *, subscription_id: str, invoice_id: str) -> None
def handle_invoice_upcoming(db, *, subscription_id: str, period_end: datetime) -> None

def handle_owner_departure(db, family_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Called from the member-removal / leave / account-deletion paths when the
    departing user owns the family's live subscription: set cancel_at_period_end
    at Stripe (best-effort; failures logged for admin reconcile), mirror, and
    email remaining parents ('Premium until {date} — resubscribe anytime')."""

def run_lazy_lifecycle(db, family_id: uuid.UUID) -> None:
    """Request-driven replacement for a cron (§10.4): gift_ending_soon and
    grant-lapse premium_ended emails, guarded by premium_email_log."""

def reconcile_family_premium(db, family_id: uuid.UUID) -> str:
    """Admin path: re-fetch live subscription state and re-mirror; exposed as a
    management command + admin router action (precedent: reconcile_contribution)."""
```

Feed payloads (no amounts on the feed — "a year of Premium" is the unit of love):

- `premium_activated`: `{family_name, plan}` — actor = subscribing parent.
- `premium_gifted`: `{gifter_name, message, months: 12, premium_until}` — actor = gifter. Visible family-wide like all feed events; contains no billing internals.

Premium emails are **transactional** (not preference-gated — a payment failure must reach the owner) and sent directly via `get_email_sender()` + `render_email` to the computed audience, not through `notify_members` (whose audience is "all non-supporter members with a pref", the wrong shape for owner-only/parents-only sends).

---

## 7. Failure & edge handling

### 7.1 Webhook ordering / duplication
Subscription handlers converge to live-fetched state → replays and reordering are harmless. Gift handler is insert-or-return on the unique session id. Feed events/emails ride row-creation, so they fire exactly once. Every handler commits and returns 200 even for "not ours" events (never make Stripe retry what we've chosen to skip).

### 7.2 Checkout completed, webhook delayed
Success page polls `GET /families/{id}/premium` every 2s (~60s budget) showing "Finishing up — this takes a few seconds". After ~6s still-free, it calls `POST .../premium/sync {session_id}` once, which settles from a live session retrieve through the same functions. Entirely request-driven; no state machine on the client.

### 7.3 Concurrent double-subscribe
Three layers: (1) pre-checkout 409 when a live row exists; (2) partial unique index `uq_family_subscriptions_live`; (3) webhook-time guard in `apply_subscription_state` — on IntegrityError/pre-check hit with a *different* subscription id, call `provider.cancel_subscription_now(new_sub_id, refund_latest_charge=True)` and email that parent an apology ("you weren't charged twice"). No double billing survives all three.

### 7.4 Owner leaves / is removed / deletes account
`handle_owner_departure` (in `services/premium.py`) is the hook for this: when the departing user owns the family's live subscription it sets `cancel_at_period_end` at Stripe (best-effort inside the request; on failure we log and the row stays visibly wrong for `reconcile_family_premium`) and emails the remaining parents. Grants are untouched when the gifter leaves (prepaid; feed event remains).

> **⚠️ KNOWN GAP (not yet wired) — consumer-protection follow-up.** The hook is **implemented and unit-tested**, but it has **no production caller**: FutureRoots has no member-removal, leave-family, or account-deletion endpoints today, so nothing invokes `handle_owner_departure`. **Consequence:** if the subscription owner stops using the product without cancelling from the Plan settings, they keep being billed at renewal even though they've effectively left. Until those membership-lifecycle endpoints exist and call this hook, the only ways a departing owner stops billing are (a) cancelling themselves in the app or Billing Portal, or (b) an admin reconcile after support contact. Wiring the hook is a required follow-up when the removal/leave/deletion endpoints land.

### 7.5 Grant stacking clock math
Computed server-side under a row lock on the family (`SELECT id FROM families WHERE id=:f FOR UPDATE` scoped to the settlement transaction): `starts_at = max(now, latest unvoided ends_at)`, `ends_at = starts_at + 365d`. Grants therefore never overlap each other; they *may* overlap subscription coverage by design (spec: the gift-received email notes the ride-the-gift option). All math in UTC tz-aware datetimes.

### 7.6 `past_due` grace
Derived entitlement treats `past_due` as premium with no time bound — Stripe's Smart Retries window is the grace period and Stripe always terminates it with a final webhook. No custom dunning clock on our side.

### 7.7 Missed webhooks / drift
`/sync` (user-reachable, safe), `reconcile_family_premium` (admin), and the 72-hour active-slack together bound the damage of any lost event. The Stripe dashboard's event-resend also just works because handlers are idempotent.

### 7.8 Refund/chargeback on a gift
Manual support path: admin voids the grant (`voided_at`/`voided_by_user_id` — the one permitted mutation) after refunding in the Stripe dashboard. Chargeback on a subscription: Stripe cancels → normal downgrade path.

---

## 8. Web integration (`apps/web`)

### 8.1 API client — `apps/web/src/lib/api.ts`
- Extend `FamilySummary` (L22) with `plan: "free" | "premium"`; extend the family-detail type with `plan`, `premium_until`, `capabilities`.
- New types mirroring §4.2 (`PremiumStatus`, `PremiumSubscription`, `PremiumGrant`) and functions: `getPremiumStatus(familyId)`, `createPremiumCheckout(familyId, plan)`, `createGiftCheckout(familyId, message?)`, `cancelPremium(familyId)`, `resumePremium(familyId)`, `createBillingPortal(familyId)`, `syncPremium(familyId, sessionId?)`.
- Error helper: `isPremiumRequired(err): err is ApiError & {capability: string}` — matches status 402 + `detail.code === "premium_required"`. Callers of gated actions catch it and open the upsell instead of a toast.

### 8.2 Components — `apps/web/src/components/premium/`
- `PremiumPill.tsx` — small amber "Premium" pill (shared visual language for gating affordances and the families-list badge; "Free" variant is the quiet neutral pill). No lock icons.
- `PremiumUpsell.tsx` — the single shared modal/inline card. Props: `familyId`, `capability`, `role` (from family payload). Parent → "Upgrade to Premium" (links `/family/[id]/premium`) + "Maybe later"; non-parent → "Gift Premium to the family" (links `/family/[id]/premium/gift`) + "Ask a parent" (copy only, no send). Copy per capability from a small map; all strings through brand-guardian review.
- `PlanSection.tsx` — family settings block: current plan, `premium_until`, cancel/resume with confirm dialog showing the exact end date, Portal button when `is_owner`, grants list, Upgrade (parents on Free) / Gift (non-parents on Free) entries.

### 8.3 Pages — `apps/web/src/app/family/[id]/premium/`
- `page.tsx` — plan picker: Annual preselected, "Save $20.88 — about 2 months free"; POSTs checkout and `window.location.assign(checkout_url)`. Handles `?canceled=1` with the no-pressure copy. Price strings are static marketing copy (the app never computes prices; Stripe Prices are the money truth).
- `success/page.tsx` — poll → `sync` fallback → warm confirmation with links to Moments and Video Call. (Client component; `useParams()`/`useSearchParams` with the required Suspense boundary — Next 15 pin.)
- `gift/page.tsx` — gift screen with message field (≤500 chars) and the "extends their Premium" notice when `plan === "premium"`.
- `gift/success/page.tsx` — "Your gift is on its way to the family feed ♥", same poll/sync pattern.

### 8.4 Wiring the gates
- Families list (home): render `PremiumPill` per card from `plan`; badge tap → parent+free: `/family/[id]/premium`, else the Plan section anchor.
- Moments + vault memory form: when a selected/dropped file is `video/*` and family `capabilities` lacks `video_upload`, swap the form to the inline `PremiumUpsell` (nothing uploads). Also catch 402 from the ticket call as backstop.
- Video-call UI: pill on Start/Join/Schedule for free families → upsell modal; catch 402 from `join`/`planned` as backstop.
- Feed: renderers for `premium_activated` / `premium_gifted` (gift message quoted, gifter attributed warmly).

Frontend can build against this contract immediately: the local backend settles synchronously, so `npm run dev` + local API yields real end-to-end behavior without Stripe keys.

---

## 9. Config, env, infra

### 9.1 `apps/api/app/config.py`

```python
# Premium (family subscription). Prices are Stripe Price ids — amounts live in
# Stripe, never as floats in code. Empty ids ⇒ premium checkout 503s in stripe
# mode ("Premium isn't set up yet") so the feature stays dark, never broken.
stripe_price_monthly: str = ""      # $9.99/mo recurring
stripe_price_annual: str = ""       # $99/yr recurring
stripe_price_gift_year: str = ""    # $99 one-time (12-month gift)
premium_grant_days: int = 365
premium_gift_amount_cents: int = 9900   # local-backend simulation + display only
```

No new webhook secret — Premium events arrive on the existing account-level endpoint/secret.

### 9.2 CDK — `infra/lib/futureroots-stack.ts` (env block L128-146)

```ts
FUTUREROOTS_STRIPE_PRICE_MONTHLY: process.env.STRIPE_PRICE_MONTHLY ?? "",
FUTUREROOTS_STRIPE_PRICE_ANNUAL: process.env.STRIPE_PRICE_ANNUAL ?? "",
FUTUREROOTS_STRIPE_PRICE_GIFT_YEAR: process.env.STRIPE_PRICE_GIFT_YEAR ?? "",
```

Amplify: **no changes** — Checkout is a redirect; no publishable-key usage is added (the existing `NEXT_PUBLIC` key for contributions is untouched). No new AWS resources; cost impact ≈ $0 (well inside the ceiling).

### 9.3 Stripe dashboard setup (one-time, live + test mode)

1. Product **"FutureRoots Premium"** → recurring Prices: $9.99/month, $99/year (USD). Product **"FutureRoots Premium — one-year gift"** → one-time Price $99. Record the three price ids into env.
2. Existing webhook endpoint `https://api.futureroots.app/webhooks/stripe`: add events `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `invoice.upcoming`.
3. Billing → Revenue recovery: **Smart Retries on**; after final retry **cancel the subscription**. Turn **off** Stripe's own customer emails (failed payment, upcoming renewal) — FutureRoots sends brand-voice equivalents.
4. Billing Portal configuration: payment-method update + invoice history **on**; cancellation and plan switching **off** (both are app-controlled).
5. Checkout: Link / Apple Pay / Google Pay enabled (defaults).

`docs/deploy.md` gets a short "Premium rollout" note in the implementation phase (env vars + dashboard checklist); SES production access remains the launch dependency for emails at scale.

---

## 10. Compliance & principles checklist

1. **Zero crypto surface** — nothing in this feature touches `AnchorService` or any chain column; no crypto terminology anywhere (billing UI, emails, receipts).
2. **COPPA-clean billing** — Stripe sees only adult customers (email + display name) and opaque UUID metadata. The gift message (free text that may name a child) stays in `premium_gift_intents`, never in Stripe. Premium changes no consent or child-access rule; video uploads still require the existing `media_storage` consent and Family Graph write rules.
3. **Money discipline** — integer cents everywhere; amounts live as Stripe Prices; `family_subscriptions` written only from verified webhooks / live-Stripe reconcile; `premium_grants` append-only (admin void is the logged exception, mirroring `contributions.refunded_cents`); premium state always derived.
4. **Serverless / Lambda-shaped** — no workers, no cron, no in-memory state that must survive a request: every side effect is inside a webhook or user request. §10.4's lazy lifecycle is the deliberate substitute for a scheduler: `run_lazy_lifecycle` runs inside `GET /families/{id}/premium` and `family_detail` (not the list endpoint), with `premium_email_log`'s unique insert as the race-safe send-once guard. Known trade-off: a family nobody visits gets the "gift ending soon" email late/never — acceptable for MVP; an EventBridge-scheduled invoke of the same function is a one-line hardening item if it ever matters. All other lifecycle emails are webhook- or action-triggered.
5. **Private by design** — plan/badge/feed events exist only inside family-scoped payloads; billing detail (`subscription` block) only for parents; payment-failure email only to the owner.
6. **Cost** — no new infra; Stripe fees only on real revenue.

---

## 11. Implementation plan

Contract-first: §4.2 is frozen — frontend builds against it from day one (local backend settles synchronously, so no mocks needed once B1–B4 land; before that the web team can stub `getPremiumStatus` locally).

### (a) Backend (`backend-engineer`)

1. **B1 — Schema + models.** New enums, `users.stripe_customer_id`, four tables (§1) in `apps/api/app/models.py`; Alembic migration off `b7d3e91c4f20` (`uv run alembic revision --autogenerate`), hand-check the partial unique index. Feed enum values are free (non-native enums).
2. **B2 — Entitlements service** (`app/services/entitlements.py`, §3) + unit tests for the derivation math (active/past_due/slack/grants/voided/stacked).
3. **B3 — Gating call sites** (§3.1) in `vault.py`, `legacy.py`, `calls.py` + 402 tests per endpoint (free vs premium family fixtures).
4. **B4 — Premium router + schemas** (§4) with `require_parent_role` in `deps.py`; local-backend synchronous settle; family payload additions (`FamilySummary.plan`, `FamilyDetail` fields) with the batch query. Tests: role matrix, already-premium 409, parent-hits-gift 409, local checkout end-to-end (checkout → premium → feed event → emails in outbox).
5. **B5 — Provider extensions** (§5.3) in `services/payments.py`, both impls.
6. **B6 — Settlement service** (`app/services/premium.py`, §6) incl. emails + feed events + double-subscribe guard + owner-departure hook. **Status correction:** the `handle_owner_departure` hook is implemented and unit-tested, but it is **NOT** wired into any removal/deletion path — those endpoints (member-removal, leave-family, account-deletion) do not exist in the codebase yet, so there is nothing to wire it into. See §7.4's known-gap note: this is a tracked consumer-protection follow-up (a departed owner keeps being billed until they self-cancel), to be completed when the membership-lifecycle endpoints are built.
7. **B7 — Webhook handlers** (§5.4) in `routers/webhooks.py` + tests copied from the `tests/test_stripe_webhook.py` signed harness: replay idempotency, out-of-order updated-before-completed, gift replay, payment_failed dedupe, double-subscribe webhook guard.
8. **B8 — Reconcile + admin**: `reconcile_family_premium` management command + admin router action; gift-intent prune in the admin sweep; `run_lazy_lifecycle` + tests.

Dependencies: B1 → everything; B2 → B3/B4; B5 → B4(stripe mode)/B6 → B7. B3 can run parallel to B4/B5.

### (b) Frontend (`frontend-engineer`) — parallel after the contract, real data after B4

1. **F1** — `api.ts` types/functions + `isPremiumRequired` helper.
2. **F2** — `PremiumPill`, `PremiumUpsell`, families-list badge wiring.
3. **F3** — Plan picker + success page (poll → sync) + cancel-return state.
4. **F4** — Gift page + gift success page.
5. **F5** — `PlanSection` in family settings (cancel/resume/portal/grants).
6. **F6** — Gate wiring: moments/vault video-file interception, video-call pills + modal, 402 backstops; feed renderers for the two new event types.
7. **F7** — Copy pass through brand-guardian (all upsell/billing/email-adjacent strings).

### (c) Infra/config (`infra` — small, do last before rollout)

1. **I1** — Stripe test-mode products/prices + webhook events (§9.3); `.env` price ids; end-to-end test with Stripe CLI (`stripe listen --forward-to localhost:8000/webhooks/stripe`).
2. **I2** — CDK env additions (§9.2), deploy; live-mode products/prices + webhook events; verify with a real $9.99 checkout + cancel.
3. **I3** — Billing Portal + revenue-recovery dashboard config; `docs/deploy.md` runbook note.

Definition of done: spec acceptance criteria in `docs/specs/premium.md` §3–§8 all pass; `uv run pytest` green; `npm run build` green; a free family sees zero premium messaging outside gated actions.
