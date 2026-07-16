# FutureRoots — Build Roadmap

Local-first, web-first. Each phase ends with something demonstrable. AWS deployment is deferred until Phase 2 is worth showing to real family members.

## Phase 0 — Foundation docs ✅

- [x] Vision source of truth (`docs/vision.md`)
- [x] Architecture (`docs/architecture.md`)
- [x] Data model (`docs/data-model.md`)
- [x] Agent team structure (`.claude/agents/`)
- [x] CLAUDE.md for future sessions

## Phase 1 — Scaffold & Family Graph ✅ (done 2026-07-10)

Goal: a parent can sign up, create a family, add a child profile, and invite a grandparent — end to end locally.

- [x] Monorepo layout: `apps/web` (Next.js 16 + TS + Tailwind), `apps/api` (FastAPI + Pydantic + SQLAlchemy)
- [x] Native PostgreSQL 16 (winget service) instead of Docker — this machine has no WSL2; Docker can come later
- [x] Alembic migrations for identity & graph tables: `users`, `families`, `family_members`, `family_invites`, `children`, `child_relationships`, `consent_records`
- [x] Local auth (JWT dev issuer; Cognito abstraction later)
- [x] Parental-consent capture recorded at child-profile creation
- [x] Invite flow via email (dev outbox at `apps/api/var/outbox/` instead of Mailpit)
- [x] 17 API tests: auth, cross-family access denial, consent enforcement, role checks, invite lifecycle
- Deferred within phase: ShadCN adoption (hand-rolled Tailwind primitives in `src/components/ui.tsx` for now)

## Phase 2 — Vault, Feed & Memories ✅ (done 2026-07-10)

Goal: the family's private timeline is alive.

- [x] Media upload behind a `MediaStorage` abstraction — local disk (`apps/api/var/media/`) now, S3 presigned URLs later with the same client contract (ticket → PUT → attach)
- [x] `media_objects` (child-scoped for Family Graph access control), `vault_items`, `feed_events` tables + migration
- [x] Vault API: any family member adds memories (photos/messages); media never attaches across children; 25 MB upload cap
- [x] Milestone posting → vault item + feed event + email to every family member except the poster
- [x] Family Feed API + UI ("Family moments" on the family page), `member_joined` events on invite acceptance
- [x] Child Vault UI (`/family/[id]/child/[childId]`): milestone + memory forms with photo upload, vault timeline
- [x] 10 new tests (27 total): media access denial, foreign-media rejection, feed privacy, milestone email fan-out

## Phase 3 — Achievement Economy & Contributions ✅ (done 2026-07-10, north-star phase)

Goal: the 60-second grandparent flow works.

- [x] Goals + completions + badges; parents/guardians manage, whole family sees; achievement feed events
- [x] Payments behind a `PaymentProvider` abstraction — `LocalPaymentProvider` simulates the card flow; `record_payment_succeeded` is the ONLY ledger-write path, called only after provider verification (Stripe PaymentIntents + signed webhooks drop into the same seam — real Stripe wiring pending API keys)
- [x] `fund_accounts` + append-only `fund_ledger_entries`; balance always derived (SUM); idempotent settlement via unique source_contribution_id
- [x] One-screen grandparent flow (`/family/[id]/child/[childId]/contribute`): preset $10/$25/$50, note, single confirm — linked from milestone emails and feed events ("Celebrate with a gift")
- [x] Contribution fee in config basis points (default 250 = 2.5%), deducted from the gift
- [x] Goal completions never write the ledger (no phantom money — money rewards route through the real payment flow)
- [x] Parents emailed when someone contributes; contribution celebration on the feed
- [x] 13 new tests (40 total): fee math, idempotent confirm, derived balances, append-only corrections, role/outsider denials
- Deferred within phase: video message on contribution; time-to-contribution instrumentation
- ~~Real Stripe keys~~ → **done 2026-07-11**: live-mode PaymentIntents + Stripe Elements + signed-webhook settlement (see `docs/deploy.md`)

## Phase 4 — Time Capsules & Legacy Archive ✅ (done 2026-07-10)

