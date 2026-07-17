# FutureRoots — System Architecture

Status: **live in production** (futureroots.app / api.futureroots.app). This document describes the system as built and the local-first development approach that still applies — everything runs locally with no cloud account, and the AWS deployment is configuration on top (runbook: `docs/deploy.md`).

## Guiding constraints

- **North star flow:** grandparent completes notification → congratulations → contribution → memory in under 60 seconds. Every architectural choice is judged against this.
- **Blockchain is invisible:** no wallets, seed phrases, gas, or crypto terminology anywhere in the product surface. Chain writes (Base) happen asynchronously behind a service interface and can be stubbed out entirely for MVP.
- **Cost ceiling:** ~$50/month for MVP infrastructure → AWS serverless, event-driven, on-demand compute, S3 object storage, API-based AI.
- **Children's data:** COPPA/GDPR/PIPEDA. Children are *profiles managed by guardians*, not independent accounts. Privacy by design.

## High-level shape

```
                         ┌───────────────────────────────┐
  Web (Next.js) ────────▶│   API (FastAPI + Pydantic)    │
  Mobile (later, Expo)   │                               │
                         │  auth · family graph · vault  │
                         │  feed · goals · contributions │
                         │  capsules · notifications     │
                         └───────┬───────────┬───────────┘
                                 │           │
                          PostgreSQL      S3 (media)
                                 │
                     async workers / events
                     ├─ email notifications (SES)
                     ├─ Stripe webhooks (payments)
                     ├─ time-capsule release scheduler
                     └─ chain anchor service (Base, stub in MVP)
```

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Web frontend | Next.js, TypeScript, Tailwind, ShadCN | Responsive web first; grandparents use it from any device |
| Mobile | React Native + Expo | **Deferred** until the API is stable |
| API | FastAPI + Pydantic | Single service for MVP; module-per-domain internal structure |
| Database | PostgreSQL | See `data-model.md` |
| Media storage | S3 (prod) / local directory (dev) | Presigned-URL uploads so media never flows through the API; fetches use short-lived media-scoped tokens |
| Auth | JWT issuer behind an auth abstraction (Cognito swap deferred by decision 2026-07-16) | Children never authenticate independently |
| Payments | Stripe | Connect destination charges for contributions, Checkout subscriptions/gifts for Premium; signature-verified webhooks drive all state |
| Email | SES (prod) / file outbox (dev, `apps/api/var/outbox/`) | Milestone notifications are the growth engine |
| Blockchain | Base, via an internal `AnchorService` interface | MVP implementation: no-op/stub that records intent; real chain writes later |
| AI | API-based only (Anthropic, OpenAI) | Later phase; never self-hosted models |

## Local-first development

Everything runs locally with zero cloud keys:

- PostgreSQL 16 as a native Windows service (db/role `futureroots`) — see `docs/dev.md`
- FastAPI via `uvicorn --reload`; Next.js via `next dev`
- Cloud services (SES, S3, Stripe, Secrets Manager) are hidden behind thin interfaces with local implementations: emails land in a file outbox, media in a local directory, and the local payment provider settles contributions and Premium checkout/gift synchronously through the same settlement functions the Stripe webhooks call.

## Production deployment (AWS serverless — live)

Deployed since Phase 5 (full runbook: `docs/deploy.md`):

- **Amplify Hosting** — Next.js web (futureroots.app), building from GitHub on push to `main`
- **API Gateway + Lambda** — FastAPI via Mangum (api.futureroots.app), in a VPC with fck-nat egress
- **RDS PostgreSQL 16** — the one relational store (deletion protection + RETAIN)
- **S3** — vault media, presigned upload/download
- **SES** — transactional email (sandbox until production access)
- **Secrets Manager** — one consolidated `futureroots/api` secret, loaded at Lambda cold start
- **EventBridge** — daily maintenance command (data-lifecycle sweeps); capsule release checks
- Auth is the JWT issuer (Cognito swap deferred); CloudFront+WAF in front of the API also deferred by decision 2026-07-16.

## Domain modules (API internal structure)

One FastAPI app, organized by domain so modules can be split later if needed:

