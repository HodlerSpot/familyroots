# FutureRoots — System Architecture

Status: **design phase** — no code exists yet. This document describes the target architecture and the local-first development approach that precedes any AWS deployment.

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
| Media storage | S3 (prod) / local directory or MinIO (dev) | Presigned-URL uploads so media never flows through the API |
| Auth | Cognito (prod) behind an auth abstraction; simple JWT issuer in local dev | Children never authenticate independently |
| Payments | Stripe | PaymentIntents for contributions; webhooks drive ledger entries |
| Email | SES (prod) / console or Mailpit (dev) | Milestone notifications are the growth engine |
| Blockchain | Base, via an internal `AnchorService` interface | MVP implementation: no-op/stub that records intent; real chain writes later |
| AI | API-based only (Anthropic, OpenAI) | Later phase; never self-hosted models |

## Local-first development

Everything runs locally until there is something worth deploying:

- `docker compose` for PostgreSQL (and MinIO + Mailpit when media/email work starts)
- FastAPI via `uvicorn --reload`
- Next.js via `next dev`
- Cloud services (Cognito, SES, S3, Stripe live mode) are hidden behind thin interfaces with local implementations, so the swap to AWS is configuration, not rewrite.

## Target production deployment (AWS serverless)

- **CloudFront + S3** — Next.js static assets / web delivery
- **API Gateway + Lambda** — FastAPI via a Lambda adapter (e.g. Mangum)
- **Cognito** — authentication (parents, grandparents, relatives)
- **S3** — vault media (photos, video, audio), presigned upload/download
- **SES** — transactional and milestone-notification email
- **SNS / EventBridge** — event fan-out (milestone created → notify grandparents; contribution succeeded → ledger + feed + email)
- **RDS or Aurora Serverless v2 (PostgreSQL)** — the one relational store

Deployment is out of scope until the roadmap's foundation phase is done; this section exists so local design decisions stay Lambda-compatible (stateless handlers, no long-lived connections without pooling, event-driven side effects).

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
- `notifications` — email dispatch, driven by domain events

## Key flows

### Grandparent 60-second contribution (north star)
1. Child milestone is recorded (parent action or goal completion) → feed event + notification event
2. Grandparent receives email with a deep link (already authenticated or one-tap magic link)
3. One screen: milestone context + congratulate (message/emoji) + contribute (preset amounts, saved Stripe payment method) + optional record video message
4. Stripe PaymentIntent succeeds → webhook → ledger entry, feed event, thank-you notification
5. Async: `AnchorService` records contribution proof (invisible; stub in MVP)

### Media upload
Client requests presigned URL from API → uploads directly to S3/MinIO → confirms → vault item row created → feed event emitted.

### Time capsule release
Capsules store a release condition. A scheduled job (EventBridge cron in prod, simple scheduler locally) evaluates date/age conditions; milestone conditions trigger on the corresponding feed event.

## Money-handling rules

- All monetary amounts are **integer cents** with explicit currency
- The future fund ledger is **append-only**; corrections are compensating entries, never updates
- Stripe is the source of truth for payment status; ledger entries are created only from verified webhook events
- **Real Future Fund accounts (Stripe Connect):** each child's fund is a Stripe Express connected account (legally the parent's, set up via hosted onboarding). Contributions are **destination charges** — the platform charges the card, keeps an application fee equal to the card-processing cost (2.9% + 30¢, ceiling; the platform nets ~0 and absorbs Amex/international variance and the kept processing fee on refunds), and Stripe transfers the net to the connected account. **FutureRoots holds no child balances**; the ledger records the net and settlement additionally verifies the live intent's destination + fee before writing. Connect account state arrives on a second webhook endpoint (`/webhooks/stripe-connect`, own signing secret) and is always re-fetched from Stripe, never trusted from a payload
- MVP holds no real invested assets — the ledger tracks contributions and balances only (RESP/ETF/custodial investments are future phases)

## Compliance-driven design decisions

- **Child = profile, not account.** A `children` row has no credentials. Optional supervised child login is a future feature gated on parental consent records.
- **Consent records** are first-class data (who consented, for which child, when, to what).
- **Invite-only family graph** — a user only sees a family they were invited into; children's data is visible only within their family.
- **Deletability** — GDPR/PIPEDA erasure must be possible: media deletion cascades to S3; chain anchors store hashes/proofs only, never personal data.
