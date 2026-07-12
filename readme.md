# FutureRoots

**Building Generational Wealth & Memories**

FutureRoots is a Family Wealth Network that helps families preserve memories, transfer wisdom, teach financial literacy, and build generational wealth through a child-centered family platform. Blockchain is invisible infrastructure; the product is a warm, private family experience with zero crypto surface.

Every child gets a lifetime **FutureRoots Vault**: memories, milestones, family messages, time capsules, and a growing future fund that grandparents and relatives contribute to in moments of celebration.

## Status

**Live in production at [futureroots.app](https://futureroots.app).** All planned build phases are complete and deployed on AWS.

| Area | State |
|------|-------|
| Family Graph | Signup/login, families, child profiles (recorded parental consent), email invites |
| Vault, Feed & Memories | Photo/media upload (S3 presigned), private family feed, milestone posts with email notifications |
| Achievement Economy | Goals, badges, append-only future-fund ledger, one-screen grandparent contribution flow |
| Payments | Live Stripe (PaymentIntents + signature-verified webhook settlement) |
| Time Capsules & Legacy | Sealed capsules with age/date/milestone release; family legacy archive |
| Accounts | Password complexity + show/hide, forgot/reset, change password |
| Email | Branded HTML + plain-text, sent from a DKIM/SPF/DMARC-authenticated domain |
| Deployment | AWS via CDK (Lambda + RDS + S3 + SES, no-NAT VPC), web on Amplify, custom domain |

## Live surfaces

- **App:** https://futureroots.app · **API:** https://api.futureroots.app
- **Tester harness:** https://testnet.futureroots.app — a wallet-gated, gamified testing wrapper (Base Sepolia sign-in, quest catalog, real-time leaderboard, verified-bug rewards, tester avatars with optional X connection). Runs the same product against its own database with simulated payments; the family product exposes none of it.

## Repository layout

- `apps/api` — FastAPI + SQLAlchemy + Alembic (PostgreSQL). Domain modules: auth, families, children, vault, feed, goals, contributions, funds, capsules, legacy, notifications, plus the flag-gated `testnet` harness.
- `apps/web` — Next.js 15 + TypeScript + Tailwind. The family app; the testnet wrapper mounts only when `NEXT_PUBLIC_TESTNET` is set.
- `infra` — AWS CDK (TypeScript) stack for the whole deployment.
- `docs` — source-of-truth documentation (below).
- `.claude/agents` — the role-based AI team that builds and maintains the platform.

## Documentation

- [Vision](docs/vision.md) — product source of truth
- [Architecture](docs/architecture.md) — system design and stack
- [Data model](docs/data-model.md) — schema and access rules
- [Roadmap](docs/roadmap.md) — phased build plan (all phases complete)
- [Dev setup](docs/dev.md) — run the stack locally
- [Deployment](docs/deploy.md) — AWS runbook, custom domain, Stripe, email
- [Testnet harness](docs/testnet.md) — gamified tester program design
- [Agent team](docs/agents.md) — the AI role team in `.claude/agents/`

## Local development

Prereqs and full details in [docs/dev.md](docs/dev.md). In short: PostgreSQL 16, then

```
# API — http://localhost:8000 (docs at /docs)
cd apps/api && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload

# Web — http://localhost:3000
cd apps/web && npm install && npm run dev
```

## Non-negotiable principles

North star: a grandparent goes from milestone notification to congratulations to contribution to memory in under 60 seconds, never seeing blockchain. Children are profiles, not accounts (COPPA/GDPR/PIPEDA). Money is integer cents; the fund ledger is append-only; balances are always derived. Family-only and private by design.
