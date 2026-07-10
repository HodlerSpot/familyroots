# FutureRoots — Build Roadmap

Local-first, web-first. Each phase ends with something demonstrable. AWS deployment is deferred until Phase 2 is worth showing to real family members.

## Phase 0 — Foundation docs ✦ (current)

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

## Phase 3 — Achievement Economy & Contributions (north-star phase)

Goal: the 60-second grandparent flow works.

- Goals + completions + badges
- Stripe integration: PaymentIntents, saved payment methods, webhook → ledger
- `fund_accounts` + append-only `fund_ledger_entries`, balances on the child vault
- The one-screen grandparent flow: milestone context → congratulate → contribute → optional video message
- Contribution fee handling
- **Measure it:** instrument time-from-notification-to-completed-contribution

## Phase 4 — Time Capsules & Legacy Archive

- `time_capsules` with age/date/milestone release conditions + release scheduler
- Family Legacy Archive (`legacy_items`): stories, recipes, documents, wisdom recordings
- Voice/video recording in-browser for capsules and wisdom

## Phase 5 — Deploy & Harden

- AWS serverless deployment (CloudFront, S3, API Gateway + Lambda/Mangum, Cognito, SES, RDS) — infrastructure as code
- Swap local auth → Cognito, Mailpit → SES, MinIO → S3 (config-only if abstractions held)
- Security & compliance review (COPPA/GDPR/PIPEDA checklist), data-erasure flow
- Cost check against the ~$50/month ceiling

## Phase 6 — AI & Growth

- Family Story Generator, Birthday Memory Generator (API-based models)
- Wisdom Search across messages/stories/archives
- Legacy Book Generator
- `AnchorService` real implementation on Base (contribution proofs; still invisible)
- React Native/Expo mobile app once the API is stable

## Explicitly deferred (do not build)

Trading, crypto wallets, DeFi, NFTs, complex investments (RESP/ETF come after real traction), enterprise white-labeling, custom/self-hosted AI models.