- `auth` — signup/login, parental consent records, invitation flow (family members join via invite, never open registration into a family)
- `families` — family creation, membership, roles (the Family Graph)
- `children` — child profiles (managed, non-authenticating) and their vaults
- `vault` — media items, presigned uploads, achievements history, messages
- `feed` — private family timeline events; every meaningful action emits a feed event
- `goals` — achievement engine: goal definition, completion, reward triggering
- `contributions` — Stripe-backed gifts and milestone contributions; writes future-fund ledger entries
- `funds` — future fund accounts and append-only ledger (balances are derived, never stored as mutable truth)
- `capsules` — time capsules with release conditions (age/date/milestone) and a release scheduler
- `legacy` — family legacy archive (stories, recipes, documents)
- `premium` — family membership (Stripe Checkout subscriptions + prepaid gift grants) and the derived entitlements registry that gates capabilities (video upload, family video call)
- `calls` — Family Video Call (Agora), Premium-gated token minting
- `notifications` — channel-agnostic dispatch (bell + email + Web Push), driven by domain events; see **Notifications** below

## Key flows

### Grandparent 60-second contribution (north star)
1. Child milestone is recorded (parent action or goal completion) → feed event + notification event
2. Grandparent receives email with a deep link (already authenticated or one-tap magic link)
3. One screen: milestone context + congratulate (message/emoji) + contribute (preset amounts, saved Stripe payment method) + optional record video message
4. Stripe PaymentIntent succeeds → webhook → ledger entry, feed event, thank-you notification
5. Async: `AnchorService` records contribution proof (invisible; stub in MVP)

### Media upload
Client requests presigned URL from API → uploads directly to S3 (local directory in dev) → confirms (server sniffs container bytes so video can't masquerade as image) → vault item row created → feed event emitted. Video uploads require the `video_upload` entitlement (Premium). Fetches authenticate with a short-lived media-scoped token, never the session JWT.

### Time capsule release
Capsules store a release condition. A scheduled job (EventBridge cron in prod, simple scheduler locally) evaluates date/age conditions; milestone conditions trigger on the corresponding feed event.

## Money-handling rules

- All monetary amounts are **integer cents** with explicit currency
- The future fund ledger is **append-only**; corrections are compensating entries, never updates
- Stripe is the source of truth for payment status; ledger entries are created only from verified webhook events
- **Real Future Fund accounts (Stripe Connect):** each child's fund is a Stripe Express connected account (legally the parent's, set up via hosted onboarding). Contributions are **destination charges** — the platform charges the card, keeps an application fee equal to the card-processing cost (2.9% + 30¢, ceiling; the platform nets ~0 and absorbs Amex/international variance and the kept processing fee on refunds), and Stripe transfers the net to the connected account. **FutureRoots holds no child balances**; the ledger records the net and settlement additionally verifies the live intent's destination + fee before writing. Connect account state arrives on a second webhook endpoint (`/webhooks/stripe-connect`, own signing secret) and is always re-fetched from Stripe, never trusted from a payload
- MVP holds no real invested assets — the ledger tracks contributions and balances only (RESP/ETF/custodial investments are future phases)
- **Premium (family subscription):** $9.99/mo · $99/yr via Stripe Checkout (`mode=subscription`), plus one-time $99 12-month gifts (`mode=payment`) from non-parents. Premium state is always **derived** from webhook-mirrored `family_subscriptions` + append-only `premium_grants` — never a stored flag. Gated capabilities (`video_upload`, `family_video_call`) are enforced server-side by a capability registry (`app/services/entitlements.py`) returning structured 402 `premium_required` errors. One Stripe Customer per adult user (`users.stripe_customer_id`); gift messages never go to Stripe (staged locally) so no child-adjacent free text leaves the platform. Full design: `docs/specs/premium-architecture.md`

## Runtime security & operations

- **Entitlements (Premium) are derived, never stored.** There is no `is_premium` flag anywhere; premium status is computed on every check from the webhook-mirrored `family_subscriptions` rows plus append-only `premium_grants`. A single capability registry (`app/services/entitlements.py`) is the server-side gate for premium features (structured 402 `premium_required` responses); clients render upsells but never enforce. New premium features add a capability and a `require_capability` call at the server choke point — never a parallel check.
- **Secrets load at cold start.** All runtime secrets live in one Secrets Manager secret (`futureroots/api`). The config layer fetches it once per Lambda cold start and overlays the values as env-var *defaults* — explicitly set env vars win, and with no secret ARN configured (local dev) there is no fetch at all, so local mode is untouched. Non-secret config (price ids, backends, base URLs) stays plain env.
- **Data lifecycle without a cron fleet.** A daily EventBridge rule invokes the API Lambda with a `maintenance` command — one idempotent sweep (staged-gift-intent and email-log prunes, stale fund nudges, abandoned-call end, call-presence retention). Same no-always-on-compute pattern as capsule release; it never touches money records.
- **Media fetches use scoped tokens, not session JWTs.** `GET /media/{id}` rejects session JWTs in the URL; browsers pass a short-lived media-scoped token (aud `futureroots:media`, 60-min TTL, minted at `POST /auth/media-token`) that is valid *only* on the media route, which still runs full per-media authorization on every fetch. Caps the query-string leak surface (Referer/history/logs) at an hour of read-only media access.

