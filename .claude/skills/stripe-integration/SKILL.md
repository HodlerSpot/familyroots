---
name: stripe-integration
description: Authoritative reference for FutureRoots' Stripe money layer — the PaymentProvider abstraction, Future Fund contributions via Connect destination charges, Premium subscriptions and gifts, webhook settlement, and the entitlement gate. Use when touching payments, contributions, funds, Connect onboarding, Premium/subscriptions/gifting, Stripe webhooks, billing, refunds, or any code under apps/api/app/services/payments.py, premium.py, entitlements.py, or routers/{webhooks,premium,funds,contributions}.py. Read this BEFORE changing any money path so you preserve the money-discipline and webhook-as-source-of-truth invariants.
---

# FutureRoots — Stripe Integration

FutureRoots handles money through **one abstraction** (`PaymentProvider`) with two implementations — a keyless **local** provider for dev/tests and a live **Stripe** provider. Two independent money flows ride on it:

1. **Future Fund contributions** — a relative contributes to a child's fund; funds route to the child's **Stripe Connect** account as a **destination charge** (platform is merchant of record, takes an app fee).
2. **FutureRoots Premium** — a family-level paid membership ($9.99/mo or $99/yr) via **Stripe Checkout subscriptions**, plus one-time **$99 gift** grants; Premium unlocks **entitlement-gated** capabilities (video upload, family video call).

> This is a **family platform, not a crypto product.** Never surface wallets/gas/tokens/Web3 to users. Stripe is the payment rail; Base is invisible.

## The non-negotiable invariants (break these and you break the product)

1. **Money is integer cents + a currency.** Never floats. Amounts live in Stripe (Prices), never hardcoded as dollars in code.
2. **Webhooks are the source of truth in Stripe mode.** The Stripe provider **never settles synchronously** — `settle_contribution`, `apply_subscription_state`, and `apply_gift_paid` are reached only from the signature-verified webhook (or the equally-guarded reconcile paths). `StripePaymentProvider.confirm_payment` raises `NotImplementedError` by design.
3. **The future-fund ledger is append-only.** `FundLedgerEntry` rows are never mutated or deleted. Refunds add a compensating **negative `adjustment`** entry; balances are always **derived** (`SUM(amount_cents)`), never stored.
4. **Premium status is derived, never stored.** There is no `is_premium` boolean. It is computed from `family_subscriptions` + `premium_grants` every time (see `entitlements.py`).
5. **No child data ever reaches Stripe.** Customer records are adults only. Metadata carries **opaque UUIDs + a `kind` string** — never a child's name, never the free-text gift message (that stays in `premium_gift_intents`).
6. **Idempotency everywhere.** Every settlement path is safe to replay: unique DB constraints + status guards, not "hope the event arrives once."

## Provider selection

`apps/api/app/services/payments.py` builds a **module-level singleton** at import:

```python
def _build_provider() -> PaymentProvider:
    if settings.payment_backend == "stripe":
        return StripePaymentProvider(settings.stripe_secret_key)
    return LocalPaymentProvider()

_provider = _build_provider()
def get_payment_provider() -> PaymentProvider: return _provider
```

`settings.payment_backend` is `"local"` (default; dev + all tests, no keys needed) or `"stripe"` (prod Lambda). Always obtain the provider via `get_payment_provider()` — never instantiate directly. Tests monkeypatch `payments._provider` when they need to simulate live state.

The distinguishing attribute is **`settles_via_webhook: bool`** — `False` for local, `True` for Stripe. Routers branch on `provider.settles_via_webhook` to decide whether to settle inline (local) or wait for a webhook (Stripe). This is *the* mechanism that lets the whole product run end-to-end locally with no Stripe account.

## The `PaymentProvider` contract

Full signatures live in `payments.py` (Protocol at ~L99). Grouped by flow:

