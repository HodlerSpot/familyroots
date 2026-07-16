# FutureRoots Premium — Family Membership (Spec)

Status: **Scoped — ready to build** · Owner: PM · Fits: post-Phase-5 monetization (vision.md business model #1: family subscription)

FutureRoots Premium is a paid membership **at the family level**: one subscription unlocks premium features for every member of that family. Pricing is fixed by the founder: **$9.99 USD/month or $99 USD/year**, recurring until cancelled. Payment runs entirely through **Stripe** (Checkout + Billing subscriptions). Non-parents can **gift** Premium to a family they belong to.

Premium-gated capabilities at launch (extensible — see Entitlements):

1. **Video upload — gated everywhere**: Child Vault (Memory form), Time Capsules, and the Legacy Archive all require Premium to attach a video. Photos, voice notes, text, milestones, contributions, and goals stay free on every surface. (Memories & Moments has no upload control of its own — see §5 for where video memory upload actually lives.)
2. **Family Video Call** (starting/joining live calls and scheduling the next call)

> **2026-07-15 founder decision:** video upload is gated via the single `video_upload` entitlement at every media choke point across the product (Child Vault, Time Capsules, Legacy Archive), not only "Memories & Moments" as an earlier draft implied. This replaces the prior narrower framing where capsules and the legacy archive were to show zero Premium messaging.

---

## Key decisions (summary)

| Question | Decision |
|---|---|
| Gift mechanics | **Prepaid period, one-time charge** — 12 months for $99, paid once by the gifter via Stripe Checkout (`mode=payment`). Not a recurring subscription in the gifter's name. |
| Can parents decline a gift? | **No decline flow.** Gifts apply immediately; parents are notified by email + feed event. A prepaid gift never converts into a charge for the parent, so there is nothing to protect them from. |
| Grace period on payment failure | Rely on **Stripe Smart Retries**. Premium stays active while the subscription is `past_due` (that retry window *is* the grace period). On final failure (`canceled`/`unpaid`) the family downgrades immediately. |
| Downgrade behavior for existing videos | **Nothing is ever deleted or hidden.** Already-uploaded videos remain viewable and downloadable forever. Only *new* video uploads and *new/joining* video calls are blocked. |
| Who can cancel | Any **active parent** of the family (not only the parent who started it), via an in-app action. Payment-method changes and invoice history go through the Stripe Billing Portal, available **only to the subscription owner**. |
| Trial | **No trial** for MVP. The free tier is the trial — the whole core product (feed, photos, contributions, goals, capsules, archive) works free. |
| Plan switching | Not in MVP. Switch = cancel (active until period end) + resubscribe on the other plan. No proration. |
| Entitlement model | A server-side **capability registry** (`entitlements` service), never hardcoded `if premium` checks at call sites. Premium state is **derived** from Stripe-webhook-written rows, never a hand-set boolean. |

---

## 1. Personas & user stories

- **Parent** — "As a parent, I want to upgrade my family to Premium in a couple of taps so we can save videos of the kids and do family video calls, and I want to see clearly what it costs, when it renews, and how to cancel."
- **Grandparent** — "As a grandparent, I want to give my daughter's family a year of Premium as a gift — I pay once, they get the features, and the family sees it was a gift from me."
- **Extended family (aunt/uncle/relative, guardian, supporter)** — "As a relative, when I hit a Premium feature I want to understand what it is and either nudge a parent or gift it myself — without feeling scolded."
- **Child** — Children are **profiles, not accounts** and never see billing. Premium changes nothing about consent or child-data access: video uploads to a child's vault still require the existing `media_storage` consent and the existing Family Graph write rules. No child data is ever sent to Stripe.

---

## 2. Entitlements & data model

### New tables (extends `docs/data-model.md`)

**family_subscriptions** — one active recurring subscription per family, mirrored from Stripe
- `id`, `family_id` → families, `owner_user_id` → users (the parent who subscribed; owns the Stripe customer), `stripe_customer_id`, `stripe_subscription_id` (unique), `plan` (`monthly | annual`), `status` (`active | past_due | canceled`), `current_period_end`, `cancel_at_period_end` (bool), `created_at`, `updated_at`
- Rows are created/updated **only** by verified Stripe webhook handlers (plus an admin reconcile path that reads live state from `subscriptions.retrieve`) — never from client say-so. Partial unique index: at most one row per family with `status != canceled`.

**premium_grants** — prepaid Premium periods (gifts), **append-only**
- `id`, `family_id`, `source` (`gift`), `granted_by_user_id` → users, `stripe_checkout_session_id` / `stripe_payment_intent_id`, `amount_cents` (integer, e.g. `9900`), `currency` (`usd`), `message` (optional, shown on the feed), `starts_at`, `ends_at`, `created_at`
- Written **only** when a verified Stripe webhook confirms payment. `starts_at = max(now, latest existing grant.ends_at)` so gifts stack, never overlap each other. No updates/deletes; corrections are support-side refunds + a compensating admin action.

### Derived premium state (money discipline: balances/entitlements are always derived)

```
premium_until(family) = max(
  current_period_end  where family_subscriptions.status in ('active','past_due'),
  max(premium_grants.ends_at)
)
family is Premium  ⇔  now < premium_until(family)
```

### Capability registry (extensibility requirement)

A single server-side module, e.g. `app/services/entitlements.py`:

```
CAPABILITIES = {
  "video_upload":      Tier.PREMIUM,
  "family_video_call": Tier.PREMIUM,
  # future premium features are one line here
}
require_capability(family_id, "video_upload")  # raises 402-style domain error
```

- Every gated API endpoint calls `require_capability`; the web app reads the same data from a `capabilities` list returned on family payloads (e.g. `GET /families` and `GET /families/{id}` gain `plan: "free" | "premium"`, `premium_until`, `capabilities: [...]`). The client uses this for affordances only; **the server check is the enforcement**.
- Gating error responses carry a machine-readable code (`premium_required`, with the capability name) so the web app can render the standard upsell, never a raw error.

### Feed events (the feed is the heartbeat)

New `feed_events.type` values:
- `premium_activated` — actor: the subscribing parent. Copy (brand voice): "The Saliga family is now on FutureRoots Premium".
- `premium_gifted` — actor: the gifter, payload includes optional gift message. Copy: "June gave the family a year of FutureRoots Premium ♥ 'For all the recital videos to come.'"
- No feed events for payment failure, cancellation, or downgrade — billing trouble is private to parents (warm brand: no wall of shame). Downgrade is communicated by email and settings state only.

Feed events are family-private like all others — Premium status is **never** visible outside the family (no public/cross-family surface).

---

## 3. Flow A — Upgrade (parent)

### Entry points

1. **Gated-feature upsell** (primary): the modal/card shown when any member hits video upload or video call (see Flow C) has "Upgrade to Premium" for parents.
2. **Family settings**: a "Plan" section on the family page management area — shows current plan (Free/Premium), and for Free families an "Upgrade" button.
3. **Families list badge** (Flow D): tapping the "Free" badge as a parent deep-links to the Plan section.

### Screens & steps (tap count — under-60-seconds discipline)

1. **Plan picker** (`/family/[id]/premium`): two cards — Monthly $9.99/mo and **Annual $99/yr, preselected, labeled "Save $20.88 — about 2 months free"**. One short benefits list (videos, family video calls, "and everything we add next"). Zero crypto/Web3 terminology, like everywhere else. *(1 tap to pick plan if changing from default)*
2. **Continue to checkout** → API `POST /families/{id}/premium/checkout` (parent-role check) creates a Stripe Checkout Session (`mode=subscription`, price = chosen plan, `client_reference_id` = family id, customer = get-or-create for this parent) and redirects. *(1 tap)*
3. **Stripe Checkout** — card/Link/Apple Pay/Google Pay. *(~2–3 taps with Link)*
4. **Return states:**
   - **Success** (`success_url` → `/family/[id]/premium/success?session_id=...`): warm confirmation ("Welcome to Premium — your family's videos start now"), buttons to Moments and Video Call. The page polls family state briefly; entitlement flips only when the `checkout.session.completed` / `invoice.paid` webhook lands (usually < 2s). If the webhook is slow, show "Finishing up — this takes a few seconds" rather than an error.
   - **Cancel** (`cancel_url` → plan picker): "No problem — everything you already love about FutureRoots stays free." No nagging, no retry pressure.

Total: ~4–6 taps end to end. Comfortably under 60 seconds.

### Reads / writes

- Reads: `families`, `family_members` (role check = `parent`, status `active`), `family_subscriptions`, `premium_grants` (to block double-subscribe, see Edge cases).
- Writes: `family_subscriptions` (webhook only), `feed_events` (`premium_activated`), `notifications` (emails, Flow F).

### Acceptance criteria

- [ ] Only an **active `parent`** member can create a subscription Checkout session; grandparent/relative/guardian/supporter and non-members get a domain error (guardians manage children, but billing is founder-fixed to parents).
- [ ] Annual plan is preselected and shows the exact savings vs. 12×monthly.
- [ ] Amounts are configured as Stripe Prices ($9.99 = `999`, $99 = `9900` — integer cents everywhere in our code); the app never computes or stores a float price.
- [ ] `family_subscriptions` rows are written only by verified (signature-checked) webhook handlers; handlers are **idempotent** (replayed events cause no duplicate rows/events/emails).
- [ ] A family with an already-active subscription cannot start a second Checkout session (server-side check, friendly message: "Your family is already on Premium").
- [ ] Success page never claims Premium before the entitlement is actually live; webhook delay shows the "finishing up" state.
- [ ] Abandoned/cancelled Checkout leaves zero DB rows and zero emails.
- [ ] `premium_activated` feed event is emitted exactly once per new subscription.
- [ ] Two parents clicking Upgrade concurrently results in exactly one active subscription (unique index + pre-Checkout check + webhook-time guard: if a second subscription completes for an already-premium family, it is auto-cancelled at Stripe with an apologetic email to that parent — no double billing).
- [ ] No user-facing string anywhere in the flow contains crypto/Web3 terminology.

---

## 4. Flow B — Gift Premium (non-parent)

### Mechanics decision: **prepaid period, not a recurring subscription**

The gift is a **one-time $99 payment for 12 months of Premium**, applied to the family as a `premium_grant`. Rationale:

- **Simplicity for MVP:** one Checkout `mode=payment` charge; no second subscription object per family, no "who owns the renewal" question, no dunning against a grandparent's card.
- **No obligation transfer:** when the gift ends, the family simply returns to Free (with a heads-up email and an easy upgrade path) — nobody is surprise-billed.
- **Emotional fit:** a gift is a bounded, generous act ("a year of Premium from Grandma"), not an open-ended financial entanglement. This mirrors how contributions already work (one-time, celebrated on the feed).
- One gift option only (12 months / $99) keeps the choice effortless. Monthly gifting adds decisions without adding love.

### Entry points

1. Gated-feature upsell shown to non-parents (Flow C): secondary button "Gift Premium to the family".
2. Family page Plan section, visible to non-parents on Free families: "Give this family a year of Premium".

### Screens & steps

1. **Gift screen** (`/family/[id]/premium/gift`): "Give the Saliga family a year of FutureRoots Premium — $99, one time." Optional gift message field ("Add a note the family will see"). If the family is already Premium, a gentle notice: "This family already has Premium — your gift will extend it by a year." *(0–1 taps)*
2. **Continue to payment** → `POST /families/{id}/premium/gift-checkout` (any active non-parent member; parents are redirected to the subscribe flow) creates Checkout `mode=payment` for `9900` cents. *(1 tap)*
3. **Stripe Checkout.** *(~2–3 taps)*
4. **Success return**: "Your gift is on its way to the family feed ♥" — and it is: webhook writes the `premium_grant`, emits `premium_gifted` (with the message), emails the parents and the gifter. **Cancel return**: back to gift screen, no guilt copy.

~4–5 taps. A grandparent completes this well under 60 seconds — same bar as contributions.

### Notification / decline policy

- Parents are **notified** (email + feed event) but there is **no accept/decline step**. The gift activates immediately. Justification: a prepaid grant can never charge the parents or auto-renew, so consent adds friction without protection. If a family genuinely wants a gift reversed, that's a manual support refund (out of scope self-serve).

### Reads / writes

- Reads: `family_members` (active membership, role ≠ parent), `family_subscriptions` + `premium_grants` (to compute the "already Premium" notice and the grant `starts_at`).
- Writes (webhook only): `premium_grants`, `feed_events` (`premium_gifted`), `notifications`.

### Acceptance criteria

- [ ] Any **active non-parent member** (grandparent, relative, guardian, supporter) can gift; non-members are denied; parents attempting the gift endpoint are pointed to subscribe instead.
- [ ] Gift is exactly one product: 12 months for `9900` cents USD, one-time charge, no saved recurring billing for the gifter.
- [ ] The `premium_grant` row is written only by a verified webhook; handler idempotent; `starts_at`/`ends_at` computed server-side (`starts_at = max(now, latest grant ends_at)`, `ends_at = starts_at + 365 days`).
- [ ] Gifting an already-Premium family is allowed **with** the extension notice shown before payment (no silent overlap surprise); the grant stacks after existing grants.
- [ ] Gift message ≤ 500 chars, rendered on the feed event and in the parents' email; empty message is fine.
- [ ] `premium_gifted` feed event emitted exactly once; gifter's name attributed warmly; message included.
- [ ] Failed/abandoned payment: no grant, no feed event, no emails.
- [ ] Supporters gifting does not widen their visibility: they still see only `visible_to_supporters` items; the gift changes entitlements, not access rules.

---

## 5. Flow C — Gating UX (free families)

Principle: **warm upsell, never a wall of shame.** Free is a full product; Premium is "more room for your family's story."

### Consistent affordance

- A single reusable **"Premium" pill** (small, gold/amber, word "Premium" — no lock icons, no greyed-out dead zones) appears next to gated actions across the app. One shared web component; one shared upsell modal.

### Video upload — every upload surface, uniformly gated

Gated surfaces (each has its own upload form; each independently enforces `video_upload`):

- **Child Vault memory form** (`/family/[id]/child/[childId]` — this is where video *memory* upload actually lives; see the Moments note below)
- **Time Capsules** (capsule creation form)
- **Legacy Archive** (archive item form)

Not an upload surface: **Memories & Moments** (`/family/[id]/moments`) is a **read-only feed view** of memories — it has no file picker of its own. It displays whatever media (including video) was uploaded via the Child Vault memory form above. There is currently no separate "add a memory from Moments" control, so there is nothing to gate there today. **Reconciliation:** an earlier draft of this spec incorrectly named Moments as a gated upload surface; that was stale. Building a dedicated upload affordance directly on the Moments page is **not required for this phase** — it's logged as a **follow-up** (if/when Moments grows its own composer, it must call `require_capability(..., "video_upload")` the same as every other surface, no exceptions).

- On every gated surface, the file picker stays available. If a free-family user selects a video file (or drags one in), the upload form swaps to an inline **upsell card**: "Videos are part of FutureRoots Premium. Photos and voice notes are always free."
  - Parent sees: **Upgrade to Premium** (→ Flow A) + "Maybe later".
  - Non-parent sees: **Gift Premium to the family** (→ Flow B) + "Ask a parent" (sends nothing automatically in MVP — it's copy guidance, not a button that emails; a nudge email is out of scope).
- The photo/audio/text/milestone path is untouched on every surface — a free user posting non-video content never sees Premium messaging, in the Child Vault, a Time Capsule, or the Legacy Archive.
- Server: every media upload ticket endpoint (Child Vault, Time Capsules, Legacy Archive) rejects `video/*` content types for free families with `premium_required` (defense in depth — client affordance is not the enforcement). This is the same `video_upload` capability check at every choke point, not three separate rules.

### Family Video Call

- The "Start a call" / "Join" / "Schedule next call" actions carry the Premium pill for free families; tapping opens the same upsell modal ("Family video calls are part of Premium — see everyone's faces, from anywhere").
- Server: all call endpoints (`start`, `join`, token mint, presence, planned calls) require the `family_video_call` capability. Supporters remain excluded from calls regardless of plan (existing rule).

### Acceptance criteria

- [ ] Video upload is gated **uniformly across all upload surfaces**: Child Vault memory form, Time Capsules, and Legacy Archive all require the `video_upload` capability; there is exactly one capability name and one enforcement path (`require_capability(family_id, "video_upload")`), never a per-surface variant.
- [ ] Photo, voice, text, milestones, contributions, goals: zero Premium messaging anywhere, on every surface, for free families — this is unchanged and still absolute.
- [ ] Time Capsules and the Legacy Archive are **no longer** exempt from Premium messaging: a free family selecting a video in a capsule or an archive item form sees the same inline upsell card as the Child Vault, not silence. (Superseded: an earlier draft of this criterion required "zero Premium messaging" for capsules and legacy archive — that was the pre-2026-07-15 scope and is no longer correct.)
- [ ] Selecting a video as a free family shows the upsell card inline on whichever surface it was selected on (Child Vault, capsule, or archive); nothing uploads; no error toast/raw 4xx ever reaches the user.
- [ ] API rejects video-type upload tickets on **all three** upload endpoints (Child Vault media, capsule media, legacy archive media) and all call endpoints for free families with the machine-readable `premium_required` code, regardless of what the client sends.
- [ ] Memories & Moments (`/family/[id]/moments`) has no upload control in this phase and therefore nothing to gate directly; it correctly renders video content that was uploaded (and gated) via the Child Vault memory form. A future Moments-native composer is out of scope for this phase and is tracked as a follow-up, with the requirement that it must enforce the same `video_upload` capability when built.
- [ ] Parent vs. non-parent see the correct primary action (Upgrade vs. Gift), consistently worded across Child Vault, capsule, and legacy-archive upsell cards.
- [ ] Premium families see no pills, no upsells — the features just work, on every surface.
- [ ] Existing videos in a downgraded family — in the Child Vault, capsules, Legacy Archive, and feed/Moments views of that media — play, download, and appear exactly as before (see Flow E). Downgrade never hides or deletes previously uploaded video anywhere.
- [ ] All upsell copy passes brand-guardian rules; no crypto terms, no shame language ("unlock" is fine, "you can't afford" tones are not); copy is consistent regardless of which surface triggered it.

---

## 6. Flow D — Badge in the families list

- The families list (home page `/`) shows a plan badge on every family card: **"Premium"** (amber/gold pill, same visual language as the gating pill) or **"Free"** (neutral/quiet pill).
- Data: `GET /families` response gains `plan: "free" | "premium"` per family (derived server-side from `premium_until`). No `premium_until` or billing detail on the list — just the badge.
- Tapping the badge: parents on a Free family → plan picker; everyone else → family page Plan section (where non-parents see the gift option).
- The badge is visible **only to that family's members** — it's on their own private list. Premium status never appears on any cross-family or public surface (there are none).

Acceptance criteria:

- [ ] Badge state matches derived entitlement (subscription **or** unexpired grant ⇒ Premium; `past_due` within retry window ⇒ still Premium).
- [ ] Badge updates without re-login after upgrade/gift/downgrade (list refetch reflects current state).
- [ ] A user in two families sees the correct badge per family.

---

## 7. Flow E — Lifecycle: dunning, cancellation, resubscribe, expiry

### Payment failure & dunning

- Stripe Billing **Smart Retries** handle retry timing; Stripe emails are **off** — FutureRoots sends its own (Flow F, brand voice).
- `invoice.payment_failed` → subscription `past_due`: **Premium stays fully active** during the retry window (this is the grace period; no additional custom grace on top). Email the owner ("We couldn't process your Premium payment — we'll retry automatically; update your card here"), with a Billing Portal link.
- Final failure (Stripe cancels: `customer.subscription.deleted` / status `unpaid`→our `canceled`): family downgrades to Free **unless an unexpired `premium_grant` still covers it**. Email owner + all parents ("Your family is back on the Free plan — every photo, video, and memory is safe").

### Downgrade behavior (decided)

- **Existing videos stay viewable and downloadable forever.** Nothing is deleted, hidden, or watermarked. New video uploads and starting/joining/scheduling calls are blocked (Flow C gating resumes).
- Scheduled `planned_calls` in the future: kept in the DB, but shown with the Premium pill and reminders are suppressed while Free.

### Cancellation

- Any active **parent** can cancel from the Plan section: one confirm dialog stating the exact end date ("Premium stays on until March 12, 2027 — after that you're on Free, and everything you've saved stays yours"). API sets `cancel_at_period_end=true` at Stripe; state mirrors back via webhook.
- Until period end: fully Premium, and a **Resume** button replaces Cancel (Stripe `cancel_at_period_end=false`) — resuming before the period end requires no new checkout.
- Subscription owner can additionally open the **Stripe Billing Portal** (payment method, invoices). Portal is configured with plan-switching and immediate-cancel disabled.

### Resubscribe (after expiry/downgrade)

- Plan section on a Free-again family shows the standard Upgrade button → Flow A creates a **new** subscription (reusing the parent's Stripe customer). A fresh `premium_activated` feed event is emitted. No proration/backdating.

### Acceptance criteria

- [ ] `past_due` families retain all capabilities; entitlement flips to Free only on terminal subscription status **and** no unexpired grant.
- [ ] Downgrade blocks new video tickets and call endpoints within one request of the webhook landing (entitlement is derived, not cached stale).
- [ ] Previously uploaded videos (vault, moments, feed, capsule media) remain fully accessible to the same people as before, on Free.
- [ ] Cancel is available to any active parent, not only the owner; it never ends Premium early; end date shown is Stripe's `current_period_end`.
- [ ] Resume before period end restores auto-renew with no new charge and no duplicate feed event.
- [ ] All state transitions are webhook-driven and idempotent; an admin reconcile command can re-sync any family's subscription from live Stripe state.
- [ ] Gift-covered family whose subscription finally fails stays Premium until the grant's `ends_at`.

---

## 8. Flow F — Email touchpoints (SES; all via existing `notifications` machinery)

| Email | To | Trigger |
|---|---|---|
| **Premium activated** | All active parents | First `invoice.paid` on a new subscription |
| **Gift confirmation** ("Your gift is live") | Gifter | Gift webhook success (doubles as receipt: amount, family name, coverage dates) |
| **Gift received** ("June gave your family a year of Premium") | All active parents | Gift webhook success (includes gift message) |
| **Payment failed** ("We'll retry automatically") | Subscription owner | First `invoice.payment_failed` per invoice (not per retry) |
| **Premium ended** ("You're on the Free plan — everything is safe") | Owner + all parents | Terminal failure or period end after cancellation, once entitlement actually lapses |
| **Cancellation confirmed** ("Premium until {date}") | Owner (+ other parents informed) | Cancel action |
| **Renewal upcoming** (annual only) | Owner | `invoice.upcoming` webhook, 7 days before annual renewal (price + date + how to cancel — good practice and legally required in several states) |
| **Gift ending soon** | All active parents | 7 days before a grant's `ends_at` when no active subscription will continue coverage ("Keep Premium going" CTA) |

Rules: every email is warm brand voice, states amounts as normal currency ("$99"), never mentions Stripe internals or any blockchain anything, and links back into the app (deep link to the Plan section). Send-once idempotency per triggering event. Note: SES is currently in sandbox — production access is a launch dependency (already on the hardening backlog).

Acceptance criteria:

- [ ] Each email fires exactly once per triggering event (webhook replay safe).
- [ ] Payment-failure emails go only to the owner (billing trouble is not broadcast to the whole family).
- [ ] Renewal reminder is sent for annual plans only, ~7 days ahead.
- [ ] No email is sent for abandoned checkouts.

---

## 9. Edge cases

| Case | Behavior |
|---|---|
| Gift attempted while family already Premium | Allowed with a pre-payment notice ("your gift extends their Premium"); grant stacks after the latest existing grant (`starts_at = max(now, latest grant ends_at)`); parents' email notes the new combined end date. Parents may choose to cancel their recurring plan and ride the gift — the gift-received email mentions this option when a subscription is active. |
| Multiple parents | Any active parent can upgrade or cancel. Exactly one active subscription per family enforced (DB partial-unique + pre-checkout check + webhook-time guard that refunds/cancels an accidental second subscription with an apology email). |
| Subscription owner leaves / is removed from the family | App sets `cancel_at_period_end=true` immediately (a person shouldn't silently keep paying for a family they're no longer in). Premium runs to period end; remaining parents get the "Premium until {date} — resubscribe anytime" email. Grants are unaffected by the gifter leaving. |
| Gifter leaves the family | Grant stands (it's prepaid); feed event remains. |
| Owner deletes account | Same as leaving: cancel at period end + parent notification. |
| Webhook arrives before the user returns from Checkout | Fine — success page reads current state. Webhook late: success page shows "finishing up" and polls briefly. |
| Refund/chargeback (`charge.refunded` / dispute) on a gift | MVP: manual support flow; admin action voids the grant (compensating end-date change via admin path, logged). No self-serve. Chargeback on subscription: Stripe cancels → normal downgrade path. |
| Currency | USD only at launch (matches founder pricing). Stripe Checkout displays USD to everyone. |
| Child profiles | Untouched. Premium confers no new access to child data; all existing Family Graph and consent rules apply identically on Free and Premium. |
| Upload in flight at downgrade moment | Ticket already issued completes (attach allowed); no new video tickets after entitlement lapses. |

---

## 10. Out of scope (MVP)

- **Trials** (free tier is the trial), coupons, promo codes, referral credits
- **Plan switching with proration** (monthly↔annual mid-cycle) — cancel + resubscribe instead
- **Self-serve refunds** or gift returns (manual support only)
- Per-seat / per-child pricing, family-size tiers
- Gift options other than 12 months / $99; gift cards / redeemable codes; gifting to families you don't belong to
- Regional pricing, VAT/sales-tax handling beyond Stripe defaults, currencies other than USD
- Mobile in-app purchases (Expo app is Phase 6+; when it lands, billing remains web-based initially)
- Automated "ask a parent to upgrade" nudge emails from non-parents
- Grandfathered/legacy pricing machinery
- Storage quotas or any limitation of existing free features (free tier is not being reduced by this spec)

---

## 11. Non-negotiables checklist

- **Zero crypto surface:** billing UI, emails, and receipts contain no Web3/crypto/blockchain terminology (nothing in this feature touches the chain at all — no `anchor_ref` involvement).
- **60-second flows:** parent upgrade ≈ 4–6 taps; grandparent gift ≈ 4–5 taps, same bar as the contribution flow.
- **Children are profiles:** no billing surface for children; no child PII to Stripe; consent rules unchanged.
- **Money discipline:** integer cents + currency everywhere; `family_subscriptions`/`premium_grants` written only from verified Stripe webhooks; `premium_grants` append-only; premium state always derived, never a stored flag.
- **Private by design:** plan status and feed events visible only inside the family; no cross-family or public surface.
- **Feed heartbeat:** `premium_activated` and `premium_gifted` feed events; billing failures deliberately excluded from the feed (privacy > completeness — flagging this as an intentional exception to "every meaningful action emits a feed event").