## Notifications

One channel-agnostic dispatcher, `app/services/notify.py`, backs every
notify()-worthy domain event: family member joins, milestones, memories,
legacy items, contributions, a child's fund activating, time-capsule
seal/release, a family video call going live, and platform-wide admin
broadcasts (ten `NotificationKind`s total — see the taxonomy table in the
module docstring). A single `notify()` call **always** writes an in-app
"bell" row per recipient (the `notifications` table), in the same
transaction as the domain change, and — gated by that recipient's
preferences — stages an email and/or a Web Push payload. **The bell is
never gated; only the interrupting channels (email, push) are**, so a user
who has muted everything still accrues a durable record of what happened.

- **One preference matrix, ten kinds × two channels.** `notification_preferences`
  is one row per user, global across all of that user's families (no
  per-family granularity) — 20 booleans (`email_*`/`push_*` per kind). A
  missing row falls back to `DEFAULT_PREFS`.
- **Post-commit delivery discipline.** Callers commit the domain transaction
  first, then call `batch.deliver(db)` — the same pattern established by
  `ContributionSettlement`. Bell rows roll back with a losing transaction
  (e.g. a replayed Stripe webhook that loses a unique-constraint race), and
  `deliver()` only runs after a successful commit, so replays can never
  double-send an email or a push notification.
- **Web Push (VAPID).** `push_subscriptions` holds one row per browser/device
  (keyed on the provider's unique `endpoint` URL; re-subscribing an existing
  endpoint reassigns it to the current user for shared-device handoff, and
  dead subscriptions — 404/410/403 on send — are pruned automatically).
  Delivery is inline and synchronous via `pywebpush`: one POST per
  subscription with a short timeout (`call_live` uses a 90s TTL / high
  urgency; everything else a 1-day TTL / normal urgency — the seam to make
  this asynchronous, if push volume ever grows, is `deliver()`). An empty
  `vapid_private_key` keeps the whole feature dark: subscribe 503s, the
  dispatcher sends no push, and the web settings page hides the enrollment
  card. The public key ships to the browser via `GET /me/notifications`
  (`push_public_key`), so lighting the feature up never needs an Amplify env
  var or a web rebuild.
- **SSRF allowlist on subscription endpoints.** Because the dispatcher POSTs
  to whatever `endpoint` a client submitted, from inside the VPC-egress
  Lambda, `app/push_targets.py` restricts accepted endpoints to the known Web
  Push provider origins (FCM/`googleapis.com`, Mozilla, Windows/Edge, Apple)
  and rejects IP-literal hosts outright — a registered endpoint can never
  turn push fan-out into an SSRF primitive against internal hosts or the
  instance metadata service.
- **The bell.** The `notifications` table (`kind`, `title`, `body`, `url`,
  optional `family_id`, `read_at`) is retained 90 days by the daily
  maintenance sweep. Read via `/me/inbox`: keyset-paginated list,
  unread-count, read-all, mark-one-read.
- **Admin broadcast.** `POST /admin/broadcast` reaches every non-disabled
  user (supporters included — platform content carries no family data); the
  bell is written even for users opted out of announcements, push/email are
  gated by `push_announcements`/`email_announcements`, and email is
  additionally opt-in per send (`include_email`) to protect SES quota and
  sender reputation. Audit-logged; supports a `dry_run` reach count before a
  real send.

## Compliance-driven design decisions

- **Child = profile, not account.** A `children` row has no credentials. Optional supervised child login is a future feature gated on parental consent records.
- **Consent records** are first-class data (who consented, for which child, when, to what).
- **Invite-only family graph** — a user only sees a family they were invited into; children's data is visible only within their family.
- **Deletability** — GDPR/PIPEDA erasure must be possible: media deletion cascades to S3; chain anchors store hashes/proofs only, never personal data.