**Contributions / Connect**
- `create_payment(contribution, *, destination_account=None) -> (provider_payment_id, client_secret|None)` — starts a PaymentIntent; with `destination_account`, a destination charge (funds net of app fee route to the child's account).
- `confirm_payment(contribution) -> bool` — **local only**; Stripe raises `NotImplementedError`.
- `refund_payment(contribution, amount_cents) -> bool`
- `payment_status(contribution) -> str|None` — live status for reconcile.
- `payment_routing(contribution) -> (destination, application_fee)|None` — live routing to verify against the DB; `None` = nothing to verify (local).
- `create_connect_account(*, email, metadata, idempotency_scope) -> account_id` — child's Express account, owned by the parent.
- `create_account_link(account_id, *, return_url, refresh_url) -> url` — single-use hosted onboarding; never stored.
- `connect_account_state(account_id) -> ConnectAccountState` — live, never from a payload.

**Premium**
- `get_or_create_customer(*, email, display_name, user_id, existing_customer_id) -> customer_id` — one adult customer per user; idempotency key `fr-customer-{user_id}`.
- `create_subscription_checkout(*, customer_id, price_id, metadata, success_url, cancel_url, idempotency_scope) -> (session_id, url)` — `mode=subscription`.
- `create_gift_checkout(*, customer_id, price_id, metadata, success_url, cancel_url) -> (session_id, url)` — `mode=payment`.
- `subscription_state(subscription_id) -> SubscriptionState|None` — live retrieve (local `None`).
- `checkout_result(session_id) -> CheckoutResult|None` — live session retrieve, backs `/sync`.
- `set_cancel_at_period_end(subscription_id, cancel) -> SubscriptionState|None` — the **only** user-facing cancel/resume mechanism.
- `cancel_subscription_now(subscription_id, *, refund_latest_charge) -> None` — immediate cancel+refund; used **only** by the double-subscribe guard, never by a user action.
- `create_billing_portal(customer_id, *, return_url) -> url`

**Return dataclasses** (all frozen): `ConnectAccountState` (details_submitted, charges_enabled, payouts_enabled, transfers_active, requirements_due), `SubscriptionState` (subscription_id, customer_id, status, price_id, current_period_end, cancel_at_period_end, metadata), `CheckoutResult` (session_id, kind, paid, subscription_id, payment_intent_id, amount_total, currency, price_id, metadata).

### How the local provider simulates Stripe

Local premium methods are stubs that **do not retrieve live state** (there is none). Instead:
- `create_subscription_checkout` / `create_gift_checkout` synthesize a `cs_local_{uuid}` session id and splice it into the `success_url`'s `{CHECKOUT_SESSION_ID}` placeholder.
- The **router** then calls the same settlement functions the webhook would (`apply_subscription_state` with a synthesized active `SubscriptionState`, or `apply_gift_paid`) **synchronously in the same request**.

So local dev exercises the real settlement code — only the transport (inline call vs webhook) differs. When editing settlement logic, you are editing the path both modes use.

## Settlement functions — the sole writers

**Contributions:** `settle_contribution(db, contribution) -> FundLedgerEntry` (payments.py) is the one path that writes a fund ledger entry. Reached only after verified success (local `confirm_payment`, or the webhook after `_destination_verified`). Writes one `FundLedgerEntry` (amount = gross − fee), idempotent via the unique `source_contribution_id`, emits a feed event, emails parents (except the contributor).

**Premium:** `apps/api/app/services/premium.py` holds the **only** writers of `family_subscriptions` and `premium_grants`:
- `apply_subscription_state(db, state, *, family_id=None, owner_user_id=None)` — upsert keyed on `stripe_subscription_id`, converging to live `state`. First creation for a not-already-premium family → activation feed event + email (exactly once). Enforces the double-subscribe guard before insert; catches the partial-unique-index `IntegrityError` as the race backstop. Transition to `canceled` → `_maybe_premium_ended`.
- `apply_gift_paid(db, *, session_id, payment_intent_id, amount_cents, currency, family_id, gifter_user_id)` — idempotent on unique `stripe_checkout_session_id`. Row-locks the `Family` to serialize concurrent gifts. Stacks: `starts_at = max(now, latest unvoided grant ends_at)`, `ends_at = starts_at + premium_grant_days`. Joins the gift message from `premium_gift_intents`. Feed event + gifter/parent emails.
- `handle_invoice_payment_failed` / `handle_invoice_upcoming` — re-mirror live state, email (owner only), deduped per invoice / per period.
- `handle_owner_departure(db, family_id, user_id)` — best-effort `cancel_at_period_end` when the subscription owner leaves. **Currently implemented + tested but has no caller** (no member-removal/account-deletion endpoints exist yet — wire it there when they land).
- `run_lazy_lifecycle(db, family_id)` — the **no-cron** substitute: runs inside `GET .../premium` and family detail; sends "gift ending soon" / "premium ended" for gift-only coverage Stripe gives no webhook for. Deduped via `premium_email_log`.
- `reconcile_family_premium(db, family_id)` — admin reconcile; re-fetches live state and re-mirrors (not a settlement bypass — same verification discipline).

## Webhooks — `apps/api/app/routers/webhooks.py`

Two endpoints, two signing secrets. Both verify via `_verified_event(payload, signature, secret)` (`stripe.Webhook.construct_event`, 400 on bad signature).

**`POST /webhooks/stripe`** (secret `stripe_webhook_secret`) handles:

| Event | Handling | Idempotency |
|---|---|---|
| `payment_intent.succeeded` | Find contribution by `provider_payment_id`; if not settled, `_destination_verified` (destination + app fee must match the DB's current fund account; legacy no-transfer carve-out), then `settle_contribution`. | status guard + ledger unique constraint |
| `payment_intent.payment_failed` / `.canceled` | Mark a `pending` contribution `failed`. | status guard |
| `checkout.session.completed` (`kind=premium_subscription`) | **Re-fetch live** `subscription_state`, then `apply_subscription_state`. Never trusts the session payload. | upsert on `stripe_subscription_id` |
| `checkout.session.completed` (`kind=premium_gift`) | **Trusts the signed payload** (a completed one-time payment is immutable). Verifies `payment_status=="paid"`, UUIDs parse, `amount_total == premium_gift_amount_cents`, `currency=="usd"`, `_livemode_ok`. Then `apply_gift_paid`. | unique `stripe_checkout_session_id` |
| `customer.subscription.updated` / `.deleted` | `_mirror_live_subscription` (re-fetch; on 404 synthesize a `canceled` state from payload). | upsert on subscription id |
| `invoice.paid` | Re-mirror (covers renewals). | upsert |
| `invoice.payment_failed` | `handle_invoice_payment_failed`. | `premium_email_log` per `invoice_id` |
| `invoice.upcoming` | `handle_invoice_upcoming`. | `premium_email_log` per `sub:period_end` |

**Trust model** (memorize this): subscription state is **always re-fetched live** so event ordering is irrelevant. The **one** place that trusts a signed payload is the gift path — compensated by the amount/currency/livemode checks and session-id idempotency. Every branch commits and acks `{"received": True}`, even "not ours" events, so Stripe never retries something deliberately skipped.

**`POST /webhooks/stripe-connect`** (separate secret `stripe_connect_webhook_secret`; 503 if unconfigured) handles `account.updated` only: re-fetch `connect_account_state` live (never trust the body) → `sync_fund_account_state`. Connect events arrive **only** on this endpoint, not the main one.

## Entitlements — `apps/api/app/services/entitlements.py`

The gate. No stored flag; everything derived.

- `Capability` enum: `video_upload`, `family_video_call`. `PREMIUM_CAPABILITIES` = all of them (every capability currently requires Premium).
- Derivation (a family is Premium iff):
  - a `family_subscriptions` row with `status='past_due'` **OR** (`status='active'` AND `now < current_period_end + 72h slack`), **OR**
  - an unvoided `premium_grants` row with `starts_at <= now < ends_at`.
  - `past_due` entitles unconditionally (Stripe Smart Retries *is* the grace period and always terminates via webhook). The 72h `ACTIVE_SLACK` covers a late renewal webhook. The displayed `premium_until` never includes the slack.
- `require_capability(db, family_id, capability)` — **the enforcement call**. Raises `HTTPException(402, detail={"code": "premium_required", "capability": ..., "message": ...})`. Call sites: `routers/calls.py` (video call, before minting the Agora token), `routers/vault.py` and `routers/legacy.py` (video upload, keyed off content_type). To gate a **new** premium feature, add a `Capability` and a `require_capability` call at the server choke point — do not invent a parallel check.
- `plans_for_families(db, family_ids) -> {uuid: bool}` — batch helper; use it (not per-family calls) anywhere you list families, to avoid N+1.

## Premium HTTP API — `apps/api/app/routers/premium.py`

Prefix `/families/{family_id}/premium`. All require an active membership first (`get_active_membership`).

| Endpoint | Auth beyond membership | Notes |
|---|---|---|
| `GET ""` → `PremiumStatusOut` | any member | runs `run_lazy_lifecycle` first; hides `subscription` block from non-parents |
| `POST /checkout` {plan} → `CheckoutSessionOut` | `require_parent_role` | `409 already_premium` if live sub exists; `503` if price id empty in Stripe mode |
| `POST /gift-checkout` {message?≤500} → `CheckoutSessionOut` | rejects parents (`409 use_subscribe`) | any active non-parent incl. supporters; message staged in `premium_gift_intents`, never sent to Stripe |
| `POST /cancel` → `PremiumStatusOut` | `require_parent_role` (any parent) | `set_cancel_at_period_end(True)`; `409` if no live sub |
| `POST /resume` → `PremiumStatusOut` | `require_parent_role` | `409` if no pending cancellation |
| `POST /portal` → `PremiumPortalOut` | `require_parent_role` **and owner-only** | `403` if caller isn't `owner_user_id` |
| `POST /sync` {session_id?} → `PremiumStatusOut` | any member | re-derives from live Stripe; `404` if session's `family_id` metadata ≠ path family. Backs success-page polling + missed-webhook recovery |

Metadata sent to Stripe: subscribe `{kind:"premium_subscription", family_id, owner_user_id, plan}`, gift `{kind:"premium_gift", family_id, gifter_user_id}` — opaque only.

## Data model (`apps/api/app/models.py`)

- `users.stripe_customer_id` — `String(64)`, **unique**, nullable, server-only (never serialized). One adult customer per user.
- `fund_accounts.stripe_account_id` — Connect account, **unique**, nullable, server-only; plus `account_status` and cached capability booleans.
- `contributions.provider_payment_id` — the PaymentIntent id (uniqueness enforced by lookup logic, not a DB constraint); `amount_cents`, `fee_cents`, `refunded_cents`.
- `family_subscriptions` — Stripe subscription mirror: `stripe_subscription_id` **unique**, `plan`, `status`, `current_period_end`, `cancel_at_period_end`, `owner_user_id`, `stripe_customer_id`. **Partial unique index `uq_family_subscriptions_live` on `family_id WHERE status != 'canceled'`** — the DB-level double-subscribe backstop.
- `premium_grants` — append-only prepaid gift: `stripe_checkout_session_id` **unique** (idempotency key), `amount_cents`, `currency`, `message`(≤500, nullable), `starts_at`/`ends_at` (`CHECK ends_at > starts_at`), `voided_at`/`voided_by_user_id` (admin-only, the single permitted mutation).
- `premium_gift_intents` — staging row holding the free-text gift `message`; `stripe_checkout_session_id` **unique**; never sent to Stripe; prunable after 30 days.
- `premium_email_log` — `UniqueConstraint(kind, dedupe_key)` — the race-safe send-once guard for every lifecycle email.

## Config (`apps/api/app/config.py`, env prefix `FUTUREROOTS_`)

`contribution_fee_bps` (290), `contribution_fee_fixed_cents` (30), `payment_backend` ("local"|"stripe"), `stripe_secret_key`, `stripe_webhook_secret`, `stripe_connect_webhook_secret`, `stripe_price_monthly`, `stripe_price_annual`, `stripe_price_gift_year`, `premium_grant_days` (365), `premium_gift_amount_cents` (9900), `web_base_url`. Empty price ids ⇒ Premium checkout **503s** in Stripe mode (feature stays dark, never crashes). In prod these are set from `infra/.env` → `FUTUREROOTS_*` Lambda env via the CDK stack (`infra/lib/futureroots-stack.ts`).

## Stripe dashboard setup (see `docs/deploy.md`)

- **Contributions:** `/webhooks/stripe` events `payment_intent.succeeded`/`payment_failed`.
- **Connect:** enable Connect + platform profile (accept destination-charge liability); Connect branding; a **second** webhook at `/webhooks/stripe-connect` with "events on Connected accounts", event `account.updated`; live-mode platform review (gates launch).
- **Premium:** create the three Prices → `STRIPE_PRICE_{MONTHLY,ANNUAL,GIFT_YEAR}`; add to the **existing** `/webhooks/stripe` endpoint the events `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`, `invoice.upcoming`; Billing Smart Retries ON + cancel after final retry; turn OFF Stripe's own customer emails (the app sends brand-voice equivalents); Billing Portal: payment-method + invoices ON, cancellation/plan-switching OFF (app-controlled); **⛔ set the `invoice.upcoming` lead time to 30 days** (California ARL requires 15–45 days for annual auto-renew — launch-blocking).
- SES production access is required for lifecycle emails at scale.

## When you change something here — checklist

- Touching a settlement path? It must stay **idempotent** and be reachable only after verified success. Add a test in `apps/api/tests/test_premium_webhooks.py` / `test_stripe_webhook.py` using the signed-event harness (`sign()` + monkeypatched secret).
- Adding a premium feature? New `Capability` + `require_capability` at the server choke point + client upsell; never a client-only check.
- New Stripe object? Metadata = opaque UUIDs + `kind` only. No child data. Free text stays in a local staging table.
- New money field? Integer cents + currency. Ledger stays append-only; balances derived.
- Verify locally first: `payment_backend=local` runs the full flow with no keys; then test-mode Stripe CLI before live.
