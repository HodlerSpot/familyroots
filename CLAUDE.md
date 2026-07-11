# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**FutureRoots** — a Family Wealth Network ("Building Generational Wealth & Memories"): families preserve memories, transfer wisdom, teach financial literacy, and build generational wealth around child-centered vaults. It is a **family platform, not a crypto product** — blockchain (Base) is invisible infrastructure only.

**Current status: Phase 5 complete — deployed to AWS.** All product phases (Family Graph, Vault/Feed/Memories, Achievement Economy, Time Capsules, Legacy Archive) are live: API on Lambda + RDS (us-east-1, CDK stack in `infra/`, runbook in `docs/deploy.md`), web on Amplify Hosting at `https://main.d2eorgdxfwgaam.amplifyapp.com`. SES is in sandbox mode. Next: Phase 6 (AI & growth) and the hardening backlog in `docs/deploy.md`.

## Source-of-truth documents (read before designing or building anything)

- `docs/vision.md` — product vision, personas, modules, MVP scope, positioning. **Authoritative; do not redesign the product.**
- `docs/architecture.md` — system design, stack, local-first dev approach, key flows
- `docs/data-model.md` — PostgreSQL schema design and access rules
- `docs/roadmap.md` — phased build plan and what's explicitly deferred
- `docs/agents.md` — the role-based agent team in `.claude/agents/` and the feature workflow

## Non-negotiable principles

1. **North star:** a grandparent goes from milestone notification → congratulations → contribution → memory in **under 60 seconds**, never seeing blockchain.
2. **Zero crypto surface:** no wallets, seed phrases, gas, tokens, or Web3/crypto terminology in any user-facing string, ever.
3. **Children are profiles, not accounts** (COPPA/GDPR/PIPEDA): no child credentials; parental consent is recorded data; access is scoped by explicit family relationships.
4. **Money discipline:** integer cents + currency; the future-fund ledger is append-only; ledger entries only from verified Stripe webhooks; balances always derived.
5. **Private by design:** family-only experience, no public social features, no cross-family data access.
6. **Local-first dev, Lambda-shaped code:** everything runs locally (docker-compose Postgres, uvicorn, next dev); cloud services (Cognito/SES/S3/Base) sit behind thin abstractions with local implementations. AWS deployment is Phase 5. MVP infra cost ceiling ~$50/month.

## Stack (decided — do not relitigate)

Web: Next.js + TypeScript + Tailwind + ShadCN (`apps/web`, planned) · API: FastAPI + Pydantic + SQLAlchemy/Alembic (`apps/api`, planned) · PostgreSQL · Stripe · S3 presigned uploads · AI via APIs only (no self-hosted models) · Mobile (Expo) deferred.

## Out of MVP scope (do not build)

Trading, crypto wallets, DeFi, NFTs, complex investments, enterprise white-labeling, custom AI models.

## Commands

Full setup details in `docs/dev.md`. Prereqs: Node 20+, uv, PostgreSQL 16 running as a Windows service (db/role `futureroots`/`futureroots` — see dev.md for the one-time SQL).

```powershell
# API (apps/api) — http://localhost:8000, OpenAPI docs at /docs
uv sync                                  # install deps
uv run alembic upgrade head              # apply migrations
uv run uvicorn app.main:app --reload     # run server
uv run pytest                            # all tests
uv run pytest tests/test_invites.py -k single_use   # single test
uv run alembic revision --autogenerate -m "msg"     # new migration after model changes

# Web (apps/web) — http://localhost:3000
npm install
npm run dev
npm run build                            # type-checks + production build
```

Dev email (invites) is written to `apps/api/var/outbox/` as text files — invite links are in there. On this machine `uv` lives at `$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe` and node at `C:\Program Files\nodejs` (add to PATH in fresh shells if not picked up).

Note: `apps/web` is **Next.js 15** (pinned — Amplify Hosting SSR doesn't support 16 yet; see `apps/web/AGENTS.md`). Dynamic-route `params` are Promises in server components (use `useParams()` in client components); `useSearchParams` needs a Suspense boundary.

## Brand voice

Warm, optimistic, family-centered, trustworthy. All user-facing copy goes through the `brand-guardian` agent's rules (`.claude/agents/brand-guardian.md`).