- [x] `time_capsules` with age/date/milestone release conditions; sealed capsules reveal body/media only to their creator — everyone else sees existence + condition
- [x] Release: age/date capsules open via a lazy scheduler on access (`release_due_capsules` — an EventBridge cron calls the same function in prod); milestone capsules opened by creator or parent/guardian ("Open now")
- [x] Release → feed event + email to parents ("A time capsule for Emma just opened")
- [x] Family Legacy Archive (`legacy_items`): stories, recipes, documents, photos, wisdom — every member contributes; new `/family/[id]/legacy` page
- [x] Media now scoped to exactly one of child (vault/capsules) or family (legacy); download access follows the scope; family media can't attach to child vaults
- [x] 14 new tests (54 total): sealed privacy (no body/media leak), auto/manual release rules, permissions, archive access
- Deferred within phase: in-browser voice/video recording (file upload of audio/video works today; MediaRecorder UI later)

## Phase 5 — Deploy & Harden ✅ (deployed 2026-07-11)

- [x] AWS deployment via CDK (`infra/`), region us-east-1: no-NAT VPC, RDS Postgres 16 t4g.micro (private-only), Lambda/Mangum + HTTP API Gateway, private S3 media bucket, SES via PrivateLink — runbook in `docs/deploy.md`
- [x] Storage swap local→S3 (presigned up/down) and email swap outbox→SES were config-only — the abstractions held
- [x] Migrations run in-VPC via a Lambda management command
- [x] Web on Amplify Hosting (Next 15 — Amplify doesn't support 16 yet), builds from GitHub on push
- [x] Live: Web `https://futureroots.app` (+ www) · API `https://api.futureroots.app` — DNS in Cloudflare (domain registered there), certs via ACM
- [x] Cost ~$22–25/month — under the ~$50 ceiling
- Hardening backlog (see `docs/deploy.md`): Cognito swap, Secrets Manager, SES production access, custom domain + CloudFront/WAF, RDS deletion protection, formal COPPA/GDPR/PIPEDA review before real families

## Post-Phase 5 — Premium & hardening ✅ (Premium 2026-07-15 · hardening 2026-07-16)

- [x] **FutureRoots Premium** (live 2026-07-15): family-level membership $9.99/mo · $99/yr via Stripe Checkout subscriptions, plus one-time $99 12-month gifts from non-parents; entitlements always derived (never a stored flag) and server-enforced, gating video upload everywhere + Family Video Call; Free/Premium badges; 8 lifecycle emails; webhook-driven state in `family_subscriptions`/`premium_grants` — spec in `docs/specs/premium.md` + `premium-architecture.md`, Stripe interfaces in `.claude/skills/stripe-integration/SKILL.md`
- [x] **Hardening round** (2026-07-16): all runtime secrets in one Secrets Manager secret (`futureroots/api`, loaded at cold start; push via `infra/scripts/push_secrets.ps1`); RDS deletion protection + RETAIN; daily EventBridge maintenance command (data-lifecycle sweeps); leave-family/remove-member endpoints wired to `handle_owner_departure` (departing Premium owner's billing stops renewing; `member_left` feed event); contribution celebration emails post-commit only (double-send race fixed); race-safe fund-nudge throttle (migration `d41f7b6a90c3`); video-call 90-day retention + 15-min abandoned-call cap; CASL-safe informational "gift ending soon" email; EU/UK immediate-performance consent checkbox on both checkout pages (counsel review pending); media-scoped token auth for `GET /media/{id}`; GDPR/PIPEDA erasure runbook (`docs/erasure-runbook.md`); warm 503s on Stripe errors — 293 API tests passing
- Deferred by founder decision (2026-07-16): Cognito auth swap; CloudFront + WAF in front of the API. Next hardening step: Secrets-Manager-managed RDS master credential (the master password still sits inline in the CFN template)

## Phase 6 — AI & Growth

- Family Story Generator, Birthday Memory Generator (API-based models)
- Wisdom Search across messages/stories/archives
- Legacy Book Generator
- `AnchorService` real implementation on Base (contribution proofs; still invisible)
- React Native/Expo mobile app once the API is stable

## Explicitly deferred (do not build)

Trading, crypto wallets, DeFi, NFTs, complex investments (RESP/ETF come after real traction), enterprise white-labeling, custom/self-hosted AI models.
